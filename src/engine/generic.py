#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - generic.py
# Modified 2026 by megabitus98 (fork): no verbose mode or options log, yt-dlp output through the redacting root logger, build_format_options (H.264 first, PREFERRED_AUDIO_LANG instead of Russian audio), English texts, per-site cookies from COOKIES_DIR as in-memory copies (no BROWSERS), attempt(): extract, refuse playlists and live streams, then download in the same YoutubeDL (no playlist_items), Google Drive source format, audio language matches region tags, settings by user ID, host check before every attempt, socket timeout, oversized files retried a quality lower, owner notice when the Instagram cookies stopped working, exits tried recorded, PROXY_EXITS tried in order on blocked errors (pinned sites never fall back)

import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import sanitize_url

from config import (
    AUDIO_FORMAT,
    BotText,
    COOKIES_DIR,
    OWN_PUBLIC_IPS,
    PREFERRED_AUDIO_LANG,
    PROXY_EXITS,
    PROXY_PIN,
)

from engine.base import BaseDownloader
from engine.cookies import cookie_options, instagram_session_present
from engine.errors import RefusedContent, classify, tell_owners
from engine.proxy import exit_label, exits_for, ydl_proxy
from engine.sites import site_for_url
from utils import netcheck

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
    # ^= so "en" also matches region-tagged tracks such as "en-US"
    lang = f"[language^={audio_lang}]" if audio_lang else ""

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


def _is_live(info: dict) -> bool:
    # a raw extractor result may carry only live_status; yt-dlp fills in is_live while processing
    return bool(info.get("is_live")) or info.get("live_status") == "is_live"


def single_video_only(info: dict, incomplete: bool = False) -> None:
    # Backstop for what the check in attempt() cannot see (a url_transparent hop): yt-dlp calls the
    # match_filter for every video before its download, playlist entries carry playlist_index.
    if info.get("playlist_index") is not None or _is_live(info):
        raise RefusedContent()
    return None


def attempt(
    url: str,
    site: str,
    exit: str,
    opts: dict,
    tmpdir: Path,
    on_cookies_expired: Callable[[], None] | None = None,
) -> dict:
    # One YoutubeDL per attempt: extraction and download through the same exit (YouTube media URLs
    # are tied to the extracting IP), and a fresh in-memory cookies copy for this instance only.
    params = opts | {
        "proxy": ydl_proxy(exit),
        "noplaylist": True,  # watch?v=x&list=y means the video, not the playlist
        "match_filter": single_video_only,
        "outtmpl": (tmpdir / "%(title).70s.%(ext)s").as_posix(),
    }
    cookies = cookie_options(Path(COOKIES_DIR), site)
    with yt_dlp.YoutubeDL(params | cookies) as ydl:
        # yt-dlp's Instagram extractor drops sessionid from the jar when the cookies no longer work
        session = bool(cookies) and site == "instagram" and instagram_session_present(ydl)
        try:
            # process=False: the raw result, so a channel's entries are never walked
            info = ydl.extract_info(url, download=False, process=False)
            # short links and redirects come back as a pointer; follow it (still nothing downloaded)
            for _ in range(5):
                if not info or info.get("_type") != "url":
                    break
                info = ydl.extract_info(
                    sanitize_url(info["url"], scheme="https"), download=False, ie_key=info.get("ie_key"), process=False
                )
            if not info:
                raise yt_dlp.utils.DownloadError("Nothing extracted")
            if info.get("_type") in ("playlist", "multi_video") or _is_live(info):
                raise RefusedContent()
            return ydl.process_ie_result(info, download=True)
        finally:
            # failed or not, and before close() writes the jar to the scratch copy
            if session and on_cookies_expired and not instagram_session_present(ydl):
                on_cookies_expired()


class YoutubeDownload(BaseDownloader):
    def _setup_formats(self) -> dict:
        options = build_format_options(self._quality, self._vcodec, self._format, PREFERRED_AUDIO_LANG)
        if urlparse(self._url).hostname == "drive.google.com":
            # Google Drive offers the uploaded file itself as format "source"
            options["format"] = f"source/{options['format']}"
        return options

    def _download(self, formats) -> list:
        ydl_opts = {
            # without a logger yt-dlp writes errors straight to stderr, past the redacting formatter
            "logger": logging.getLogger("yt_dlp"),
            "progress_hooks": [lambda d: self.download_hook(d)],
            "restrictfilenames": False,
            "quiet": True,
            "writethumbnail": True,
            **formats,  # format, format_sort, merge_output_format
            "source_address": "0.0.0.0",
            "concurrent_fragments": 16,
            "buffersize": 4194304,
            "retries": 6,
            "fragment_retries": 6,
            # a stalled connection fails instead of waiting for JOB_TIMEOUT (yt-dlp's default is 20 s;
            # home lines can be slow)
            "socket_timeout": 60,
            "skip_unavailable_fragments": True,
        }

        if self._format == "audio":
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

        if self._sponsorblock == "remove":
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

        site = site_for_url(self._url)
        # add PO Token if present: https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
        if site == "youtube" and (potoken := os.getenv("POTOKEN")):
            ydl_opts["extractor_args"] = {
                "youtube": {
                    "player_client": ["web", "default"],
                    "po_token": [f"web+{potoken}"],
                }
            }

        tmpdir = Path(self._tempdir.name)
        exits = exits_for(site, PROXY_EXITS, PROXY_PIN)
        for number, exit in enumerate(exits, 1):
            if number > 1:
                # empty: a blocked attempt's partial files must not be resumed or sent
                shutil.rmtree(tmpdir)
                tmpdir.mkdir()
            # before every attempt, proxied ones too: a proxy on the home network would fetch LAN
            # addresses for us, and the name may resolve differently than when the job was queued
            netcheck.check_url(self._url, OWN_PUBLIC_IPS)
            # labels only: proxy URLs are secrets
            label = exit_label(exit, PROXY_EXITS)
            self._exits_tried.append(label)
            try:
                attempt(
                    self._url,
                    site,
                    exit,
                    ydl_opts,
                    tmpdir,
                    on_cookies_expired=lambda: tell_owners(
                        self._client,
                        self._url,
                        "cookies_expired",
                        BotText.owner_cookies_expired.format(site=site),
                        self._exits_tried,
                    ),
                )
                return list(tmpdir.glob("*"))
            except Exception as e:
                # only a block is worth another exit; the last one's error goes to BaseDownloader.start()
                if number == len(exits) or classify(e) != "blocked":
                    raise
                logging.warning("%s blocked through %s, trying the next exit", self._url, label)

    def _start(self):
        # start download and upload, no cache hit
        self._download_fitting()
        self._upload()
