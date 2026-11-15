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
# Neither contains the other, nor conftest's APP_HASH=test: each one is masked by its own rule only.
TOKEN = "123456789:AAFakeBotTokenValue"
HASH = "0123456789abcdef0123456789abcdef"


def test_redact_token_and_proxy(monkeypatch):
    monkeypatch.setattr(config.config, "BOT_TOKEN", TOKEN)
    monkeypatch.setattr(config.config, "APP_HASH", HASH)
    text = redact(f"bot {TOKEN} hash {HASH} via http://u:p@proxy.example:8080")
    assert "AAFakeBotTokenValue" not in text and "123456789:" not in text
    assert "0123456789abcdef" not in text
    assert "u:p@" not in text
    assert "proxy.example:8080" in text

    cookies = redact("Cookie: sessionid=abc123; csrftoken=def456")
    assert "abc123" not in cookies and "def456" not in cookies


def test_redact_at_in_password():
    # split at the last @ of the authority, as urllib.parse does
    assert (
        redact("via http://user:p@ss@host.example:1/x")
        == "via http://***@host.example:1/x"
    )
    # an @ after the authority is not a credential
    for text in (
        "https://www.tiktok.com/@a/video/1",
        "https://example.com/x?mail=a@b.example",
    ):
        assert redact(text) == text


def test_redact_masks_configured_exits(monkeypatch):
    exits = ["direct", PROXY, "http://plain.example:3128"]
    monkeypatch.setattr(config.config, "PROXY_EXITS", exits)
    text = redact(f"via {PROXY} then http://plain.example:3128 then direct")
    assert (
        "secret" not in text
        and "proxy.example" not in text
        and "plain.example" not in text
    )
    assert text.endswith("then direct")


def test_redact_masks_exit_hosts(monkeypatch):
    # real yt-dlp proxy errors name the host without the URL (urllib3 and curl-cffi forms)
    monkeypatch.setattr(config.config, "PROXY_EXITS", ["direct", PROXY])
    for text in (
        "('Unable to connect to proxy', NewConnectionError(\"HTTPConnection(host='proxy.example', port=8080): refused\"))",
        "curl: (7) Failed to connect to example.invalid:443 over proxy Proxy.Example after 0 ms",
    ):
        assert "proxy.example" not in redact(text).lower()


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
        f"    raise RuntimeError('token {TOKEN} proxy {PROXY}')\n"
        "except RuntimeError:\n"
        "    logging.getLogger('any').exception('boom')\n"
    )
    # the directory holding the config package: src/ in a checkout, /app in the image
    src = os.path.dirname(os.path.dirname(config.__file__))
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": src, "BOT_TOKEN": TOKEN},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "boom" in result.stderr and "Traceback" in result.stderr
    assert "AAFakeBotTokenValue" not in result.stderr
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
