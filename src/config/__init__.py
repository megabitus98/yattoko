#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - __init__.py.py
# Modified 2026 by megabitus98 (fork): root log handler redacts secrets, HTTP client loggers at WARNING

import logging

from dotenv import load_dotenv

load_dotenv()

from config.config import *
from config.constant import *
from utils.redact import RedactingFormatter

_log_handler = logging.StreamHandler()
_log_handler.setFormatter(
    RedactingFormatter(
        "[%(asctime)s %(filename)s:%(lineno)d %(levelname).1s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
# they log request URLs at INFO
for _name in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_name).setLevel(logging.WARNING)
