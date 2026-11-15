#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - redact.py
# Modified 2026 by megabitus98 (fork): new file, secret redaction for every log line; configured proxy exits masked as a whole and by host name, credentials split at the last @ of the authority, PROVIDER_TOKEN masked, REDIS_PASSWORD masked

import logging
import re
from urllib.parse import urlsplit

MASK = "***"
# greedy up to the last @ before the path, query or fragment, as urllib.parse splits user:pass@host
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/?#]+@", re.IGNORECASE)
_COOKIE_VALUES = re.compile(r"\b(sessionid|csrftoken)=[^\s;&,]+", re.IGNORECASE)


def redact(text: str) -> str:
    # Read at call time: config/__init__ imports this module while setting up logging.
    from config.config import (
        APP_HASH,
        BOT_TOKEN,
        PROVIDER_TOKEN,
        PROXY_EXITS,
        REDIS_PASSWORD,
    )

    # the token first: the test token "1:test" contains the test hash "test";
    # the proxy URLs before the credentials rule, which would change them
    proxies = [e for e in PROXY_EXITS if e != "direct"]
    for secret in (BOT_TOKEN, PROVIDER_TOKEN, APP_HASH, REDIS_PASSWORD, *proxies):
        if secret:
            text = text.replace(secret, MASK)
    # yt-dlp's proxy errors name the host without the URL ("host='proxy.example'", "over proxy proxy.example")
    for host in filter(None, (urlsplit(e).hostname for e in proxies)):
        text = re.sub(re.escape(host), MASK, text, flags=re.IGNORECASE)
    text = _URL_CREDENTIALS.sub(rf"\1{MASK}@", text)
    return _COOKIE_VALUES.sub(rf"\1={MASK}", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # super().format() appends the traceback and stack info, so they are redacted too
        return redact(super().format(record))
