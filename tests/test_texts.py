import re
from pathlib import Path

import config
from config import BotText

# the directory holding the config package: src/ in a checkout, /app in the image (which also holds tests/)
SRC = Path(config.__file__).resolve().parent.parent


def test_no_cyrillic_in_src():
    offenders = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*.py"))
        if "tests" not in path.relative_to(SRC).parts
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
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
