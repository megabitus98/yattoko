from types import SimpleNamespace

import pytest
import yt_dlp
from pyrogram import enums

import main
from config import BotText
from database.model import init_user, set_user_settings
from engine import base
from engine.generic import RefusedContent, YoutubeDownload, attempt, single_video_only
from engine.proxy import ydl_proxy
from fakes import FakeClient, fake_message

VIDEO = {"id": "x", "title": "x"}


@pytest.fixture
def fake_ydl(monkeypatch):
    # Stands in for yt_dlp.YoutubeDL: extract_info hands out state.results in order, nothing is fetched.
    state = SimpleNamespace(results=[], instances=[])

    class FakeYDL:
        def __init__(self, params=None):
            self.params, self.calls = params or {}, []
            state.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(
            self, url, download=True, ie_key=None, extra_info=None, process=True
        ):
            self.calls.append(("extract_info", url, download, process))
            return dict(state.results.pop(0))

        def process_ie_result(self, info, download=True, extra_info=None):
            self.calls.append(("process_ie_result", info, download))
            return info

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    return state


def calls(state, name):
    return [c for i in state.instances for c in i.calls if c[0] == name]


def make_downloader(
    monkeypatch, url, user_id=2, chat_id=None, chat_type=enums.ChatType.PRIVATE
):
    # the bot's progress message: in a group it replies to the requester's message
    monkeypatch.setattr(
        base,
        "Redis",
        lambda: SimpleNamespace(get_cache=lambda key: {}, add_cache=lambda *a: None),
    )
    edits = []
    bot_msg = SimpleNamespace(
        id=10,
        chat=SimpleNamespace(
            id=user_id if chat_id is None else chat_id, type=chat_type
        ),
        reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=user_id)),
        edit_text=lambda text, **kwargs: edits.append(text),
    )
    return YoutubeDownload(FakeClient(), bot_msg, url), edits


@pytest.mark.parametrize("kind", ["playlist", "multi_video"])
def test_playlist_refused_before_download(fake_ydl, tmp_path, kind):
    fake_ydl.results = [{"_type": kind, "entries": []}]
    with pytest.raises(RefusedContent):
        attempt("https://www.youtube.com/@channel", "youtube", "direct", {}, tmp_path)
    assert calls(fake_ydl, "process_ie_result") == []


@pytest.mark.parametrize("live", [{"is_live": True}, {"live_status": "is_live"}])
def test_live_refused(fake_ydl, tmp_path, live):
    # YouTube's raw result has only live_status; is_live is filled in later by yt-dlp
    fake_ydl.results = [VIDEO | live]
    with pytest.raises(RefusedContent):
        attempt("https://www.youtube.com/watch?v=x", "youtube", "direct", {}, tmp_path)
    assert calls(fake_ydl, "process_ie_result") == []


def test_url_to_playlist_refused(fake_ydl, tmp_path):
    fake_ydl.results = [
        {
            "_type": "url",
            "url": "https://www.youtube.com/@channel/videos",
            "ie_key": "YoutubeTab",
        },
        {"_type": "playlist", "entries": []},
    ]
    with pytest.raises(RefusedContent):
        attempt("https://youtu.be/channel-ish", "youtube", "direct", {}, tmp_path)
    assert calls(fake_ydl, "process_ie_result") == []


def test_single_video_downloads_in_same_instance(fake_ydl, tmp_path):
    fake_ydl.results = [VIDEO]
    url = "https://www.youtube.com/watch?v=x"
    assert attempt(url, "youtube", "direct", {"quiet": True}, tmp_path) == VIDEO
    [ydl] = fake_ydl.instances
    # extracted without processing (a channel's entries are not walked), then downloaded in that instance
    assert ydl.calls == [
        ("extract_info", url, False, False),
        ("process_ie_result", VIDEO, True),
    ]
    assert ydl.params["quiet"] is True
    assert ydl.params["proxy"] == ""
    assert ydl.params["outtmpl"].startswith(tmp_path.as_posix() + "/")


