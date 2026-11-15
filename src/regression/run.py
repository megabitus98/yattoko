#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - regression/run.py
# Modified 2026 by megabitus98 (fork): new file, real downloads through the bot's own download path, checked with ffprobe against what the site offered, one JSON line per link, optional upload through a test bot

"""Real-download regression run: python /app/regression/run.py [--links FILE] [--upload]

One JSON line per link on stdout, logs on stderr. Exit 0: every link passed. 2: the downloader is
broken (any link). 3: nothing broken, but a link is gone and needs replacing. 1: the run itself failed.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Before any app module is imported. The image runs this file as a script, with the app one directory
# up. The root filesystem is read-only and there is no /data volume, so the database goes under /tmp.
# ENABLE_FFMPEG as in the owner's deployment. The redacting log formatter masks BOT_TOKEN, and this
# process has no other bot.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_data_dir = os.environ.setdefault("DATA_DIR", "/tmp/regression")
os.environ.setdefault("DB_DSN", f"sqlite:///{_data_dir}/ytdlbot.db")
os.makedirs(_data_dir, exist_ok=True)
os.environ.setdefault("ENABLE_FFMPEG", "true")
if os.environ.get("TEST_BOT_TOKEN"):
    os.environ["BOT_TOKEN"] = os.environ["TEST_BOT_TOKEN"]

from pyrogram import Client, enums  # noqa: E402

from config import APP_HASH, APP_ID  # noqa: E402
from engine import transcode  # noqa: E402
from engine.errors import classify  # noqa: E402
from engine.generic import YoutubeDownload  # noqa: E402
from utils import netcheck  # noqa: E402

CAP = 1440  # the default quality setting (2K); chat 0 has no saved settings

NOTHING_FOUND = dict.fromkeys(("vcodec", "vtag", "acodec", "width", "height", "duration", "size"))


class _NoTelegram:
    # the client while downloading: every call does nothing (owner notices, chat actions)
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _progress_message() -> SimpleNamespace:
    # The bot's progress edits go nowhere. Chat 0 has no saved settings, so the defaults apply
    # (1440p, codec auto, sent as video).
    return SimpleNamespace(id=0, chat=SimpleNamespace(id=0, type=enums.ChatType.PRIVATE), edit_text=lambda *a, **k: None)


def probe(path: Path) -> dict:
    info = transcode._probe(path)
    streams = info.get("streams", [])
    # the embedded cover is a video stream too: an mp3 with a cover is not a video
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), {}
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "vcodec": video.get("codec_name"),
        "vtag": video.get("codec_tag_string"),
        "acodec": audio.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": float(info.get("format", {}).get("duration") or 0),
        "size": path.stat().st_size,
    }


def offered(formats: list[dict], quality_first: bool) -> dict | None:
    # What the site offered for this download: the biggest smaller side up to CAP among video formats,
    # and whether any format lists sound. Formats with no size or codec listed (Instagram's single
    # files) count for neither. H.264 first (long videos, or ENABLE_FFMPEG off) counts only codecs
    # that play as they are. None when the site listed no formats.
    if not formats:
        return None
    sides = [
        min(f["width"], f["height"], CAP)
        for f in formats
        if f.get("width") and f.get("height") and f.get("vcodec") not in (None, "none")
        and (quality_first or str(f["vcodec"]).startswith(("avc", "h264", "hev", "hvc", "h265")))
    ]
    return {"short_side": max(sides, default=0), "audio": any(f.get("acodec") not in (None, "none") for f in formats)}


def evaluate(found: dict, expect: dict, offer: dict | None) -> tuple[str, str]:
    # The bot is judged by what the site offered for this very download, so a link that changes does
    # not read as a broken bot. A file Telegram would not play everywhere, without the sound or below
    # the picture size the site offered is a broken downloader. A link that no longer has what it is
    # listed for (expect: audio, min_short_side) is gone: replace it. H.265 needs the hvc1 tag.
    short_side = min(found["width"] or 0, found["height"] or 0)
    if found["vcodec"] not in expect["vcodec"] or not transcode.playable(found["vcodec"], found["vtag"]):
        return "downloader_broken", f"video {found['vcodec']}/{found['vtag']} does not play everywhere"
    if found["duration"] < expect.get("duration_min", 0):
        return "downloader_broken", f"only {found['duration']:.1f} s long"
    if offer and offer["audio"] and found["acodec"] is None:
        return "downloader_broken", "the site offered sound, the file has none"
    if offer and short_side < offer["short_side"]:
        return "downloader_broken", f"smaller side {short_side}, the site offered {offer['short_side']}"
    if offer and expect.get("audio") and not offer["audio"]:
        return "link_gone", "the site offers no sound for this link any more"
    if offer and offer["short_side"] < expect.get("min_short_side", 0):
        return "link_gone", f"the site offers only {offer['short_side']} on the smaller side"
    return "passed", ""


def run_link(link: dict) -> tuple[dict, YoutubeDownload | None]:
    # The bot's download path without Telegram: host check, exits, format ladder, per-site rules, size
    # guard and the H.264 conversion. The caller removes downloader._tempdir (start() would, after uploading).
    downloader = None
    seen = {}
    try:
        downloader = YoutubeDownload(_NoTelegram(), _progress_message(), link["url"])
        # attempt() hands every extracted result to choose(); record the format list the site gave
        choose = downloader._choose

        def recording_choose(info):
            seen["formats"] = info.get("formats") or []
            return choose(info)

        downloader._choose = recording_choose
        files = downloader._download_fitting()
        if len(files) != 1:
            # the bot would send an album
            raise RuntimeError(f"{len(files)} files instead of one")
        found = probe(files[0])
    except Exception as e:
        logging.exception("%s failed", link["name"])
        status = "link_gone" if classify(e) == "unavailable" else "downloader_broken"
        return {"name": link["name"], "status": status, "reason": classify(e), **NOTHING_FOUND}, downloader
    # the mode of the file that was kept: a too-long conversion downloads again H.264 first
    offer = offered(seen.get("formats", []), quality_first=downloader._quality_first)
    status, reason = evaluate(found, link, offer)
    return {"name": link["name"], "status": status, "reason": reason, **found, "offered": offer}, downloader


def upload(downloader: YoutubeDownload, token: str, chat_id: int) -> str:
    # The bot's own upload (thumbnail, caption, send methods in order) through the test bot, with no
    # session file. A video that only got through as an animation or audio still counts as broken.
    try:
        with Client("regression", api_id=APP_ID, api_hash=APP_HASH, bot_token=token, in_memory=True) as app:
            downloader._client, downloader._chat_id = app, chat_id
            sent = downloader._upload()
        return "passed" if getattr(sent, "video", None) else "downloader_broken"
    except Exception:
        logging.exception("Upload through the test bot failed")
        return "downloader_broken"


def exit_code(statuses: list[str]) -> int:
    if "downloader_broken" in statuses:
        return 2
    return 3 if "link_gone" in statuses else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real-download regression run")
    parser.add_argument("--links", type=Path, default=Path(__file__).with_name("links.json"))
    parser.add_argument("--upload", action="store_true", help="send the smallest result to TEST_CHAT_ID through TEST_BOT_TOKEN")
    args = parser.parse_args(argv)
    token, chat_id = os.environ.get("TEST_BOT_TOKEN"), os.environ.get("TEST_CHAT_ID", "")
    if args.upload and not (token and chat_id.removeprefix("-").isdigit() and APP_ID and APP_HASH):
        # before anything is downloaded; exit 1, since 2 and 3 say something about the links
        sys.exit("--upload needs TEST_BOT_TOKEN, a numeric TEST_CHAT_ID, APP_ID and APP_HASH")

    try:
        # broken DNS or no network would otherwise read as "every link is gone" (exit 3)
        netcheck.check_url("https://www.youtube.com/", frozenset())
    except Exception as e:
        sys.exit(f"No network or DNS, nothing was tested: {e}")

    statuses, smallest = [], None
    for link in json.loads(args.links.read_text(encoding="utf-8")):
        result, downloader = run_link(link)
        print(json.dumps(result), flush=True)
        statuses.append(result["status"])
        if args.upload and result["status"] == "passed" and (smallest is None or result["size"] < smallest[0]):
            if smallest:
                smallest[1]._tempdir.cleanup()
            smallest = (result["size"], downloader)
        elif downloader:
            downloader._tempdir.cleanup()
    if smallest:
        status = upload(smallest[1], token, int(chat_id))
        smallest[1]._tempdir.cleanup()
        print(json.dumps({"name": "upload", "status": status}), flush=True)
        statuses.append(status)
    return exit_code(statuses)


if __name__ == "__main__":
    sys.exit(main())
