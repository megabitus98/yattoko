import pytest
import yt_dlp

from database import model
from engine.generic import build_format_options


def select(options: dict, formats: list[dict]) -> str:
    # offline: yt-dlp sorts and picks from the given formats, nothing is fetched
    with yt_dlp.YoutubeDL({"quiet": True, **options}) as ydl:
        info = ydl.process_ie_result(
            {
                "id": "x",
                "title": "x",
                "extractor": "test",
                "extractor_key": "Test",
                "webpage_url": "https://example.invalid/x",
                "formats": formats,
            },
            download=False,
        )
    return info["format_id"]


def video(format_id, vcodec, height=1080):
    return dict(
        format_id=format_id,
        url=f"https://example.invalid/{format_id}",
        ext="mp4",
        vcodec=vcodec,
        acodec="none",
        height=height,
        filesize=10_000_000,
    )


def audio(format_id, language):
    return dict(
        format_id=format_id,
        url=f"https://example.invalid/{format_id}",
        ext="m4a",
        vcodec="none",
        acodec="mp4a.40.2",
        language=language,
        filesize=1_000_000,
    )


def test_auto_prefers_h264():
    options = build_format_options("1080p", "auto", "video", "")
    assert options["format_sort"][:3] == ["vcodec:h264", "res", "acodec:m4a"]
    assert options["merge_output_format"] == "mp4"
    formats = [
        video("vp9", "vp9"),
        video("av1", "av01.0.08M.08"),
        video("h264", "avc1.640028"),
        audio("a", None),
    ]
    assert select(options, formats) == "h264+a"


def test_stored_codec_value_is_understood():
    # the database stores the callback data ("vcodec-auto"); the default is H.264 first
    assert model.Setting.__table__.c.vcodec.default.arg == "vcodec-auto"
    assert model.get_vcodec_settings(-1) == "vcodec-auto"
    assert build_format_options(
        "1080p", "vcodec-auto", "video", ""
    ) == build_format_options("1080p", "auto", "video", "")


@pytest.mark.parametrize("send_as", ["video", "audio", "document"])
def test_no_russian_audio_by_default(send_as):
    assert (
        "language=" not in build_format_options("1080p", "auto", send_as, "")["format"]
    )


@pytest.mark.parametrize("send_as", ["video", "audio"])
def test_original_audio_track_by_default(send_as):
    # the extractor marks the original track with a higher language_preference
    dub = dict(audio("dub", "de"), language_preference=-1)
    original = dict(audio("original", "en"), language_preference=10)
    options = build_format_options("1080p", "auto", send_as, "")
    assert select(options, [video("v", "avc1.640028"), dub, original]).endswith(
        "original"
    )


@pytest.mark.parametrize("send_as", ["video", "audio"])
def test_audio_lang_filter(send_as):
    options = build_format_options("1080p", "auto", send_as, "en")
    assert "[language^=en]" in options["format"]
    assert "/bestaudio" in options["format"].split("[language^=en]", 1)[1]
    formats = [video("v", "avc1.640028"), audio("de", "de"), audio("en", "en")]
    assert select(options, formats).endswith("en")
    # region-tagged tracks count: en-US is English
    assert select(options, [*formats[:2], audio("en-US", "en-US")]).endswith("en-US")
    # no English track: any audio instead of failing
    assert select(options, formats[:2]).endswith("de")


@pytest.mark.parametrize("vcodec", ["auto", "vp9", "avc1", "av01"])
@pytest.mark.parametrize("send_as", ["video", "audio", "document"])
@pytest.mark.parametrize("audio_lang", ["", "en"])
def test_format_parses(vcodec, send_as, audio_lang):
    options = build_format_options("720p", vcodec, send_as, audio_lang)
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        ydl.build_format_selector(options["format"])


def test_codec_setting_overrides():
    formats = [video("vp9", "vp9"), video("h264", "avc1.640028"), audio("a", None)]
    assert select(build_format_options("1080p", "vp9", "video", ""), formats) == "vp9+a"