def test_short_link_followed_once(fake_ydl, tmp_path):
    # the pointer is followed without downloading; the resolved video is not extracted a second time
    fake_ydl.results = [
        {
            "_type": "url",
            "url": "https://www.tiktok.com/@a/video/1",
            "ie_key": "TikTok",
        },
        VIDEO,
    ]
    attempt("https://vm.tiktok.com/ZMabcdef/", "tiktok", "direct", {}, tmp_path)
    assert [c[1:] for c in calls(fake_ydl, "extract_info")] == [
        ("https://vm.tiktok.com/ZMabcdef/", False, False),
        ("https://www.tiktok.com/@a/video/1", False, False),
    ]
    assert calls(fake_ydl, "process_ie_result") == [("process_ie_result", VIDEO, True)]
    assert len(fake_ydl.instances) == 1


def test_list_in_url_not_refused(fake_ydl, tmp_path, downloads):
    url = "https://www.youtube.com/watch?v=x&list=y"
    message, replies = fake_message(url)
    main.download_handler(FakeClient(), message)
    assert downloads == ["youtube_entrance"]
    assert replies == [BotText.downloading]

    fake_ydl.results = [VIDEO]
    assert attempt(url, "youtube", "direct", {}, tmp_path) == VIDEO
    # without noplaylist yt-dlp hands this URL to the playlist extractor
    assert fake_ydl.instances[0].params["noplaylist"] is True
    assert calls(fake_ydl, "process_ie_result") == [("process_ie_result", VIDEO, True)]


def test_gdrive_source_first(fake_ydl, monkeypatch):
    for url, source in [
        ("https://drive.google.com/file/d/abc/view", True),
        ("https://www.youtube.com/watch?v=x", False),
    ]:
        downloader, _ = make_downloader(monkeypatch, url)
        fake_ydl.results = [VIDEO]
        downloader._download(downloader._setup_formats())
        params = fake_ydl.instances[-1].params
        assert params["format"].startswith("source/") is source
        assert "playlist_items" not in params


def test_proxy_exit():
    assert ydl_proxy("direct") == ""
    assert ydl_proxy("http://proxy.example:8080") == "http://proxy.example:8080"
    assert ydl_proxy("socks5://proxy.example:1080") == "socks5://proxy.example:1080"


def test_refused_reply(fake_ydl, monkeypatch):
    downloader, edits = make_downloader(monkeypatch, "https://www.youtube.com/@channel")
    fake_ydl.results = [{"_type": "playlist", "entries": []}]
    downloader.start()
    assert edits == [BotText.refused]
    assert (
        BotText.refused
        == "Send a link to a single video, not a playlist, channel or live stream."
    )


def test_settings_read_by_requesting_user(fake_ydl, monkeypatch):
    # in a group the chat ID is the group's; the settings belong to the person who sent the link
    init_user(777)
    set_user_settings(777, "format", "audio")
    set_user_settings(777, "quality", "720p")
    set_user_settings(777, "sponsorblock", "remove")
    downloader, _ = make_downloader(
        monkeypatch,
        "https://www.youtube.com/watch?v=x",
        user_id=777,
        chat_id=-100123,
        chat_type=enums.ChatType.SUPERGROUP,
    )
    assert (downloader._format, downloader._quality) == ("audio", "720p")
    fake_ydl.results = [VIDEO]
    downloader._download(downloader._setup_formats())
    keys = [pp["key"] for pp in fake_ydl.instances[0].params["postprocessors"]]
    assert "FFmpegExtractAudio" in keys and "SponsorBlock" in keys


def video_formats():
    return [
        dict(
            format_id="v",
            url="https://example.invalid/v",
            ext="mp4",
            vcodec="avc1.640028",
            acodec="mp4a.40.2",
            height=720,
        )
    ]


@pytest.mark.parametrize(
    "info",
    [
        # a playlist that slips past the first check (behind a url_transparent hop) stops at its first entry
        {
            "_type": "playlist",
            "id": "p",
            "title": "p",
            "entries": [{"id": "x", "title": "x", "formats": video_formats()}],
        },
        {"id": "x", "title": "x", "formats": video_formats(), "live_status": "is_live"},
    ],
)
def test_match_filter_backstop(info):
    # offline, real yt-dlp: the filter's exception reaches the caller before anything is downloaded
    with yt_dlp.YoutubeDL({"quiet": True, "match_filter": single_video_only}) as ydl:
        with pytest.raises(RefusedContent):
            ydl.process_ie_result(
                dict(
                    info,
                    extractor="test",
                    extractor_key="Test",
                    webpage_url="https://example.invalid/x",
                ),
                download=False,
            )


def test_match_filter_passes_single_video():
    assert (
        single_video_only({"id": "x", "live_status": "not_live"}, incomplete=False)
        is None
    )
