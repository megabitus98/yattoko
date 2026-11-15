#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - config.py
# 8/28/21 15:01
#
# Modified 2026 by megabitus98 (fork): strict parsing (ID lists, booleans, integers), feature switches, DATA_DIR, check_paths, COOKIES_DIR, MAX_PARALLEL_JOBS, TMP_BUDGET, JOB_TIMEOUT, OWN_PUBLIC_IPS, PROXY_EXITS and PROXY_PIN instead of YT_DLP_PROXY, no values in ConfigError messages, upstream's VIP, rclone and ffmpeg settings restored (RCLONE_PATH read from RCLONE_PATH)

__author__ = "Benny <benny.think@gmail.com>"

import ipaddress
import os
from urllib.parse import urlsplit


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
            # no value in the message: the IDs are private
            raise ConfigError(f"{name} must be a comma-separated list of numeric Telegram IDs") from None
    return frozenset(ids)


def parse_ip_list(raw: str | None, name: str) -> frozenset[str]:
    # normalised by ipaddress, so the strings compare equal to what the host check resolves
    ips = set()
    for item in (raw or "").split(","):
        if item := item.strip():
            try:
                ips.add(str(ipaddress.ip_address(item)))
            except ValueError:
                # no value in the message: the list is a secret
                raise ConfigError(f"{name} must be a comma-separated list of IP addresses") from None
    return frozenset(ips)


def parse_exits(raw: str | None) -> list[str]:
    # Ordered download exits: "direct" (no proxy) or an http(s) proxy URL. Not SOCKS: ffmpeg gets the
    # proxy only through HTTP_PROXY and has no SOCKS support. No value in any message: proxy URLs are secrets.
    exits = []
    for item in (raw or "").split(","):
        if not (item := item.strip()):
            continue
        if item != "direct":
            try:
                parts = urlsplit(item)
                valid = parts.scheme in ("http", "https") and bool(parts.hostname)
                parts.port  # raises on a port that is not a number
            except ValueError:
                valid = False
            if not valid:
                raise ConfigError("PROXY_EXITS items must be direct or an http:// or https:// proxy URL")
        exits.append(item)
    return list(dict.fromkeys(exits)) or ["direct"]


def parse_pins(raw: str | None, exits: list[str]) -> dict[str, str]:
    # site=exit pairs, the site as engine/sites.py names it (instagram, youtube, tiktok, ...)
    pins = {}
    for item in (raw or "").split(","):
        if not (item := item.strip()):
            continue
        site, _, exit = (part.strip() for part in item.partition("="))
        if not site or not exit:
            raise ConfigError("PROXY_PIN must be comma-separated site=exit pairs")
        if exit not in exits:
            raise ConfigError("PROXY_PIN: every pinned exit must be one of PROXY_EXITS")
        pins[site.lower()] = exit
    return pins


def parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    raise ConfigError("expected true/false/1/0/yes/no")


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

# restored from upstream, off by default. Upstream master reads RCLONE_PATH and ENABLE_FFMPEG but nothing
# uses them (their code went in its 2025 refactor), so here too they are only read.
ENABLE_FFMPEG = _bool_env("ENABLE_FFMPEG")
RCLONE_PATH = _raw("RCLONE_PATH")

# payment settings: free quota reset daily, paid quota bought with /buy (Telegram payments)
ENABLE_VIP = _bool_env("ENABLE_VIP")
PROVIDER_TOKEN = _raw("PROVIDER_TOKEN")
FREE_DOWNLOAD: int = _int_env("FREE_DOWNLOAD", 3)
TOKEN_PRICE: int = _int_env("TOKEN_PRICE", 10)  # 1 USD=10 downloads; as upstream, the /buy price list does not read it

# Telegram upload limit, set in MiB
TG_NORMAL_MAX_SIZE: int = _int_env("TG_NORMAL_MAX_SIZE", 2000) * 1024 * 1024

# downloads running at once; the rest wait in the queue
MAX_PARALLEL_JOBS: int = _int_env("MAX_PARALLEL_JOBS", 2)
if MAX_PARALLEL_JOBS < 1:
    raise ConfigError("MAX_PARALLEL_JOBS must be at least 1")
# bytes all jobs together may keep under TMPFILE_PATH: the scratch volume's size minus a margin
# (estimate: separate streams, merged file and post-processor copies, about 4.5 GB per job)
TMP_BUDGET: int = _int_env("TMP_BUDGET", MAX_PARALLEL_JOBS * 4500 * 1024 * 1024)
# seconds one job may take
JOB_TIMEOUT: int = _int_env("JOB_TIMEOUT", 2700)
# the home's own static public IPs; links that resolve to them are refused
OWN_PUBLIC_IPS = parse_ip_list(os.getenv("OWN_PUBLIC_IPS"), "OWN_PUBLIC_IPS")
# yt-dlp tries these in order and moves on only when one is blocked; uploads to Telegram never use them
PROXY_EXITS = parse_exits(os.getenv("PROXY_EXITS"))
# a pinned site uses only its exit and never falls back, e.g. instagram=direct
PROXY_PIN = parse_pins(os.getenv("PROXY_PIN"), PROXY_EXITS)

CAPTION_URL_LENGTH_LIMIT = 150
