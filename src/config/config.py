#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - config.py
# 8/28/21 15:01
#
# Modified 2026 by megabitus98 (fork): strict parsing (ID lists, booleans, integers), feature switches, DATA_DIR, check_paths, COOKIES_DIR

__author__ = "Benny <benny.think@gmail.com>"

import os


class ConfigError(Exception):
    pass


def _raw(name: str) -> str | None:
    # unset and blank ("VAR=") both mean "use the default"
    value = os.getenv(name, "").strip()
    return value or None


def parse_id_list(raw: str | None, name: str) -> frozenset[int]:
    ids = set()
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            raise ConfigError(
                f"{name} must be a comma-separated list of numeric Telegram IDs, got {item!r}"
            ) from None
    return frozenset(ids)


def parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise ConfigError(f"expected true/false/1/0/yes/no, got {raw!r}")


def check_paths(data_dir: str, tmp_dir: str) -> None:
    # The startup purge empties tmp_dir, so it must not overlap the data volume (database, session) either way.
    data, tmp = os.path.realpath(data_dir), os.path.realpath(tmp_dir)
    if os.path.commonpath([data, tmp]) in (data, tmp):
        raise ConfigError(
            f"TMPFILE_PATH ({tmp_dir}) and DATA_DIR ({data_dir}) must not overlap: TMPFILE_PATH is emptied at startup"
        )


def _bool_env(name: str, default: bool = False) -> bool:
    try:
        return parse_bool(_raw(name), default)
    except ConfigError as e:
        raise ConfigError(f"{name}: {e}") from None


def _int_env(name: str, default: int | None) -> int | None:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        # no value in the message: a swapped APP_ID/APP_HASH must not print the hash
        raise ConfigError(f"{name} must be an integer") from None


# general settings
WORKERS: int = _int_env("WORKERS", 16)
APP_ID: int | None = _int_env("APP_ID", None)
APP_HASH = _raw("APP_HASH")
BOT_TOKEN = _raw("BOT_TOKEN")
YT_DLP_PROXY = _raw("YT_DLP_PROXY") or ""

# access: env names stay OWNER and AUTHORIZED_USER; an empty list allows nobody
OWNERS = parse_id_list(os.getenv("OWNER"), "OWNER")
AUTHORIZED_USERS = parse_id_list(os.getenv("AUTHORIZED_USER"), "AUTHORIZED_USER")
ALLOWED_USERS = AUTHORIZED_USERS | OWNERS

# state
DATA_DIR = _raw("DATA_DIR") or "/data"
TMPFILE_PATH = _raw("TMPFILE_PATH") or "/tmp/ytdlbot"
DB_DSN = _raw("DB_DSN") or f"sqlite:///{DATA_DIR}/ytdlbot.db"
REDIS_HOST = _raw("REDIS_HOST")
# one Netscape cookies file per site: <COOKIES_DIR>/instagram.txt, youtube.txt, tiktok.txt, ...
COOKIES_DIR = _raw("COOKIES_DIR") or "/cookies"

AUDIO_FORMAT = _raw("AUDIO_FORMAT") or "m4a"
PREFERRED_AUDIO_LANG = _raw("PREFERRED_AUDIO_LANG") or ""

# feature switches, all off unless turned on in env
ENABLE_SEARCH = _bool_env("ENABLE_SEARCH")
ENABLE_DIRECT = _bool_env("ENABLE_DIRECT")
ENABLE_ARIA2 = _bool_env("ENABLE_ARIA2")
ENABLE_SPDL = _bool_env("ENABLE_SPDL")
ENABLE_STATS = _bool_env("ENABLE_STATS")
ENABLE_GROUPS = _bool_env("ENABLE_GROUPS")
M3U8_SUPPORT = _bool_env("M3U8_SUPPORT")

# Telegram upload limit, set in MiB
TG_NORMAL_MAX_SIZE: int = _int_env("TG_NORMAL_MAX_SIZE", 2000) * 1024 * 1024
CAPTION_URL_LENGTH_LIMIT = 150
