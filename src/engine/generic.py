#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - generic.py
# Modified 2026 by megabitus98 (fork): no verbose mode or options log, yt-dlp output through the redacting root logger, build_format_options (H.264 first, PREFERRED_AUDIO_LANG instead of Russian audio), English texts, per-site cookies from COOKIES_DIR as in-memory copies (no BROWSERS), attempt(): extract, refuse playlists and live streams, then download in the same YoutubeDL (no playlist_items), Google Drive source format, audio language matches region tags, settings by user ID, host check before every attempt, socket timeout, oversized files retried a quality lower, owner notice when the Instagram cookies stopped working, exits tried recorded, PROXY_EXITS tried in order on blocked errors (pinned sites never fall back), single files before audio-only, quality limit on the smaller side (res sort), Instagram single file first, TikTok H.265 first, ENABLE_FFMPEG: short videos take the best picture up to the quality setting and VP9/AV1 is converted to H.264 (transcode.py)

import logging
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from yt_dlp.utils import sanitize_url

from config import (
    AUDIO_FORMAT,
    BotText,
    COOKIES_DIR,
    ENABLE_FFMPEG,
    OWN_PUBLIC_IPS,
    PREFERRED_AUDIO_LANG,
    PROXY_EXITS,
    PROXY_PIN,
    REENCODE_MAX_SECONDS,
)

from engine import transcode
from engine.base import BaseDownloader
from engine.cookies import cookie_options, instagram_session_present
from engine.errors import RefusedContent, classify, tell_owners
from engine.jobs import JobTimeout
from engine.proxy import exit_label, exits_for, ydl_proxy
from engine.sites import site_for_url
from utils import netcheck

# yt-dlp's FormatSorter keeps the sort limits (res:N, hdr:sdr, vcodec:...) in a class-level dict, so two
# jobs sorting at the same time would sort with each other's limits. yt-dlp makes sorters in one place,
# YoutubeDL.sort_formats; one lock around it serialises the sorting only (milliseconds), not the download.
SORT_LOCK = threading.Lock()
_unlocked_sort_formats = yt_dlp.YoutubeDL.sort_formats


def _sort_formats(self, info_dict):
    with SORT_LOCK:
        return _unlocked_sort_formats(self, info_dict)


yt_dlp.YoutubeDL.sort_formats = _sort_formats

# Instagram's single H.264 files (sizes not listed) have been 720p in every reel seen without a login;
# a VP9 stream no bigger than this is not worth converting
INSTAGRAM_SINGLE_FILE_SIDE = 720

# codec setting -> (filter on the first format rungs, codec the sort prefers)
CODECS = {
    "auto": ("", "h264"),
    "avc1": ("[vcodec^=avc1]", "h264"),
    "vp9": ("[vcodec^=vp]", "vp9"),
    "av01": ("[vcodec^=av01]", "av01"),
}


