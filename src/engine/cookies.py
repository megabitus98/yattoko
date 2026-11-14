#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - cookies.py
# Modified 2026 by megabitus98 (fork): new file, per-site cookies handed to yt-dlp as in-memory copies

import io
import logging
import re
from pathlib import Path


def _loadable(line: str) -> bool:
    # The checks yt-dlp's loader and the stdlib one make. A line failing them is printed to stderr
    # or put in an error message, cookie value included, so it never gets that far.
    line = line.removeprefix("#HttpOnly_")
    if line.startswith("#") or not line.strip():
        return True
    fields = line.rstrip("\n").split("\t")
    return (
        len(fields) == 7
        and re.fullmatch(r"(?:[0-9]+(?:\.[0-9]+)?)?", fields[4]) is not None
        and (fields[1] == "TRUE") == fields[0].startswith(".")
    )


def cookie_options(cookies_dir: Path, site: str) -> dict:
    # yt-dlp writes the jar back to its cookiefile on close (a read-only mount fails, parallel jobs race),
    # so every YoutubeDL gets a fresh copy in memory. The copy is scratch afterwards: never read it back.
    try:
        text = (cookies_dir / f"{site}.txt").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    lines = list(io.StringIO(text))  # split the way yt-dlp reads it
    kept = [line for line in lines if _loadable(line)]
    if dropped := len(lines) - len(kept):
        logging.warning("%s.txt: skipped %d malformed line(s)", site, dropped)
        text = "".join(kept)
    return {"cookiefile": io.StringIO(text)} if text.strip() else {}


def instagram_session_present(ydl) -> bool:
    # yt-dlp's Instagram extractor drops sessionid when the cookies no longer work
    return any(
        c.name == "sessionid"
        for c in ydl.cookiejar.get_cookies_for_url("https://www.instagram.com/")
    )
