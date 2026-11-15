from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp
from pyrogram import enums

import main
from config import BotText
from database.model import init_user, set_user_settings
from engine.generic import RefusedContent, attempt, single_video_only
from engine.proxy import ydl_proxy
from fakes import FakeClient, fake_downloader, fake_message

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

        def build_format_selector(self, spec):
            return ("selector", spec)

        def process_ie_result(self, info, download=True, extra_info=None):
            self.calls.append(("process_ie_result", info, download))
            return info

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    return state


def calls(state, name):
    return [c for i in state.instances for c in i.calls if c[0] == name]


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


def test_gdrive_source_first(fake_ydl):
    for url, source in [
        ("https://drive.google.com/file/d/abc/view", True),
        ("https://www.youtube.com/watch?v=x", False),
    ]:
        downloader, _ = fake_downloader(url)
        fake_ydl.results = [VIDEO]
        downloader._download(downloader._setup_formats())
        params = fake_ydl.instances[-1].params
        assert params["format"].startswith("source/") is source
        assert "playlist_items" not in params


def test_proxy_exit():
    assert ydl_proxy("direct") == ""
    assert ydl_proxy("http://proxy.example:8080") == "http://proxy.example:8080"
    assert ydl_proxy("socks5://proxy.example:1080") == "socks5://proxy.example:1080"


def test_refused_reply(fake_ydl):
    downloader, edits = fake_downloader("https://www.youtube.com/@channel")
    fake_ydl.results = [{"_type": "playlist", "entries": []}]
    downloader.start()
    assert edits == [BotText.refused]
    assert (
        BotText.refused
        == "Send a link to a single video, not a playlist, channel or live stream."
    )


