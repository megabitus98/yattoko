#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - proxy.py
# Modified 2026 by megabitus98 (fork): new file, the yt-dlp proxy option for an exit ("direct" or a proxy URL)


def ydl_proxy(exit: str) -> str:
    # yt-dlp reads an empty proxy as "connect directly" (no proxy from the environment either)
    return "" if exit == "direct" else exit
