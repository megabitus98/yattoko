import io
import logging
import os
import subprocess
import sys

import pytest
from pyrogram import enums

import config
import main
from config import BotText
from fakes import FakeClient, fake_message
from utils.redact import RedactingFormatter, redact

PROXY = "http://u:secret@proxy.example:8080"


def test_redact_token_and_proxy():
    text = redact("bot 1:test via http://u:p@proxy.example:8080")
    assert "1:test" not in text
    assert "u:p@" not in text
    assert "proxy.example:8080" in text

    cookies = redact("Cookie: sessionid=abc123; csrftoken=def456")
    assert "abc123" not in cookies and "def456" not in cookies


def test_formatter_redacts_traceback():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test_redact.traceback")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        raise RuntimeError(f"proxy {PROXY} refused")
    except RuntimeError:
        logger.exception("download failed")
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert "Traceback" in output and "download failed" in output
    assert "secret" not in output


def test_root_logger_redacts():
    # Under pytest the root logger already has pytest's handlers, so basicConfig() is a no-op here;
    # a fresh interpreter importing main (pyrogram and yt-dlp load before config) shows what the bot writes.
    code = (
        "import logging, main\n"
        "try:\n"
        f"    raise RuntimeError('token 1:test proxy {PROXY}')\n"
        "except RuntimeError:\n"
        "    logging.getLogger('any').exception('boom')\n"
    )
    # the directory holding the config package: src/ in a checkout, /app in the image
    src = os.path.dirname(os.path.dirname(config.__file__))
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": src},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "boom" in result.stderr and "Traceback" in result.stderr
    assert "1:test" not in result.stderr
    assert "secret" not in result.stderr


def _fail(*args, **kwargs):
    raise RuntimeError("http://10.0.0.1 failed")


@pytest.mark.parametrize(
    "handler, entrance, text, chat_type",
    [
        (
            "download_handler",
            "youtube_entrance",
            "https://youtu.be/abc",
            enums.ChatType.PRIVATE,
        ),
        (
            "direct_download",
            "direct_entrance",
            "/direct https://example.com/a.mp4",
            enums.ChatType.PRIVATE,
        ),
        (
            "spdl_handler",
            "special_download_entrance",
            "/spdl https://pixeldrain.com/u/abc",
            enums.ChatType.PRIVATE,
        ),
        (
            "ytdl_handler",
            "youtube_entrance",
            "/ytdl https://youtu.be/abc",
            enums.ChatType.GROUP,
        ),
    ],
)
def test_no_exception_text_to_users(monkeypatch, handler, entrance, text, chat_type):
    for switch in ("ENABLE_DIRECT", "ENABLE_SPDL", "ENABLE_GROUPS"):
        monkeypatch.setattr(main, switch, True)
    monkeypatch.setattr(main, entrance, _fail)
    message, replies = fake_message(
        text,
        chat_type=chat_type,
        chat_id=-100 if chat_type == enums.ChatType.GROUP else None,
    )
    getattr(main, handler)(FakeClient(), message)
    assert replies[-1] == BotText.error
    assert not any("10.0.0.1" in reply for reply in replies)
