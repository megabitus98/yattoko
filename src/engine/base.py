#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - types.py
# Modified 2026 by megabitus98 (fork): upload fallback loop for kurigram 2.2.27 (save_file raises), English texts from config.constant, download failures logged, classified and shown once in the progress message, settings read by the requesting user's ID, BotText.refused for playlists and live streams, host check first, size, scratch budget and time limits in download_hook, one retry a quality lower for an oversized file, shared file_id cache keyed with SponsorBlock, owner notice after a login_required or blocked reply

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
import subprocess

from abc import ABC, abstractmethod
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import final

import ffmpeg
import filetype
from pyrogram import enums, errors, types
from tqdm import tqdm

from config import (
    JOB_TIMEOUT,
    OWN_PUBLIC_IPS,
    TG_NORMAL_MAX_SIZE,
    TMP_BUDGET,
    TMPFILE_PATH,
    BotText,
    Types,
)
from database import get_cache
from database.model import (
    get_format_settings,
    get_quality_settings,
    get_sponsorblock_settings,
    get_vcodec_settings,
)
from engine.errors import OWNER_TOLD, RefusedContent, classify, site_name, tell_owners, user_message
from engine.jobs import JobTimeout, TooLarge
from utils import debounce, dir_size, netcheck

# highest first, as in /settings; an oversized file is downloaded once more one step lower
QUALITIES = ("1440p", "1080p", "720p", "480p", "240p")


def generate_input_media(file_paths: list, cap: str) -> list:
    input_media = []
    for path in file_paths:
        mime = filetype.guess_mime(path)
        if "video" in mime:
            input_media.append(types.InputMediaVideo(media=path))
        elif "image" in mime:
            input_media.append(types.InputMediaPhoto(media=path))
        elif "audio" in mime:
            input_media.append(types.InputMediaAudio(media=path))
        else:
            input_media.append(types.InputMediaDocument(media=path))

    input_media[0].caption = cap
    return input_media


