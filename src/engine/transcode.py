#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - transcode.py
# Modified 2026 by megabitus98 (fork): new file, converts VP9/AV1 downloads to H.264 so Telegram plays them on every device

import json
import logging
import subprocess
import time
from pathlib import Path


class TooLong(Exception):
    """The video needs converting but is longer than max_seconds (or its length is unknown)."""


def playable(codec: str | None, tag: str | None) -> bool:
    # Telegram plays H.264 everywhere. VP9 and AV1 show one frame in Telegram for macOS. H.265 plays
    # on iPhones and Macs only with the hvc1 tag (TikTok's files have it).
    return codec == "h264" or (codec == "hevc" and tag == "hvc1")


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name,codec_tag_string,width,height:stream_disposition=attached_pic:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    return json.loads(out)


def to_h264(path: Path, max_side: int, max_seconds: float, timeout: float, on_start=None) -> bool:
    """Convert the main video stream of path to H.264 in place when Telegram could not play it everywhere.

    False when nothing was needed: no video, already playable, or max_seconds is 0. TooLong when it
    would need converting but is longer than max_seconds.
    Audio and the embedded cover (the upload's thumbnail) are copied; audio that is neither AAC nor
    MP3 becomes AAC. The smaller side is cut to max_side, as the format sort does. on_start() runs just
    before ffmpeg does. On a timeout or an ffmpeg error the source stays and the exception goes up.
    """
    info = _probe(path)
    streams = info.get("streams", [])
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    duration = float(info.get("format", {}).get("duration") or 0)
    if video is None or playable(video.get("codec_name"), video.get("codec_tag_string")):
        return False
    if not max_seconds:
        return False
    if not duration or duration > max_seconds:
        raise TooLong()
    width, height = video.get("width") or 0, video.get("height") or 0
    # -map 0 -c copy keeps sound and cover in whatever order yt-dlp wrote them; only the main video stream
    # is encoded, named by its index (the "V" specifier also matched the cover on output, ffmpeg 8.0)
    # ponytail: 2 encoder threads, a CPU knob if the cluster has room to spare
    n = video["index"]
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-map", "0", "-c", "copy",
            f"-c:{n}", "libx264", "-preset", "veryfast", "-crf", "20", f"-pix_fmt:{n}", "yuv420p", "-threads", "2"]
    if min(width, height) > max_side:
        scale = f"-2:{max_side}" if width >= height else f"{max_side}:-2"
        args += [f"-filter:{n}", f"scale={scale}"]
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio and audio.get("codec_name") not in ("aac", "mp3"):
        args += ["-c:a", "aac", "-b:a", "160k"]
    out = path.with_name(f"{path.stem}.h264.mp4")
    args += ["-movflags", "+faststart", str(out)]
    if on_start:
        on_start()
    started = time.monotonic()
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    path.unlink()
    out.replace(path.with_suffix(".mp4"))
    logging.info(
        "Converted %s %dx%d (%.0f s) to H.264 in %.0f s",
        video.get("codec_name"), width, height, duration, time.monotonic() - started,
    )
    return True
