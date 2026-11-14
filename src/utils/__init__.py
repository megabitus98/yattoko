#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - __init__.py.py
# Modified 2026 by megabitus98 (fork): extract_first_url for links with text around them; is_youtube removed (engine/sites.py picks the site)


import functools
import re
import threading
import time


def sizeof_fmt(num: int, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


def timeof_fmt(seconds: int | float):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def extract_first_url(text: str | None) -> str | None:
    # share sheets and chats wrap the link in other text; take the first http(s) URL
    match = re.search(r"https?://\S+", text or "", re.IGNORECASE)
    return match.group(0).rstrip(").,") if match else None


def extract_url_and_name(message_text):
    # Regular expression to match the URL
    url_pattern = r"(https?://[^\s]+)"
    # Regular expression to match the new name after '-n'
    name_pattern = r"-n\s+(.+)$"

    # Find the URL in the message_text
    url_match = re.search(url_pattern, message_text)
    url = url_match.group(0) if url_match else None

    # Find the new name in the message_text
    name_match = re.search(name_pattern, message_text)
    new_name = name_match.group(1) if name_match else None

    return url, new_name


def debounce(wait_seconds):
    """
    Thread-safe debounce decorator for methods whose instance exposes `_bot_msg`
    (with chat.id and id attributes). The wrapped method runs only if it hasn't
    run for the same (chat.id, msg.id) within the last `wait_seconds`.
    """

    def decorator(func):
        last_called = {}
        lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            bot_msg = args[0]._bot_msg
            key = (bot_msg.chat.id, bot_msg.id)

            with lock:
                if key not in last_called or now - last_called[key] >= wait_seconds:
                    last_called[key] = now
                    return func(*args, **kwargs)

        return wrapper

    return decorator
