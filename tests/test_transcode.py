import json
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import transcode

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def make_clip(tmp_path: Path, codec: str = "libvpx-vp9", size: str = "640x360") -> Path:
    # one second of picture and sound plus an embedded cover, the shape yt-dlp leaves behind
    cover = tmp_path / "cover.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", cover], check=True)
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-i", cover,
         "-map", "0:v", "-map", "1:a", "-map", "2", "-c:v:0", codec, "-c:a", "aac", "-c:v:1", "mjpeg",
         "-disposition:v:1", "attached_pic", clip],
        check=True,
    )
    return clip


def streams(path: Path) -> list[dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:stream_disposition=attached_pic",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


def test_vp9_becomes_h264_with_sound_and_cover(tmp_path):
    clip = make_clip(tmp_path)
    assert transcode.to_h264(clip, max_side=1440, max_seconds=300, timeout=60) is True
    found = streams(clip)
    main = [s for s in found if s["codec_type"] == "video" and not s["disposition"]["attached_pic"]]
    assert [(s["codec_name"], s["width"], s["height"]) for s in main] == [("h264", 640, 360)]
    assert [s["codec_name"] for s in found if s["codec_type"] == "audio"] == ["aac"]
    assert any(s["disposition"]["attached_pic"] for s in found)  # the upload takes its thumbnail from it
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4", "cover.jpg"]  # replaced in place


def test_smaller_side_capped(tmp_path):
    clip = make_clip(tmp_path)
    transcode.to_h264(clip, max_side=240, max_seconds=300, timeout=60)
    main = [s for s in streams(clip) if s["codec_type"] == "video" and not s["disposition"]["attached_pic"]]
    assert (main[0]["width"], main[0]["height"]) == (426, 240)


def test_left_alone(tmp_path):
    vp9 = make_clip(tmp_path)
    before = vp9.read_bytes()
    assert transcode.to_h264(vp9, max_side=1440, max_seconds=0, timeout=60) is False  # switched off
    with pytest.raises(transcode.TooLong):  # needs converting, but longer than the limit
        transcode.to_h264(vp9, max_side=1440, max_seconds=0.5, timeout=60)
    assert vp9.read_bytes() == before
    h264_dir = tmp_path / "h264"
    h264_dir.mkdir()
    h264 = make_clip(h264_dir, codec="libx264")
    assert transcode.to_h264(h264, max_side=1440, max_seconds=300, timeout=60) is False


def test_timeout_leaves_the_source(tmp_path):
    clip = make_clip(tmp_path)
    before = clip.read_bytes()
    with pytest.raises(subprocess.TimeoutExpired):
        transcode.to_h264(clip, max_side=1440, max_seconds=300, timeout=0.001)
    assert clip.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4", "cover.jpg"]


def test_playable():
    assert transcode.playable("h264", "avc1")
    assert transcode.playable("hevc", "hvc1")  # TikTok's H.265, plays in Telegram on iPhone and Mac
    assert not transcode.playable("hevc", "hev1")  # Apple players need hvc1
    assert not transcode.playable("vp9", "vp09")
    assert not transcode.playable("av1", "av01")


def video_size(path: Path, displayed: bool = False) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "V:0", "-show_entries", "stream=width,height:stream_side_data=rotation",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    stream = json.loads(out)["streams"][0]
    rotation = next((d.get("rotation") for d in stream.get("side_data_list", []) if "rotation" in d), 0)
    if displayed and abs(int(rotation)) % 180 == 90:
        return stream["height"], stream["width"]
    return stream["width"], stream["height"]


def test_vertical_smaller_side_capped(tmp_path):
    clip = make_clip(tmp_path, size="360x640")
    transcode.to_h264(clip, max_side=240, max_seconds=300, timeout=60)
    assert video_size(clip) == (240, 426)


def test_rotated_video_capped_on_its_shown_smaller_side(tmp_path):
    # coded 640x360, shown 360x640 (a phone upload); ffmpeg rotates before the scale filter
    coded = make_clip(tmp_path)
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", coded, "-map", "0", "-c", "copy", rotated], check=True)
    coded.unlink()
    transcode.to_h264(rotated, max_side=240, max_seconds=300, timeout=60)
    assert min(video_size(rotated, displayed=True)) == 240


def test_odd_size_converts(tmp_path):
    # libx264 with yuv420p needs even sizes
    clip = make_clip(tmp_path, size="641x361")
    assert transcode.to_h264(clip, max_side=1440, max_seconds=300, timeout=60) is True
    width, height = video_size(clip)
    assert width % 2 == 0 and height % 2 == 0 and abs(width - 641) <= 1 and abs(height - 361) <= 1


def test_subtitle_track_left_out(tmp_path):
    # an mp4 cannot hold an SRT track; a Google Drive source/ .mkv can have one
    clip = make_clip(tmp_path)
    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:00,900\nhello\n")
    mkv = tmp_path / "clip.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-i", srt, "-map", "0", "-map", "1", "-c", "copy", mkv], check=True)
    clip.unlink()
    assert transcode.to_h264(mkv, max_side=1440, max_seconds=300, timeout=60) is True
    found = streams(tmp_path / "clip.mp4")
    # Matroska keeps the cover as an attachment, which is left out with the subtitle; Telegram then
    # makes its own thumbnail
    assert sorted(s["codec_type"] for s in found) == ["audio", "video"]
    assert [s["codec_name"] for s in found if s["codec_type"] == "video"] == ["h264"]
    assert not (tmp_path / "clip.mkv").exists()


def test_on_start_only_when_converting(tmp_path):
    calls = []
    vp9 = make_clip(tmp_path)
    transcode.to_h264(vp9, max_side=1440, max_seconds=300, timeout=60, on_start=lambda: calls.append("vp9"))
    h264_dir = tmp_path / "h264"
    h264_dir.mkdir()
    h264 = make_clip(h264_dir, codec="libx264")
    transcode.to_h264(h264, max_side=1440, max_seconds=300, timeout=60, on_start=lambda: calls.append("h264"))
    assert calls == ["vp9"]


def test_ffmpeg_error_leaves_the_source(tmp_path, monkeypatch):
    clip = make_clip(tmp_path)
    before = clip.read_bytes()
    real_run = subprocess.run

    def failing_run(args, **kwargs):
        if args[0] == "ffmpeg":
            raise subprocess.CalledProcessError(1, args, stderr="[libx264] something unexpected\n")
        return real_run(args, **kwargs)

    monkeypatch.setattr(transcode.subprocess, "run", failing_run)
    with pytest.raises(transcode.ConversionFailed, match="something unexpected"):
        transcode.to_h264(clip, max_side=1440, max_seconds=300, timeout=60)
    assert clip.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4", "cover.jpg"]
