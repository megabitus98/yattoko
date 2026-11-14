#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - health.py
# Modified 2026 by megabitus98 (fork): new file, heartbeat thread and the probe: `python health.py` exits 0 while the heartbeat file is fresh
#
# Standard library only: the probe runs often and must not load the bot's config.

import logging
import sys
import threading
import time
from pathlib import Path

HEALTH_FILE = Path("/tmp/healthy")
MAX_AGE = 180  # seconds; three missed beats


def start_heartbeat(
    client, path: Path = HEALTH_FILE, interval: int = 60
) -> threading.Thread:
    # The file is touched only after Telegram answered, so a hung connection makes the probe fail.
    def beat():
        while True:
            try:
                client.get_me()
                path.touch()
            except Exception:
                logging.exception("Heartbeat failed")
            time.sleep(interval)

    thread = threading.Thread(target=beat, name="heartbeat", daemon=True)
    thread.start()
    return thread


def is_healthy(path: Path = HEALTH_FILE, max_age: float = MAX_AGE) -> bool:
    try:
        return time.time() - path.stat().st_mtime < max_age
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(0 if is_healthy() else 1)
