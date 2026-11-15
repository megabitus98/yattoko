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
