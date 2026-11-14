#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - selfcheck.py
# Modified 2026 by megabitus98 (fork): new file, image self-check (versions, impersonation, writable dirs)

import os
import tempfile

import curl_cffi
import pyrogram
from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.version import __version__ as yt_dlp_version


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def run_selfcheck() -> dict[str, object]:
    # env is read at call time on purpose: the check must see what the container really has
    with YoutubeDL({"quiet": True}) as ydl:
        impersonation = bool(ydl._impersonate_target_available(ImpersonateTarget()))
    result: dict[str, object] = {
        "yt_dlp": yt_dlp_version,
        "curl_cffi": curl_cffi.__version__,
        "kurigram": pyrogram.__version__,
        "impersonation": impersonation,
        "data_writable": _writable(os.getenv("DATA_DIR") or "/data"),
        "tmp_writable": _writable(os.getenv("TMPFILE_PATH") or "/tmp/ytdlbot"),
    }
    result["ok"] = all(result[key] is True for key in ("impersonation", "data_writable", "tmp_writable"))
    return result
