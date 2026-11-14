#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - sites.py
# Modified 2026 by megabitus98 (fork): new file, the site of a URL from yt-dlp's extractors (cookie file name, display name)

from urllib.parse import urlparse

from yt_dlp.extractor import gen_extractor_classes

# Extractor families share one cookie file (YoutubeTab, TikTokVM, InstagramStory, ...); other sites use their key.
_FAMILIES = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"}
# Links no extractor pattern knows (instagr.am, instagram.com/share/...) go to the generic extractor,
# which follows the redirect inside the same YoutubeDL: the cookies must already be there.
_HOSTS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "instagram.com": "instagram",
    "instagr.am": "instagram",
    "tiktok.com": "tiktok",
}


def site_for_url(url: str) -> str:
    try:
        # The extractor yt-dlp would pick, matched offline by URL pattern, in yt-dlp's own order.
        for ie in gen_extractor_classes():
            key = ie.ie_key()
            if key != "Generic" and ie._ENABLED and ie.suitable(url):
                key = key.lower()
                return next(
                    (family for family in _FAMILIES if key.startswith(family)), key
                )
        host = urlparse(url).hostname or ""
    except ValueError:  # e.g. a broken IPv6 literal
        return "generic"
    return next(
        (
            site
            for domain, site in _HOSTS.items()
            if host == domain or host.endswith("." + domain)
        ),
        "generic",
    )


def display_name(site: str) -> str:
    return _FAMILIES.get(site, site.title())