def test_settings_read_by_requesting_user(fake_ydl):
    # in a group the chat ID is the group's; the settings belong to the person who sent the link
    init_user(777)
    set_user_settings(777, "format", "audio")
    set_user_settings(777, "quality", "720p")
    set_user_settings(777, "sponsorblock", "remove")
    downloader, _ = fake_downloader(
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


def test_instagram_single_file_first():
    # Instagram's single files are H.264 with sound, but yt-dlp lists their codecs as unknown,
    # so the codec sort ranks them below the separate VP9 streams (VP9 shows one frame on a Mac)
    from test_formats import select

    downloader, _ = fake_downloader("https://www.instagram.com/reel/abc/")
    formats = [
        {"format_id": "1", "url": "https://example.invalid/1", "ext": "mp4"},
        {"format_id": "dash-v", "url": "https://example.invalid/v", "ext": "mp4", "vcodec": "vp09.00.31.08",
         "acodec": "none", "width": 720, "height": 1280, "tbr": 767},
        {"format_id": "dash-a", "url": "https://example.invalid/a", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a.40.5", "tbr": 55},
    ]
    assert select(downloader._setup_formats(), formats) == "1"
    other, _ = fake_downloader("https://www.youtube.com/watch?v=x")
    assert not other._setup_formats()["format"].startswith("best/")


def test_tiktok_prefers_h265():
    # TikTok's H.264 files stop at 540p with 32 kb/s sound; its H.265 files reach 1080p with 64 kb/s
    from test_formats import select

    def fmt(format_id, vcodec, acodec, width=None, height=None, ext="mp4"):
        return {"format_id": format_id, "url": f"https://example.invalid/{format_id}", "ext": ext,
                "vcodec": vcodec, "acodec": acodec, "width": width, "height": height}

    formats = [
        fmt("audio", "none", "mp3", ext="mp3"),
        fmt("h264_540p", "h264", "aac", 576, 1024),
        fmt("bytevc1_720p", "h265", "aac", 720, 1280),
        fmt("bytevc1_1080p", "h265", "aac", 1080, 1920),
    ]
    init_user(778)
    downloader, _ = fake_downloader("https://www.tiktok.com/@someone/video/1", user_id=778)
    assert select(downloader._setup_formats(), formats) == "bytevc1_1080p"
    # a codec chosen in /settings still wins
    set_user_settings(778, "vcodec", "vcodec-avc1")
    downloader, _ = fake_downloader("https://www.tiktok.com/@someone/video/1", user_id=778)
    assert select(downloader._setup_formats(), formats) == "h264_540p"
    # other sites keep H.264 first
    other, _ = fake_downloader("https://www.youtube.com/watch?v=x")
    assert other._setup_formats()["format_sort"][0] == "vcodec:h264"


def test_instagram_codec_setting_wins():
    # Instagram's 1080p exists only as VP9; whoever picks VP9 in /settings gets it
    from test_formats import select

    formats = [
        {"format_id": "1", "url": "https://example.invalid/1", "ext": "mp4"},
        {"format_id": "vp9-720", "url": "https://example.invalid/v7", "ext": "mp4", "vcodec": "vp09.00.31.08",
         "acodec": "none", "width": 720, "height": 1280, "tbr": 729},
        {"format_id": "vp9-1080", "url": "https://example.invalid/v10", "ext": "mp4", "vcodec": "vp09.00.40.08",
         "acodec": "none", "width": 1080, "height": 1920, "tbr": 1391},
        {"format_id": "a", "url": "https://example.invalid/a", "ext": "m4a", "vcodec": "none",
         "acodec": "mp4a.40.5", "tbr": 46},
    ]
    init_user(779)
    set_user_settings(779, "vcodec", "vcodec-vp9")
    downloader, _ = fake_downloader("https://www.instagram.com/reel/abc/", user_id=779)
    assert select(downloader._setup_formats(), formats) == "vp9-1080+a"


def test_short_video_switches_to_quality_first(fake_ydl, tmp_path):
    # the duration is known only after extraction; attempt() then rebuilds the format choice
    picked = {"format": "best", "format_sort": ["hdr:sdr", "res:1440"]}
    fake_ydl.results = [dict(VIDEO, duration=30)]
    attempt("https://www.youtube.com/watch?v=x", "youtube", "direct", {"format": "x"}, tmp_path,
            choose=lambda info: picked if info["duration"] < 60 else None)
    ydl = fake_ydl.instances[-1]
    assert ydl.params["format_sort"] == picked["format_sort"]
    assert ydl.format_selector == ("selector", "best")


def test_choose(monkeypatch):
    from engine import generic

    monkeypatch.setattr(generic, "REENCODE_MAX_SECONDS", 300)
    monkeypatch.setattr(generic, "ENABLE_FFMPEG", False)
    init_user(780)
    downloader, _ = fake_downloader("https://www.instagram.com/reel/abc/", user_id=780)
    assert downloader._choose({"duration": 30}) is None  # switched off: H.264 first as before
    monkeypatch.setattr(generic, "ENABLE_FFMPEG", True)
    downloader, _ = fake_downloader("https://www.instagram.com/reel/abc/", user_id=780)
    picked = downloader._choose({"duration": 30})
    assert picked["format_sort"][:2] == ["hdr:sdr", "res:1440"]  # 2K by default
    assert not picked["format"].startswith("best/")  # the VP9 1080p beats Instagram's 720p H.264 file
    assert downloader._choose({"duration": 301}) is None
    # unknown length (Instagram gives none): best picture; the file's real length decides afterwards
    assert downloader._choose({})["format_sort"][0] == "hdr:sdr"
    monkeypatch.setattr(generic, "REENCODE_MAX_SECONDS", 0)
    assert downloader._choose({"duration": 30}) is None
    monkeypatch.setattr(generic, "REENCODE_MAX_SECONDS", 300)
    set_user_settings(780, "vcodec", "vcodec-vp9")
    downloader, _ = fake_downloader("https://www.instagram.com/reel/abc/", user_id=780)
    assert downloader._choose({"duration": 30}) is None  # a codec chosen in /settings is kept


def test_converted_after_download(fake_ydl, monkeypatch):
    from engine import generic

    monkeypatch.setattr(generic, "ENABLE_FFMPEG", True)
    converted = []

    def fake_to_h264(path, max_side, max_seconds, timeout, on_start=None):
        if path.name == "vp9.mp4":
            on_start()
            converted.append((path.name, max_side, max_seconds))
            return True
        return False

    monkeypatch.setattr(generic.transcode, "to_h264", fake_to_h264)
    init_user(781)
    downloader, edits = fake_downloader("https://www.youtube.com/watch?v=x", user_id=781)
    fake_ydl.results = [dict(VIDEO, duration=30)]
    (Path(downloader._tempdir.name) / "vp9.mp4").write_bytes(b"x")
    downloader._download(downloader._setup_formats())
    assert converted == [("vp9.mp4", 1440, generic.REENCODE_MAX_SECONDS)]
    assert edits == [BotText.converting]
    # an H.264 file: no conversion, no message
    edits.clear()
    (Path(downloader._tempdir.name) / "vp9.mp4").rename(Path(downloader._tempdir.name) / "h264.mp4")
    fake_ydl.results = [dict(VIDEO, duration=30)]
    downloader._download(downloader._setup_formats())
    assert edits == []


def test_too_long_to_convert_downloads_again_h264_first(fake_ydl, monkeypatch):
    # unknown length, best picture taken, the file turns out longer than REENCODE_MAX_SECONDS
    from engine import generic

    monkeypatch.setattr(generic, "ENABLE_FFMPEG", True)

    def too_long(path, max_side, max_seconds, timeout, on_start=None):
        raise generic.transcode.TooLong()

    monkeypatch.setattr(generic.transcode, "to_h264", too_long)
    init_user(782)
    downloader, edits = fake_downloader("https://www.instagram.com/reel/abc/", user_id=782)
    # Instagram as it lists a reel: the single H.264 file without size, VP9 streams with sizes
    listed = [{"format_id": "1"}, {"format_id": "v", "vcodec": "vp09.00.40.08", "acodec": "none", "width": 1080, "height": 1920}]
    fake_ydl.results = [dict(VIDEO, formats=listed), dict(VIDEO, formats=listed)]
    (Path(downloader._tempdir.name) / "vp9.mp4").write_bytes(b"x")
    downloader._download(downloader._setup_formats())
    first, second = fake_ydl.instances
    assert first.format_selector[0] == "selector"  # quality first
    assert not hasattr(second, "format_selector")  # H.264 first, as built
    assert second.params["format"].startswith("best/")  # Instagram's H.264 file
    assert list(Path(downloader._tempdir.name).iterdir()) == []  # emptied before the second download
    assert edits == []


def test_caption_is_plain_text(tmp_path):
    # a title with "<i" or "*" must not be read as formatting (kurigram: "Unclosed tags: <i>")
    from pyrogram import enums

    sent = []
    downloader, _ = fake_downloader("https://www.youtube.com/watch?v=x")
    # _methods looks up every send_* method, so the fake client has them all
    record = lambda **kwargs: sent.append(kwargs)
    downloader._client = SimpleNamespace(
        send_chat_action=lambda *a, **k: None, send_video=record, send_document=record,
        send_audio=record, send_animation=record, send_photo=record,
    )
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    downloader.send_something(chat_id=1, files=[video], _type="video", caption="<i>title *x*")
    assert sent[0]["caption"] == "<i>title *x*"
    assert sent[0]["parse_mode"] == enums.ParseMode.DISABLED


def _ffmpeg_on(monkeypatch):
    from engine import generic

    monkeypatch.setattr(generic, "ENABLE_FFMPEG", True)
    return generic


def test_conversion_failure_sends_the_original(fake_ydl, monkeypatch):
    generic = _ffmpeg_on(monkeypatch)

    def broken(path, max_side, max_seconds, timeout, on_start=None):
        raise generic.transcode.ConversionFailed("[libx264] width not divisible by 2")

    monkeypatch.setattr(generic.transcode, "to_h264", broken)
    downloader, _ = fake_downloader("https://www.youtube.com/watch?v=x")
    fake_ydl.results = [dict(VIDEO, duration=30)]
    (Path(downloader._tempdir.name) / "vp9.mp4").write_bytes(b"x")
    assert [p.name for p in downloader._download(downloader._setup_formats())] == ["vp9.mp4"]


def test_conversion_timeout_is_not_read_as_login(fake_ydl, monkeypatch):
    # the ffmpeg command holds the file name, so the video title; it must not decide the reply
    import subprocess

    from engine.errors import classify
    from engine.jobs import JobTimeout

    generic = _ffmpeg_on(monkeypatch)

    def slow(path, max_side, max_seconds, timeout, on_start=None):
        raise subprocess.TimeoutExpired(["ffmpeg", "-i", "/tmp/x/How to sign in to Gmail.mp4"], timeout)

    monkeypatch.setattr(generic.transcode, "to_h264", slow)
    downloader, _ = fake_downloader("https://www.youtube.com/watch?v=x")
    fake_ydl.results = [dict(VIDEO, duration=30)]
    (Path(downloader._tempdir.name) / "vp9.mp4").write_bytes(b"x")
    with pytest.raises(JobTimeout) as stopped:
        downloader._download(downloader._setup_formats())
    assert stopped.value.__context__ is None
    assert classify(stopped.value) == "other"


def test_converting_message_shown_right_after_progress(monkeypatch):
    # the progress edits are throttled to one per 5 s; the converting message must not be dropped
    downloader, edits = fake_downloader("https://www.youtube.com/watch?v=x")
    downloader.edit_text("▶️ Downloading 99 %")
    downloader._say_converting()
    assert edits[-1] == BotText.converting


def test_instagram_up_to_720_stays_h264_first(monkeypatch):
    # Instagram's single H.264 file (size not listed) has been 720p in every reel seen; a VP9 stream of
    # the same size is not worth converting
    _ffmpeg_on(monkeypatch)
    init_user(783)
    downloader, _ = fake_downloader("https://www.instagram.com/reel/abc/", user_id=783)
    single = {"format_id": "1", "url": "https://example.invalid/1", "ext": "mp4"}
    vp9 = lambda side: {"format_id": f"v{side}", "vcodec": "vp09.00.31.08", "acodec": "none", "width": side, "height": side * 16 // 9}
    assert downloader._choose({"formats": [single, vp9(720)]}) is None
    assert downloader._choose({"formats": [single, vp9(720), vp9(1080)]})["format_sort"][0] == "hdr:sdr"


def test_too_long_single_format_is_sent_as_it_is(fake_ydl, monkeypatch):
    # a direct link has one format: downloading it again H.264 first would fetch the same file
    generic = _ffmpeg_on(monkeypatch)

    def too_long(path, max_side, max_seconds, timeout, on_start=None):
        raise generic.transcode.TooLong()

    monkeypatch.setattr(generic.transcode, "to_h264", too_long)
    downloader, _ = fake_downloader("https://example.com/film.webm")
    fake_ydl.results = [dict(VIDEO, formats=[{"format_id": "webm", "url": "https://example.com/film.webm"}])]
    (Path(downloader._tempdir.name) / "film.webm").write_bytes(b"x")
    assert [p.name for p in downloader._download(downloader._setup_formats())] == ["film.webm"]
    assert len(fake_ydl.instances) == 1


def test_format_sorting_is_serialised(monkeypatch):
    # yt-dlp's FormatSorter keeps its limits (res:N, hdr:sdr, vcodec:...) in a class-level dict, so two
    # jobs sorting at once would use each other's limits; generic.py holds one lock while yt-dlp sorts
    from engine import generic
    from yt_dlp.utils import FormatSorter

    held = []
    real = FormatSorter.calculate_preference
    monkeypatch.setattr(FormatSorter, "calculate_preference", lambda self, f: held.append(generic.SORT_LOCK.locked()) or real(self, f))
    from test_formats import select

    select(generic.build_format_options("720p", "auto", "video", ""), [
        {"format_id": "a", "url": "https://example.invalid/a", "ext": "mp4", "vcodec": "avc1", "acodec": "aac", "width": 1280, "height": 720},
        {"format_id": "b", "url": "https://example.invalid/b", "ext": "mp4", "vcodec": "avc1", "acodec": "aac", "width": 640, "height": 360},
    ])
    assert held and all(held)
