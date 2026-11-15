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


class ConversionFailed(Exception):
    """ffmpeg stopped with an error; the message is its last line of output. The source is untouched."""


def playable(codec: str | None, tag: str | None) -> bool:
    # Telegram plays H.264 everywhere. VP9 and AV1 show one frame in Telegram for macOS. H.265 plays
    # on iPhones and Macs only with the hvc1 tag (TikTok's files have it).
    return codec == "h264" or (codec == "hevc" and tag == "hvc1")


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name,codec_tag_string,width,height:stream_disposition=attached_pic:"
         "stream_side_data=rotation:stream_tags=rotate:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    return json.loads(out)


def _rotation(stream: dict) -> int:
    # degrees the player turns the picture: display-matrix side data, or the old rotate tag
    for data in stream.get("side_data_list") or []:
        if "rotation" in data:
            return abs(int(float(data["rotation"])))
    return abs(int(float((stream.get("tags") or {}).get("rotate") or 0)))


def to_h264(path: Path, max_side: int, max_seconds: float, timeout: float, on_start=None) -> bool:
    """Convert the main video stream of path to H.264 in place when Telegram could not play it everywhere.

    False when nothing was needed: no video, already playable, or max_seconds is 0. TooLong when it
    would need converting but is longer than max_seconds.
    Sound and the embedded cover (the upload's thumbnail) are copied; sound that is neither AAC nor
    MP3 becomes AAC. Subtitle, data and attachment streams are left out (an mp4 cannot hold most of
    them). The smaller side as shown (after rotation) is cut to max_side, as the format sort does, and
    both sides are made even (libx264 with yuv420p needs that). on_start() runs just before ffmpeg does.
    On a timeout (subprocess.TimeoutExpired) or an ffmpeg error (ConversionFailed) the source stays.
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
    if _rotation(video) % 180 == 90:
        # ffmpeg turns the picture upright before the scale filter runs
        width, height = height, width
    covers = [s["index"] for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic")]
    sounds = [s for s in streams if s.get("codec_type") == "audio"]
    # Main video first, then sound, then the covers, each mapped by its input index ("V" for "video that
    # is not a cover" also matched the cover on output in ffmpeg 8.0). Only output stream 0 is encoded.
    maps = ["-map", f"0:{video['index']}", "-map", "0:a?"]
    for index in covers:
        maps += ["-map", f"0:{index}"]
    if min(width, height) > max_side:
        scale = f"-2:{max_side}" if width >= height else f"{max_side}:-2"
    else:
        scale = "trunc(iw/2)*2:trunc(ih/2)*2"
    # ponytail: 2 encoder threads, a CPU knob if the cluster has room to spare
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), *maps, "-c", "copy",
            "-c:0", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt:0", "yuv420p",
            "-filter:0", f"scale={scale}", "-threads", "2"]
    if any(s.get("codec_name") not in ("aac", "mp3") for s in sounds):
        args += ["-c:a", "aac", "-b:a", "160k"]
    out = path.with_name(f"{path.stem}.h264.mp4")
    args += ["-movflags", "+faststart", str(out)]
    if on_start:
        on_start()
    started = time.monotonic()
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as e:
        out.unlink(missing_ok=True)
        lines = (e.stderr or "").strip().splitlines()
        raise ConversionFailed(lines[-1] if lines else f"ffmpeg exit {e.returncode}") from None
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