def build_format_options(quality: str, vcodec: str, send_as: str, audio_lang: str, quality_first: bool = False) -> dict:
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
        formats = [
            # most videos up to about two hours
            f"bestvideo{codec_filter}[filesize<1.5G]+{audio('[filesize<0.5G]')}",
            f"bestvideo[filesize<1.5G]+{audio('[filesize<0.5G]')}",
            # very long videos
            f"bestvideo{codec_filter}[filesize<1G]+{audio('[filesize<1G]')}",
            f"bestvideo[filesize<1G]+{audio('[filesize<1G]')}",
            # sizes not known in advance
            f"bestvideo+{audio()}",
            # one file with video and sound (TikTok and many smaller sites have nothing else)
            "best",
            # only video, then only audio
            "bestvideo",
            audio(),
        ]
    return {
        # with "auto" the first rungs repeat; dict.fromkeys drops the copies and keeps the order
        "format": "/".join(dict.fromkeys(formats)),
        # The quality limit lives in the sort, not in a filter: yt-dlp's res is the smaller side, so
        # a vertical 1080x1920 video counts as 1080p, and a format with no size listed is not dropped.
        # quality_first (short videos, ENABLE_FFMPEG): the best picture in any codec, SDR first because HDR
        # forced into 8-bit H.264 looks washed out; transcode.py converts VP9/AV1 afterwards.
        "format_sort": (
            ["hdr:sdr", f"res:{quality.removesuffix('p')}", f"vcodec:{preferred}", "acodec:m4a"]
            if quality_first
            else [f"vcodec:{preferred}", f"res:{quality.removesuffix('p')}", "acodec:m4a"]
        ),
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
    choose: Callable[[dict], dict | None] | None = None,
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
            # choose(info) may pick other format options once the duration is known. yt-dlp reads
            # format_sort when it sorts, but builds the format selector when the instance is created.
            if choose and (picked := choose(info)):
                ydl.params.update(picked)
                ydl.format_selector = ydl.build_format_selector(picked["format"])
            return ydl.process_ie_result(info, download=True)
        finally:
            # failed or not, and before close() writes the jar to the scratch copy
            if session and on_cookies_expired and not instagram_session_present(ydl):
                on_cookies_expired()


class YoutubeDownload(BaseDownloader):
    def _setup_formats(self, quality_first: bool = False) -> dict:
        options = build_format_options(self._quality, self._vcodec, self._format, PREFERRED_AUDIO_LANG, quality_first)
        site = site_for_url(self._url)
        # a codec chosen in /settings beats the per-site choices below
        auto_video = self._format != "audio" and self._vcodec.removeprefix("vcodec-") == "auto"
        if urlparse(self._url).hostname == "drive.google.com":
            # Google Drive offers the uploaded file itself as format "source"
            options["format"] = f"source/{options['format']}"
        elif quality_first:
            pass  # the best picture wins; transcode.py makes it H.264
        elif auto_video and site == "instagram":
            # Instagram's single files are H.264 with sound, but yt-dlp lists their codecs as
            # unknown, so the codec sort would pick the separate VP9 streams (one frame on a Mac).
            # Without a login the H.264 file stops at 720p; 1080p exists only as VP9 (/settings vp9).
            options["format"] = f"best/{options['format']}"
        elif auto_video and site == "tiktok":
            # TikTok's H.264 files stop at 540p with 32 kb/s sound; its H.265 (hvc1) files reach 1080p
            # with 64 kb/s. The TikTok app plays H.265, and so did Telegram on an iPhone and a Mac.
            # Telegram on Windows and old Android phones may not; /settings avc1 keeps H.264.
            options["format_sort"] = ["vcodec:h265", *options["format_sort"][1:]]
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
                self._attempt(site, exit, ydl_opts, tmpdir, choose=self._choose)
            except Exception as e:
                # only a block is worth another exit; the last one's error goes to BaseDownloader.start()
                if number == len(exits) or classify(e) != "blocked":
                    raise
                logging.warning("%s blocked through %s, trying the next exit", self._url, label)
                continue
            # outside the try: a conversion problem is not a block and is not retried on another exit
            self._convert_all(site, exit, ydl_opts, tmpdir)
            return list(tmpdir.glob("*"))

    def _attempt(self, site: str, exit: str, ydl_opts: dict, tmpdir: Path, choose=None):
        self._quality_first = False  # _choose() sets it when it picks the quality-first options
        self._video_formats_offered = 0  # and this, from the extracted format list
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
            choose=choose,
        )

    def _convert_all(self, site: str, exit: str, ydl_opts: dict, tmpdir: Path):
        if not self._converts():
            return
        try:
            for path in list(tmpdir.glob("*")):
                self._convert(path)
        except transcode.TooLong:
            if not self._quality_first or self._video_formats_offered <= 1:
                # nothing else to pick (one format, as for a direct link): the same file again would not help
                logging.info("%s has no H.264 and is too long to convert, sent as it is", self._url)
                return
            # the site gave no length and the file is too long to convert: download again through the
            # same exit, H.264 first (ydl_opts was built from the H.264-first options)
            logging.info("%s is too long to convert, downloading again H.264 first", self._url)
            shutil.rmtree(tmpdir)
            tmpdir.mkdir()
            netcheck.check_url(self._url, OWN_PUBLIC_IPS)
            self._attempt(site, exit, ydl_opts, tmpdir)

    def _converts(self) -> bool:
        # a codec chosen in /settings is kept as it is, and audio is never converted here
        return ENABLE_FFMPEG and self._format != "audio" and self._vcodec.removeprefix("vcodec-") == "auto"

    def _choose(self, info: dict) -> dict | None:
        # A short video gets the best picture up to the quality setting in any codec; a longer one keeps
        # H.264 first, so nothing long is converted. Without a length (Instagram gives none) the best
        # picture is taken and the file's real length decides: too long means one more download, H.264 first.
        formats = info.get("formats") or []
        video = [f for f in formats if f.get("vcodec") != "none"]
        self._video_formats_offered = len(video)
        duration = info.get("duration")
        if not self._converts() or not REENCODE_MAX_SECONDS or (duration and duration > REENCODE_MAX_SECONDS):
            return None
        if site_for_url(self._url) == "instagram":
            sides = [min(f["width"], f["height"]) for f in video if f.get("width") and f.get("height")]
            if sides and max(sides) <= INSTAGRAM_SINGLE_FILE_SIDE:
                return None  # H.264 first: the single file is as big and needs no conversion
        self._quality_first = True
        return self._setup_formats(quality_first=True)

    def _convert(self, path: Path):
        if path.suffix.lower() not in (".mp4", ".mkv", ".webm", ".mov"):
            return
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise JobTimeout()
        timed_out = False
        try:
            # the size check in _download_fitting() sees the converted file
            transcode.to_h264(
                path, int(self._quality.removesuffix("p")), REENCODE_MAX_SECONDS, remaining, self._say_converting
            )
        except transcode.ConversionFailed as e:
            # the source is intact: sending it as it is beats sending nothing
            logging.warning("Converting %s failed, sent as it is: %s", path.name, e)
        except subprocess.TimeoutExpired:
            timed_out = True
        if timed_out:
            # raised outside the except block: the ffmpeg command line (it holds the title) must not
            # reach classify() through __context__
            raise JobTimeout()

    def _say_converting(self):
        # A conversion can take a minute; without this the progress message looks stuck at 100 %.
        # Straight to the message: edit_text() drops edits within 5 s of the last progress update.
        try:
            self._bot_msg.edit_text(BotText.converting)
        except Exception:
            logging.warning("Could not show the converting message", exc_info=True)

    def _start(self):
        # start download and upload, no cache hit
        self._download_fitting()
        self._upload()
