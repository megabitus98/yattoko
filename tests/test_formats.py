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


def video(format_id, vcodec, height=1080, width=None):
    return dict(
        format_id=format_id,
        url=f"https://example.invalid/{format_id}",
        ext="mp4",
        vcodec=vcodec,
        acodec="none",
        height=height,
        width=width,
        filesize=10_000_000,
    )


def combined(format_id, vcodec, width, height):
    # one file with video and sound, as TikTok serves them
    return dict(
        format_id=format_id,
        url=f"https://example.invalid/{format_id}",
        ext="mp4",
        vcodec=vcodec,
        acodec="aac",
        width=width,
        height=height,
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
    assert options["format_sort"][:3] == ["vcodec:h264", "res:1080", "acodec:m4a"]
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


def test_single_file_before_audio_only():
    # TikTok: every video format has its sound inside, next to an audio-only mp3
    formats = [
        dict(format_id="audio", url="https://example.invalid/audio", ext="mp3", vcodec="none", acodec="mp3"),
        combined("h264_540p", "h264", 576, 1024),
        combined("bytevc1_720p", "h265", 720, 1280),
    ]
    assert select(build_format_options("1080p", "auto", "video", ""), formats) == "h264_540p"


def test_quality_limits_the_smaller_side():
    # a vertical 1080p video is 1080x1920: the setting must not drop it for being 1920 high
    formats = [
        video("v1080", "avc1.640028", 1920, 1080),
        video("v480", "avc1.4d401e", 854, 480),
        audio("a", None),
    ]
    assert select(build_format_options("1080p", "auto", "video", ""), formats) == "v1080+a"
    assert select(build_format_options("480p", "auto", "video", ""), formats) == "v480+a"
    wide = [video("h1080", "avc1.640028", 1080, 1920), video("h720", "avc1.4d401f", 720, 1280), audio("a", None)]
    assert select(build_format_options("720p", "auto", "video", ""), wide) == "h720+a"



def test_quality_first_takes_the_best_picture():
    # a short video gets the best picture up to the setting in any codec; transcode.py makes it H.264
    formats = [video("avc1", "avc1.640028", 1080, 1920), video("vp9", "vp9", 1440, 2560), audio("a", None)]
    assert select(build_format_options("1440p", "auto", "video", ""), formats) == "avc1+a"
    options = build_format_options("1440p", "auto", "video", "", quality_first=True)
    assert options["format_sort"][:2] == ["hdr:sdr", "res:1440"]
    assert select(options, formats) == "vp9+a"
    # same picture size: H.264 still wins, nothing to convert
    same = [video("vp9", "vp9", 1080, 1920), video("avc1", "avc1.640028", 1080, 1920), audio("a", None)]
    assert select(options, same) == "avc1+a"


def test_quality_first_prefers_sdr():
    # HDR forced into 8-bit H.264 looks washed out; YouTube has an SDR copy of every HDR video
    formats = [
        dict(video("hdr", "vp09.02.51.10", 1440, 2560), dynamic_range="HDR10"),
        dict(video("sdr", "vp9", 1440, 2560), dynamic_range="SDR"),
        audio("a", None),
    ]
    assert select(build_format_options("1440p", "auto", "video", "", quality_first=True), formats) == "sdr+a"
