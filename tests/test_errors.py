import io
from pathlib import Path
from types import SimpleNamespace

import pyrogram.errors
import pytest
from yt_dlp.networking import Response
from yt_dlp.networking.exceptions import HTTPError, ProxyError
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError

import config
from config import BotText
from engine.base import BaseDownloader
from engine.errors import classify, user_message

# yt-dlp source = the text is in the installed yt-dlp 2026.10.26 (file named);
# server text = what the site itself sends, passed through by yt-dlp (pinned 2026-11-14).
# A wording change upstream breaks this table on purpose.
CASES = [
    # blocked
    (
        "Sign in to confirm you’re not a bot. This helps protect our community.",
        "blocked",
    ),  # server text, YouTube
    (
        "Video unavailable. This content isn’t available, try again later. "
        "The current session has been rate-limited by YouTube for up to an hour.",
        "blocked",
    ),  # server text + yt-dlp source (youtube/_video.py appends the rate-limit sentence)
    (
        "The webpage request was redirected to the login page. "
        "You have exceeded the rate-limit for accessing posts anonymously",
        "blocked",
    ),  # yt-dlp source, instagram.py
    (
        "Your IP address is blocked from accessing this post",
        "blocked",
    ),  # yt-dlp source, tiktok.py
    (
        "All player responses are invalid. Your IP is likely being blocked by Youtube",
        "blocked",
    ),  # yt-dlp source, youtube/_video.py
    ("Unexpected response from webpage request", "blocked"),  # yt-dlp source, tiktok.py
    (
        "Instagram sent an empty media response.",
        "blocked",
    ),  # yt-dlp source, instagram.py
    # yt-dlp source, utils/_utils.py RetryManager: a fragment give-up carries no exception object
    (
        DownloadError(
            "[download] Got error: HTTP Error 403: Forbidden. Giving up after 10 retries"
        ),
        "blocked",
    ),
    (
        "YouTube is requiring a captcha challenge before playback",
        "blocked",
    ),  # yt-dlp source, youtube/_video.py
    # unavailable
    (
        "Private video. If the owner of this video has granted you access, please sign in.",
        "unavailable",
    ),  # server text, YouTube
    (
        "Video unavailable. This video is not available",
        "unavailable",
    ),  # server text, YouTube
    (
        "This content is only available for registered users who follow this account",
        "unavailable",
    ),  # yt-dlp source, instagram.py
    ("There is no video in this post", "unavailable"),  # yt-dlp source, instagram.py
    (
        "You do not have permission to view this post. Log into an account that has access",
        "unavailable",
    ),  # yt-dlp source, tiktok.py
    (
        "Join this channel to get access to members-only content like this video, and other exclusive perks.",
        "unavailable",
    ),  # server text, YouTube
    # login_required
    (
        "Sign in to confirm your age. This video may be inappropriate for some users.",
        "login_required",
    ),  # server text, YouTube
    (
        "Restricted Video: You must be 18 years old or over to see this video",
        "login_required",
    ),  # server text, Instagram
    (
        "TikTok is requiring login for access to this content",
        "login_required",
    ),  # yt-dlp source, tiktok.py
    # other
    ("Unsupported something odd", "other"),
    # yt-dlp source, YoutubeDL.py: a bad format choice is our problem, not the video's
    (
        "Requested format is not available. Use --list-formats for a list of available formats",
        "other",
    ),
]


def as_download_error(case):
    if isinstance(case, BaseException):
        return case
    inner = ExtractorError(case, expected=True)
    # the text sits only in exc_info[1], so the chain walk is what finds it
    return DownloadError("ERROR: download failed", (type(inner), inner, None))


@pytest.mark.parametrize("case, kind", CASES)
def test_classify_strings(case, kind):
    assert classify(as_download_error(case)) == kind


def test_geo_restricted_is_unavailable():
    # no regex matches this text, so only the type check can say "unavailable"
    geo = GeoRestrictedError(
        "The uploader has not made this video available in your country"
    )
    assert classify(geo) == "unavailable"
    assert (
        classify(DownloadError("ERROR: download failed", (type(geo), geo, None)))
        == "unavailable"
    )


def test_http_429_cause_is_blocked():
    response = Response(
        io.BytesIO(b""), "https://example.com/", {}, status=429, reason="x"
    )
    http = HTTPError(response)
    assert (
        classify(DownloadError("ERROR: download failed", (type(http), http, None)))
        == "blocked"
    )
    assert classify(ProxyError("tunnel failed")) == "blocked"


def test_user_message_copy():
    assert (
        user_message("login_required", "Instagram")
        == "Instagram needs a login for this video. The owner has been told."
    )
    assert (
        user_message("blocked", "YouTube")
        == "YouTube is blocking downloads right now. The owner has been told. Try again later."
    )
    assert (
        user_message("unavailable", "TikTok")
        == "This video is private, deleted or not available here."
    )
    assert user_message("other", "TikTok") == BotText.error


class FailingDownload(BaseDownloader):
    def _setup_formats(self):
        pass

    def _download(self, formats):
        pass

    def _start(self):
        inner = ExtractorError(
            "Private video. If the owner of this video has granted you access, please sign in."
        )
        raise DownloadError(
            "ERROR: http://10.0.0.1/x failed", (type(inner), inner, None)
        )


def failing_download(edits):
    dl = object.__new__(
        FailingDownload
    )  # skip __init__: no Telegram message, no temp dir
    dl._url = "https://www.youtube.com/watch?v=x"
    dl._tempdir = SimpleNamespace(cleanup=lambda: None)
    dl._get_video_cache = lambda: None
    dl._bot_msg = SimpleNamespace(edit_text=lambda text, **kwargs: edits.append(text))
    return dl


def test_failed_download_gets_one_reply():
    # the progress message turns into the classified text once; nothing is raised for the handler to reply again
    edits = []
    failing_download(edits).start()
    assert edits == [BotText.unavailable]


def test_flood_wait_reaches_handler():
    # the download handler's FloodWait branch tells the user to wait, so start() must not swallow it
    edits = []
    dl = failing_download(edits)

    def flood():
        raise pyrogram.errors.FloodWait(value=5)

    dl._start = flood
    with pytest.raises(pyrogram.errors.FloodWait):
        dl.start()
    assert edits == []


def test_engines_leave_error_replies_to_one_place():
    # engines raise; BaseDownloader.start() or the handler replies, once
    engine_dir = Path(config.__file__).resolve().parent.parent / "engine"
    offenders = [
        path.name
        for path in engine_dir.glob("*.py")
        if path.name != "errors.py"
        and "BotText.error" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
