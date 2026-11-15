import re
from pathlib import Path
from types import SimpleNamespace

import config
import main
from config import BotText
from fakes import fake_message

# the directory holding the config package: src/ in a checkout, /app in the image (which also holds tests/)
SRC = Path(config.__file__).resolve().parent.parent


def test_no_cyrillic_in_src():
    # every file, not only *.py (in the image SRC is /app, which also holds pyproject.toml and uv.lock)
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*"))
        if path.is_file()
        and not {"tests", "__pycache__"} & set(path.relative_to(SRC).parts)
        for number, line in enumerate(
            path.read_bytes().decode("utf-8", "replace").splitlines(), 1
        )
        if re.search("[\u0400-\u04ff]", line)
    ]
    assert offenders == []


def test_about_credits_upstream():
    assert "github.com/tgbot-collection/ytdlbot" in BotText.about
    assert "github.com/Katze-942/ytdlbot" in BotText.about
    assert "Apache-2.0" in BotText.about
    for text in (BotText.about, BotText.help, BotText.start):
        assert "t.me/" not in text
        # Telegram turns @name into a link to that account
        assert not re.search(r"(?<![\w/])@\w", text)


def test_every_settings_button_has_label():
    choices = (
        main.FORMAT_CHOICES
        | main.QUALITY_CHOICES
        | main.VCODEC_CHOICES
        | main.SPONSORBLOCK_CHOICES
    )
    assert set(choices) <= set(BotText.buttons)


def test_about_without_link_preview():
    sent = []
    client = SimpleNamespace(
        send_chat_action=lambda *args, **kwargs: None,
        send_message=lambda chat_id, text, **kwargs: sent.append((text, kwargs)),
    )
    main.about_handler(client, fake_message("/about")[0])
    assert [text for text, _ in sent] == [f"{BotText.about.rstrip()}\n\nVersion: {main.APP_VERSION}"]
    assert sent[0][1]["link_preview_options"].is_disabled is True


def test_no_deprecated_preview_argument():
    # kurigram 2.2.27 logs a deprecation warning for every disable_web_page_preview call
    src = Path(__file__).parents[1] / "src"
    assert [p.name for p in src.rglob("*.py") if "disable_web_page_preview" in p.read_text()] == []
