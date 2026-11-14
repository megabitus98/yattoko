#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - jobs.py
# Modified 2026 by megabitus98 (fork): new file, a fixed number of downloads at a time with queue positions, and the size and time limit errors

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor


class TooLarge(Exception):
    """Over Telegram's upload limit, or the scratch space is full (reply BotText.too_large).

    Not an OSError: yt-dlp turns those into UnavailableVideoError."""


class JobTimeout(Exception):
    """The job ran longer than JOB_TIMEOUT."""


class JobQueue:
    def __init__(self, max_parallel: int):
        self._max_parallel = max_parallel
        self._pool = ThreadPoolExecutor(max_parallel, thread_name_prefix="job")
        self._lock = threading.Lock()
        self._unfinished = 0

    def submit(self, fn: Callable[[], None]) -> int:
        # Returns the job's place in the queue: 0 means it starts now. Approximate once jobs finish.
        with self._lock:
            position = max(0, self._unfinished - self._max_parallel + 1)
            self._unfinished += 1
        self._pool.submit(self._run, fn)
        return position

    def _run(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception:
            # nobody reads the Future, so the error would vanish
            logging.exception("Job failed")
        finally:
            with self._lock:
                self._unfinished -= 1

    def shutdown(self, wait: bool) -> None:
        # jobs that have not started are dropped; running ones finish
        self._pool.shutdown(wait=wait, cancel_futures=True)
