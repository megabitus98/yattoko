#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - sites.py
# Modified 2026 by megabitus98 (fork): new file, the site of a URL from yt-dlp's extractors (cookie file name, display name)

from yt_dlp.extractor import gen_extractor_classes

# Extractor families share one cookie file (YoutubeTab, TikTokVM, InstagramStory, ...); other sites use their key.
_FAMILIES = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"}


def site_for_url(url: str) -> str:
    # The extractor yt-dlp would pick, matched offline by URL pattern, in yt-dlp's own order.
    for ie in gen_extractor_classes():
        key = ie.ie_key()
        if key != "Generic" and ie._ENABLED and ie.suitable(url):
            key = key.lower()
            return next((family for family in _FAMILIES if key.startswith(family)), key)
    return "generic"


def display_name(site: str) -> str:
    return _FAMILIES.get(site, site.title())
