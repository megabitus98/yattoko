#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - cookies.py
# Modified 2026 by megabitus98 (fork): new file, per-site cookies handed to yt-dlp as in-memory copies

import io
from pathlib import Path


def cookie_options(cookies_dir: Path, site: str) -> dict:
    # yt-dlp writes the jar back to its cookiefile on close (a read-only mount fails, parallel jobs race),
    # so every YoutubeDL gets a fresh copy in memory. The copy is scratch afterwards: never read it back.
    try:
        text = (cookies_dir / f"{site}.txt").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    return {"cookiefile": io.StringIO(text)} if text.strip() else {}


def instagram_session_present(ydl) -> bool:
    # yt-dlp's Instagram extractor drops sessionid when the cookies no longer work
    return any(
        c.name == "sessionid"
        for c in ydl.cookiejar.get_cookies_for_url("https://www.instagram.com/")
    )