class BaseDownloader(ABC):
    def __init__(self, client: Types.Client, bot_msg: Types.Message, url: str):
        # first, so a refused link creates nothing (reply: BotText.unavailable)
        netcheck.check_url(url, OWN_PUBLIC_IPS)
        # the downloader is built when the job starts, so this is the job's own clock
        self._deadline = time.monotonic() + JOB_TIMEOUT
        self._client = client
        self._url = url
        # chat id is the same for private chat
        self._chat_id = self._from_user = bot_msg.chat.id
        if bot_msg.chat.type == enums.ChatType.GROUP or bot_msg.chat.type == enums.ChatType.SUPERGROUP:
            # if in group, we need to find out who send the message
            self._from_user = bot_msg.reply_to_message.from_user.id
        self._id = bot_msg.id
        os.makedirs(TMPFILE_PATH, exist_ok=True)
        self._tempdir = tempfile.TemporaryDirectory(prefix="ytdl-", dir=TMPFILE_PATH)
        self._bot_msg: Types.Message = bot_msg
        # every exit a download went through, for the owner notice
        self._exits_tried: list[str] = []
        # settings are saved per user (main.save_setting); in a group the chat ID is the group's
        self._quality = get_quality_settings(self._from_user)
        self._vcodec = get_vcodec_settings(self._from_user)
        self._format = get_format_settings(self._from_user)
        self._sponsorblock = get_sponsorblock_settings(self._from_user)
        # fixed before any retry a quality lower, so the file is cached under what the user asked for
        self._video_key = self._calc_video_key()

    @staticmethod
    def __remove_bash_color(text):
        return re.sub(r"\u001b|\[0;94m|\u001b\[0m|\[0;32m|\[0m|\[0;33m", "", text)

    @staticmethod
    def __tqdm_progress(desc, total, finished, speed="", eta=""):
        def more(title, initial):
            if initial:
                return f"{title} {initial}"
            else:
                return ""

        f = StringIO()
        tqdm(
            total=total,
            initial=finished,
            file=f,
            ascii=False,
            unit_scale=True,
            ncols=30,
            bar_format="{l_bar}{bar} |{n_fmt}/{total_fmt} ",
        )
        raw_output = f.getvalue()
        tqdm_output = raw_output.split("|")
        progress = f"`[{tqdm_output[1]}]`"
        detail = tqdm_output[2].replace("[A", "")
        text = f"""
{desc}

🔌 {progress}
🔌 {detail}
{"" if len(speed) == 0 else "⚡️"} {more(BotText.speed, speed)}
{"" if len(eta) == 0 else "⏳"} {more(BotText.eta, eta)}
        """
        f.close()
        return text

    def check_limits(self, downloaded: int, total: int = 0) -> None:
        # The total can be unknown or an estimate, so the bytes so far count too. The scratch volume is
        # shared by all jobs: one runaway download must not fill it and get the pod evicted.
        # dir_size walks TMPFILE_PATH on every progress update; a few files per job keep that cheap.
        if max(downloaded, total) > TG_NORMAL_MAX_SIZE or dir_size(Path(TMPFILE_PATH)) > TMP_BUDGET:
            raise TooLarge()
        if time.monotonic() > self._deadline:
            raise JobTimeout()

    def download_hook(self, d: dict):
        if d["status"] == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            self.check_limits(downloaded, total)

            # percent = remove_bash_color(d.get("_percent_str", "N/A"))
            speed = self.__remove_bash_color(d.get("_speed_str", "N/A"))
            eta = self.__remove_bash_color(d.get("_eta_str", d.get("eta")))
            text = self.__tqdm_progress(BotText.downloading, total, downloaded, speed, eta)
            self.edit_text(text)

    def upload_hook(self, current, total):
        text = self.__tqdm_progress(BotText.uploading, total, current)
        self.edit_text(text)

    @debounce(5)
    def edit_text(self, text: str):
        self._bot_msg.edit_text(text)

    @abstractmethod
    def _setup_formats(self) -> list | None:
        pass

    @abstractmethod
    def _download(self, formats) -> list:
        # responsible for get format and download it
        pass

    @property
    def _methods(self):
        return {
            "document": self._client.send_document,
            "audio": self._client.send_audio,
            "video": self._client.send_video,
            "animation": self._client.send_animation,
            "photo": self._client.send_photo,
        }

    def send_something(self, *, chat_id, files, _type, caption=None, thumb=None, **kwargs):
        self._client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_DOCUMENT)
        is_cache = kwargs.pop("cache", False)
        if len(files) > 1 and is_cache == False:
            inputs = generate_input_media(files, caption)
            return self._client.send_media_group(chat_id, inputs)[0]
        else:
            file_arg_name = None
            if _type == "photo":
                file_arg_name = "photo"
            elif _type == "video":
                file_arg_name = "video"
            elif _type == "animation":
                file_arg_name = "animation"
            elif _type == "document":
                file_arg_name = "document"
            elif _type == "audio":
                file_arg_name = "audio"
            else:
                logging.error("Unknown _type encountered: %s", _type)
                return None

            send_args = {
                "chat_id": chat_id,
                file_arg_name: files[0],
                "caption": caption,
                "progress": self.upload_hook,
                **kwargs,
            }

            if _type in ["video", "animation", "document", "audio"] and thumb is not None:
                send_args["thumb"] = thumb

            return self._methods[_type](**send_args)

    def get_metadata(self):
        files = list(Path(self._tempdir.name).glob("*"))
        if not files:
            return dict(height=0, width=0, duration=0, thumb=None, caption=self._url)
        video_path = files[0]
        filename = Path(video_path).name
        width = height = duration = 0
        try:
            video_streams = ffmpeg.probe(video_path, select_streams="v")
            width = video_streams.get("streams", [])[0].get('width')
            height = video_streams.get("streams", [])[0].get('height')
            duration = int(float(video_streams["format"]["duration"]))
        except Exception as e:
            logging.error("Error while getting metadata: %s", e)

        thumb = None

        try:
            thumb = Path(video_path).parent.joinpath(f"{uuid.uuid4().hex}-thunmnail.jpg").as_posix()
            # ffmpeg -i video.mp4 -map 0:v -map -0:V -c copy cover.jpg
            subprocess.run(["ffmpeg", "-y", "-i", video_path, "-map", "0:v", "-map", "-0:V", "-c", "copy", thumb], check=True, text=True)
        except Exception:
            thumb = None

        caption = BotText.caption.format(url=self._url, filename=filename, width=width, height=height, duration=duration)
        return dict(height=height, width=width, duration=duration, thumb=thumb, caption=caption)

    def _upload(self, files=None, meta=None):
        if files is None:
            files = list(Path(self._tempdir.name).glob("*"))

        if meta is None:
            meta = self.get_metadata()

        success = SimpleNamespace(document=None, video=None, audio=None, animation=None, photo=None)
        if self._format == "document":
            logging.info("Sending as document for %s", self._url)
            success = self.send_something(
                chat_id=self._chat_id,
                files=files,
                _type="document",
                thumb=meta.get("thumb", None),
                force_document=True,
                caption=meta.get("caption", None),
            )
        elif self._format == "photo":
            logging.info("Sending as photo for %s", self._url)
            success = self.send_something(
                chat_id=self._chat_id,
                files=files,
                _type="photo",
                caption=meta.get("caption"),
            )
        elif self._format == "audio":
            logging.info("Sending as audio for %s", self._url)
            success = self.send_something(
                chat_id=self._chat_id,
                files=files,
                thumb=meta.get("thumb", None),
                _type="audio",
                caption=meta.get("caption", None),
            )
        elif self._format == "video":
            logging.info("Sending as video for %s", self._url)
            # kurigram >= 2.2.26: a failed save_file raises; send_* can also return None (no message back)
            last_error = None
            for method in ["video", "animation", "audio", "photo"]:
                current_meta = meta.copy()
                if method == "photo":
                    for key in ("thumb", "duration", "height", "width"):
                        current_meta.pop(key, None)
                elif method == "audio":
                    current_meta.pop("height", None)
                    current_meta.pop("width", None)

                try:
                    success = self.send_something(
                        chat_id=self._chat_id,
                        files=files,
                        _type=method,
                        **current_meta,
                    )
                except Exception as e:
                    last_error = e
                    logging.error("Sending as %s failed: %s", method, e)
                    continue
                if success is not None:
                    break
                logging.error("Sending as %s returned no message", method)
            else:
                raise RuntimeError("Upload failed with every send method") from last_error

        else:
            logging.error("Unknown upload format settings for %s", self._format)
            return

        obj = success.document or success.video or success.audio or success.animation or success.photo
        mapping = {
            "file_id": json.dumps([getattr(obj, "file_id", None)]),
            "meta": json.dumps({k: v for k, v in meta.items() if k != "thumb"}, ensure_ascii=False),
        }

        get_cache().hset(self._video_key, mapping=mapping)
        # change progress bar to done
        self._bot_msg.edit_text(BotText.done)
        return success

    def _get_video_cache(self):
        return get_cache().hgetall(self._video_key)

    def _calc_video_key(self):
        # every setting that changes the file that is sent
        settings = (self._url, self._quality, self._format, self._vcodec, self._sponsorblock)
        return hashlib.md5("\n".join(settings).encode()).hexdigest()

    def _fits(self, files) -> bool:
        return all(os.path.getsize(f) <= TG_NORMAL_MAX_SIZE for f in files)

    def _download_fitting(self) -> list:
        # Checked after merge and post-processing, before the upload: Telegram refuses bigger files.
        # One retry a quality lower, then refuse. A limit hit in download_hook gets no retry.
        files = self._download(self._setup_formats())
        if not self._fits(files) and self._quality in QUALITIES[:-1]:
            logging.info("%s is over the size limit at %s, trying once lower", self._url, self._quality)
            # empty: yt-dlp would take a file that is already there as downloaded
            shutil.rmtree(self._tempdir.name)
            os.makedirs(self._tempdir.name)
            self._quality = QUALITIES[QUALITIES.index(self._quality) + 1]
            files = self._download(self._setup_formats())
        if not self._fits(files):
            raise TooLarge()
        return files

    @final
    def start(self):
        try:
            if cache := self._get_video_cache():
                logging.info("Cache hit for %s", self._url)
                meta, file_id = json.loads(cache["meta"]), json.loads(cache["file_id"])
                meta["cache"] = True
                self._upload(file_id, meta)
            else:
                self._start()
        except errors.Flood:
            raise  # the job in main.submit_download() tells the user to wait
        except RefusedContent:
            logging.info("Refused %s: not a single video", self._url)
            self._bot_msg.edit_text(BotText.refused)
        except TooLarge:
            logging.info("Refused %s: over the size limit or the scratch budget", self._url)
            self._bot_msg.edit_text(BotText.too_large)
        except Exception as e:
            # one reply: the progress message becomes the error text; the traceback only goes to the log
            logging.exception("Download failed for %s", self._url)
            kind = classify(e)
            self._bot_msg.edit_text(user_message(kind, site_name(self._url)))
            # after the reply: the reply says so, and a slow notice must not hold it up
            if kind in OWNER_TOLD:
                tell_owners(self._client, self._url, kind, str(e), self._exits_tried)
        finally:
            self._tempdir.cleanup()

    @abstractmethod
    def _start(self):
        pass
