#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - errors.py
# Modified 2026 by megabitus98 (fork): new file, download errors sorted into login_required/blocked/unavailable/other, RefusedContent for playlists and live streams, links refused by the host check are unavailable

import re
from typing import Literal
from urllib.parse import urlparse

from yt_dlp.networking.exceptions import HTTPError, ProxyError
from yt_dlp.utils import GeoRestrictedError

from config import BotText
from utils.netcheck import BlockedHost

Kind = Literal["login_required", "blocked", "unavailable", "other"]


class RefusedContent(Exception):
    """A playlist, channel or live stream: refused before anything is downloaded (reply BotText.refused)."""


# Checked in this order: YouTube's rate-limit text starts with "Video unavailable",
# and its private-video text also says "sign in". tests/test_errors.py pins the strings.
_PATTERNS: list[tuple[Kind, re.Pattern]] = [
    (
        "blocked",
        re.compile(
            r"not a bot|\brate.limit|isn.t available, try again later|IP address is blocked|IP is likely being blocked"
            r"|Unexpected response from webpage request|empty media response|HTTP Error (?:403|429)\b|captcha",
            re.IGNORECASE,
        ),
    ),
    (
        "unavailable",
        re.compile(
            r"Private video|Video unavailable|video (?:is )?not available|who follow this account"
            r"|no video in this post|do not have permission to view|members-only",
            re.IGNORECASE,
        ),
    ),
    (
        "login_required",
        re.compile(
            r"confirm your age|inappropriate for some users|18 years old|age.restricted"
            r"|requiring login|\blog ?in\b|sign in|--cookies|registered users",
            re.IGNORECASE,
        ),
    ),
]
# URLs in error text (the user's own link, yt-dlp's wiki links) must not decide the kind
_URL = re.compile(r"https?://\S+")

_SITES = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "instagr.am": "Instagram",
}


def _chain(err: BaseException):
    # yt-dlp keeps the real cause in .cause (ExtractorError, RequestError) or .exc_info (DownloadError)
    seen, todo = set(), [err]
    while todo:
        e = todo.pop(0)
        if not isinstance(e, BaseException) or id(e) in seen:
            continue
        seen.add(id(e))
        yield e
        info = getattr(e, "exc_info", None)
        todo += [
            getattr(e, "cause", None),
            info[1] if isinstance(info, tuple) and len(info) > 1 else None,
            e.__cause__,
            e.__context__,
        ]


def classify(err: BaseException) -> Kind:
    chain = list(_chain(err))
    for e in chain:
        if isinstance(e, (GeoRestrictedError, BlockedHost)):
            return "unavailable"
        if isinstance(e, ProxyError) or (
            isinstance(e, HTTPError) and e.status in (403, 429)
        ):
            return "blocked"
    text = _URL.sub("", "\n".join(map(str, chain)))
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return kind
    return "other"


def user_message(kind: Kind, site: str) -> str:
    texts = {
        "login_required": BotText.login_required,
        "blocked": BotText.blocked,
        "unavailable": BotText.unavailable,
    }
    return texts.get(kind, BotText.error).format(site=site)


def site_name(url: str | None) -> str:
    # Display name for the replies above. Host based until the extractor-based site lookup exists;
    # unknown hosts get a fixed name so the reply never echoes a hostname.
    try:
        host = (urlparse(url or "").hostname or "").removeprefix("www.")
    except ValueError:  # e.g. a broken IPv6 literal
        return "This site"
    for domain, name in _SITES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return "This site"
