#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - cache.py
# Modified 2026 by megabitus98 (fork): get_cache() returns one client shared by every job; fakeredis straight away when REDIS_HOST is unset, REDIS_PASSWORD and REDIS_DB, 5 s timeouts


import logging
import threading

import fakeredis
import redis

from config import REDIS_DB, REDIS_HOST, REDIS_PASSWORD

_lock = threading.Lock()
_client: redis.Redis | None = None


def _connect() -> redis.Redis:
    if REDIS_HOST:
        # timeouts: a Redis that stops answering must not hang a job
        client = redis.Redis(
            host=REDIS_HOST,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        try:
            client.ping()
            logging.info("File cache: Redis at %s, db %s", REDIS_HOST, REDIS_DB)
            return client
        except redis.RedisError as e:
            # the exception type only: its text could name the server's reply
            logging.warning(
                "Redis connection failed (%s), using the in-process cache instead.",
                type(e).__name__,
            )
    return fakeredis.FakeStrictRedis(decode_responses=True)


def get_cache() -> redis.Redis:
    # One client for every job: two fakeredis clients without a shared server see different data.
    global _client
    with _lock:
        if _client is None:
            _client = _connect()
        return _client
