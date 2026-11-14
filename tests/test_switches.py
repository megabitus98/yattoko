from types import SimpleNamespace

import pytest
from pyrogram import enums

import main
from config import BotText


class FakeClient:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def fake_message(text, user_id=2, chat_type=enums.ChatType.PRIVATE):
    replies = []
    message = SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id),
        chat=SimpleNamespace(id=user_id, type=chat_type),
        reply_text=lambda reply, **kwargs: replies.append(reply),
    )
    return message, replies


@pytest.fixture
def downloads(monkeypatch):
    # Every way a handler can start work; a disabled feature must reach none of them.
    calls = []
    for name in (
        "direct_entrance",
        "special_download_entrance",
        "youtube_entrance",
        "search_ytb",
    ):
        monkeypatch.setattr(
            main, name, lambda *args, _name=name, **kwargs: calls.append(_name)
        )
    return calls


def _assert_disabled(handler, text, downloads, user_id=2):
    message, replies = fake_message(text, user_id=user_id)
    handler(FakeClient(), message)
    assert replies == [BotText.disabled]
    assert downloads == []


def test_direct_disabled_by_default(downloads):
    _assert_disabled(
        main.direct_download, "/direct https://example.com/file.bin", downloads
    )


def test_spdl_disabled_by_default(downloads):
    _assert_disabled(main.spdl_handler, "/spdl https://pixeldrain.com/u/abc", downloads)


def test_stats_disabled_by_default(downloads):
    _assert_disabled(main.stats_handler, "/stats", downloads, user_id=1)


def test_search_disabled_by_default(downloads):
    _assert_disabled(main.download_handler, "funny cats", downloads)


def test_m3u8_blocked_when_off(downloads, monkeypatch):
    monkeypatch.setattr(main, "M3U8_SUPPORT", False)
    _assert_disabled(
        main.download_handler, "https://example.com/live/index.m3u8", downloads
    )


def test_stats_owner_only_when_enabled(downloads, monkeypatch):
    monkeypatch.setattr(main, "ENABLE_STATS", True)
    _assert_disabled(main.stats_handler, "/stats", downloads, user_id=2)


def test_ytdl_ignored_when_groups_off(downloads):
    message, replies = fake_message(
        "/ytdl https://youtu.be/abc", chat_type=enums.ChatType.GROUP
    )
    main.ytdl_handler(FakeClient(), message)
    assert replies == []
    assert downloads == []
