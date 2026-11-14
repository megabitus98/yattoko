#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - cache.py
# Modified 2026 by megabitus98 (fork): get_cache() returns one client shared by every job; fakeredis straight away when REDIS_HOST is unset


import logging
import threading

import fakeredis
import redis

from config import REDIS_HOST

_lock = threading.Lock()
_client: redis.Redis | None = None


def _connect() -> redis.Redis:
    if REDIS_HOST:
        client = redis.Redis(host=REDIS_HOST, db=1, decode_responses=True)
        try:
            client.ping()
            return client
        except redis.RedisError:
            logging.warning(
                "Redis connection failed, using the in-process cache instead."
            )
    return fakeredis.FakeStrictRedis(decode_responses=True)


def get_cache() -> redis.Redis:
    # One client for every job: two fakeredis clients without a shared server see different data.
    global _client
    with _lock:
        if _client is None:
            _client = _connect()
        return _client
