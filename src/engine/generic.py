#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - generic.py
# Modified 2026 by megabitus98 (fork): no verbose mode or options log, yt-dlp output through the redacting root logger, build_format_options (H.264 first, PREFERRED_AUDIO_LANG instead of Russian audio), English texts

import logging
import os
from pathlib import Path

import yt_dlp

from config import (
    AUDIO_FORMAT,
    PREFERRED_AUDIO_LANG,
    YT_DLP_PROXY,
)

from utils import is_youtube
from database.model import get_format_settings, get_sponsorblock_settings
from engine.base import BaseDownloader

# codec setting -> (filter on the first format rungs, codec the sort prefers)
CODECS = {
    "auto": ("", "h264"),
    "avc1": ("[vcodec^=avc1]", "h264"),
    "vp9": ("[vcodec^=vp]", "vp9"),
    "av01": ("[vcodec^=av01]", "av01"),
}


def build_format_options(quality: str, vcodec: str, send_as: str, audio_lang: str) -> dict:
    # vcodec is the stored setting ("vcodec-auto") or the bare name ("auto").
    # H.264 first because Telegram plays it inline everywhere; the codec sorts before the resolution,
    # so with "auto" YouTube above 1080p (no H.264 there) arrives in 1080p. Nothing is re-encoded.
    codec_filter, preferred = CODECS.get(vcodec.removeprefix("vcodec-"), CODECS["auto"])
    lang = f"[language={audio_lang}]" if audio_lang else ""

    def audio(extra: str = "") -> str:
        # without a preferred language yt-dlp ranks the original track first
        return f"(bestaudio{lang}{extra}/bestaudio{extra})" if lang else f"bestaudio{extra}"

    if send_as == "audio":
        formats = [audio(f"[ext={AUDIO_FORMAT}]"), audio("[ext=m4a]"), audio(), "best"]
    else:
        height = f"[height<={quality[:-1]}]"
        formats = [
            # most videos up to about two hours
            f"bestvideo{height}{codec_filter}[filesize<1.5G]+{audio('[filesize<0.5G]')}",
            f"bestvideo{height}[filesize<1.5G]+{audio('[filesize<0.5G]')}",
            # very long videos
            f"bestvideo{height}{codec_filter}[filesize<1G]+{audio('[filesize<1G]')}",
            f"bestvideo{height}[filesize<1G]+{audio('[filesize<1G]')}",
            # sizes not known in advance
            f"(bestvideo{height}/bestvideo)+{audio()}",
            # only video or only audio
            f"(bestvideo{height}/bestvideo)/{audio()}",
            "best",
        ]
    return {
        # with "auto" the first rungs repeat; dict.fromkeys drops the copies and keeps the order
        "format": "/".join(dict.fromkeys(formats)),
        "format_sort": [f"vcodec:{preferred}", "res", "acodec:m4a"],
        "merge_output_format": "mp4",
    }


def match_filter(info_dict):
    if info_dict.get("is_live"):
        raise NotImplementedError("Skipping live video")
    return None  # Allow download for non-live videos


class YoutubeDownload(BaseDownloader):
    def _setup_formats(self) -> dict:
        return build_format_options(self._quality, self._vcodec, self._format, PREFERRED_AUDIO_LANG)

    def _download(self, formats) -> list:
        output = Path(self._tempdir.name, "%(title).70s.%(ext)s").as_posix()
        ydl_opts = {
            # without a logger yt-dlp writes errors straight to stderr, past the redacting formatter
            "logger": logging.getLogger("yt_dlp"),
            "progress_hooks": [lambda d: self.download_hook(d)],
            "outtmpl": output,
            "restrictfilenames": False,
            "quiet": True,
            "match_filter": match_filter,
            "writethumbnail": True,
            **formats,  # format, format_sort, merge_output_format
            "source_address": "0.0.0.0",
            "concurrent_fragments": 16,
            "buffersize": 4194304,
            "retries": 6,
            "fragment_retries": 6,
            "skip_unavailable_fragments": True,
            "proxy": YT_DLP_PROXY,
            "playlist_items": 1,  # workaround so a channel link does not download the whole channel
        }

        if get_format_settings(self._chat_id) == "audio":
            ydl_opts["postprocessors"] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '0'
            },
            {
                'key': 'FFmpegMetadata',
                'add_metadata': True
            },
            {
                'key': 'EmbedThumbnail',
                'already_have_thumbnail': False
            }]
        else:
            ydl_opts["postprocessors"] = [{
                'key': 'FFmpegMetadata',
                'add_metadata': True
            },
            {
                'key': 'EmbedThumbnail'
            }]

        if get_sponsorblock_settings(self._chat_id) == "remove":
            sponsorblock_pps = [
                {
                    'key': 'SponsorBlock',
                    'categories': {'sponsor', 'selfpromo'},
                    'when': 'after_filter',
                },
                {
                    'key': 'ModifyChapters',
                    'remove_sponsor_segments': {'sponsor', 'selfpromo'},
                },
            ]
            ydl_opts["postprocessors"] = sponsorblock_pps + ydl_opts["postprocessors"]

        # setup cookies for youtube only
        if is_youtube(self._url):
            # use cookies from browser firstly
            if browsers := os.getenv("BROWSERS"):
                ydl_opts["cookiesfrombrowser"] = browsers.split(",")
            if os.path.isfile("youtube-cookies.txt") and os.path.getsize("youtube-cookies.txt") > 100:
                ydl_opts["cookiefile"] = "youtube-cookies.txt"
            # add PO Token if present: https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
            if potoken := os.getenv("POTOKEN"):
                ydl_opts["extractor_args"] = {
                    "youtube": {
                        "player_client": ["web", "default"],
                        "po_token": [f"web+{potoken}"],
                    }
                }

        files = None
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([self._url])
        files = list(Path(self._tempdir.name).glob("*"))
        return files

    def _start(self):
        # start download and upload, no cache hit
        self._download(self._setup_formats())
        self._upload()
