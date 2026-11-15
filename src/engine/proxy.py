#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - proxy.py
# Modified 2026 by megabitus98 (fork): new file, the yt-dlp proxy option for an exit ("direct" or a proxy URL), which exits a site may use, exit labels for logs and owner notices

# the parsers live with the other env parsers; config.config cannot import engine (engine imports config)
from config.config import parse_exits, parse_pins  # noqa: F401


def exits_for(site: str, exits: list[str], pins: dict[str, str]) -> list[str]:
    # a pinned site never falls back
    return [pins[site]] if site in pins else exits


def exit_label(exit: str, exits: list[str]) -> str:
    # The position in PROXY_EXITS ("exit 2"): proxy URLs are secrets and never go into logs or notices.
    return exit if exit == "direct" else f"exit {exits.index(exit) + 1}"


def ydl_proxy(exit: str) -> str:
    # yt-dlp reads an empty proxy as "connect directly" (no proxy from the environment either)
    return "" if exit == "direct" else exit
