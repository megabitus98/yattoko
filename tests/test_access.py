import asyncio
from types import SimpleNamespace

import pytest
from pyrogram import StopPropagation, enums, types
from pyrogram.handlers import CallbackQueryHandler

import main
from config import BotText
from database.model import get_quality_settings
from fakes import FakeClient, fake_callback, fake_message
from utils import access

GUARD_CALLBACKS = (access.guard_message, access.guard_callback)


@pytest.fixture(autouse=True)
def fresh_denials(monkeypatch):
    monkeypatch.setattr(access, "_denials", access.DenialThrottle())


def test_allowed_user_passes():
    message, replies = fake_message("hi", user_id=2)
    assert access.guard_message(FakeClient(), message) is None
    assert replies == []


def test_stranger_gets_id_reply_once():
    for expected in ([BotText.denied.format(user_id=99)], []):
        message, replies = fake_message("hi", user_id=99)
        with pytest.raises(StopPropagation):
            access.guard_message(FakeClient(), message)
        assert replies == expected

    throttle = access.DenialThrottle()
    assert throttle.should_reply(99, 0.0)
    assert not throttle.should_reply(99, 24 * 3600 - 1)
    assert throttle.should_reply(99, 24 * 3600)


def test_owner_always_allowed(monkeypatch):
    monkeypatch.setattr(access, "OWNERS", frozenset({1}))
    monkeypatch.setattr(access, "AUTHORIZED_USERS", frozenset({2}))
    message, replies = fake_message("hi", user_id=1)
    assert access.guard_message(FakeClient(), message) is None
    assert replies == []


def test_empty_list_denies_everyone(monkeypatch):
    monkeypatch.setattr(access, "OWNERS", frozenset())
    monkeypatch.setattr(access, "AUTHORIZED_USERS", frozenset())
    message, replies = fake_message("hi", user_id=1)
    with pytest.raises(StopPropagation):
        access.guard_message(FakeClient(), message)
    assert replies == [BotText.denied.format(user_id=1)]


def test_no_sender_ignored(monkeypatch):
    # groups on, so only the missing sender can be what stops it
    monkeypatch.setattr(access, "ENABLE_GROUPS", True)
    message, replies = fake_message(
        "hi", user_id=None, chat_type=enums.ChatType.SUPERGROUP, chat_id=-100
    )
    with pytest.raises(StopPropagation):
        access.guard_message(FakeClient(), message)
    assert replies == []


def test_stranger_callback_alert():
    query, answers = fake_callback("1080p", user_id=99)
    with pytest.raises(StopPropagation):
        access.guard_callback(FakeClient(), query)
    assert answers == [(BotText.denied.format(user_id=99), {"show_alert": True})]

    query, answers = fake_callback("1080p", user_id=2)
    assert access.guard_callback(FakeClient(), query) is None
    assert answers == []


def test_group_message_ignored_when_groups_off(monkeypatch):
    monkeypatch.setattr(access, "ENABLE_GROUPS", False)
    for chat_type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        message, replies = fake_message(
            "/ytdl https://youtu.be/abc", user_id=2, chat_type=chat_type, chat_id=-100
        )
        with pytest.raises(StopPropagation):
            access.guard_message(FakeClient(), message)
        assert replies == []


def test_guard_fails_closed_when_reply_fails():
    message, _ = fake_message("hi", user_id=99)

    def broken_reply(*args, **kwargs):
        raise RuntimeError("bot was blocked by the user")

    message.reply_text = broken_reply
    with pytest.raises(StopPropagation):
        access.guard_message(FakeClient(), message)


def test_every_handler_type_has_guard():
    table = main.handler_table()
    guarded = {
        cls
        for cls, callback, handler_filters, group in table
        if group == -1 and callback in GUARD_CALLBACKS and handler_filters is None
    }
    used = {cls for cls, _callback, _filters, group in table if group >= 0}
    assert used, "no handlers at group >= 0"
    assert used <= guarded, f"handler types without a guard: {used - guarded}"

    # register_guards() adds exactly the table's group -1 entries
    added = []
    recorder = SimpleNamespace(
        add_handler=lambda handler, group: added.append(
            (type(handler), handler.callback, handler.filters, group)
        )
    )
    access.register_guards(recorder)
    assert set(added) == {entry for entry in table if entry[3] == -1}


def test_settings_saved_by_user_id():
    query, answers = fake_callback("240p", user_id=2, chat_id=555)
    main.quality_callback(FakeClient(), query)
    assert get_quality_settings(2) == "240p"
    assert get_quality_settings(555) == "1080p"  # default: nothing stored for the chat
    assert len(answers) == 1


def test_callback_regex_anchored():
    def matching(data):
        query = types.CallbackQuery(id="1", from_user=types.User(id=2), data=data)
        return [
            callback
            for cls, callback, handler_filters, group in main.handler_table()
            if cls is CallbackQueryHandler
            and group >= 0
            and asyncio.run(handler_filters(None, query))
        ]

    assert matching("x1080p") == []
    assert matching("1080px") == []
    assert matching("1080p") == [main.quality_callback]
    assert matching("sponsorblock-remove") == [main.sponsorblock_callback]
