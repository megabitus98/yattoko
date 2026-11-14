# Fake Telegram objects for handler tests: no client, no network.

from types import SimpleNamespace

import pyrogram
from pyrogram import enums


class FakeClient:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def stop_propagation():
    raise pyrogram.StopPropagation


def fake_message(text, user_id=2, chat_type=enums.ChatType.PRIVATE, chat_id=None):
    # user_id=None is a message without a sender (channel post, anonymous admin)
    replies = []
    message = SimpleNamespace(
        text=text,
        from_user=None if user_id is None else SimpleNamespace(id=user_id),
        chat=SimpleNamespace(
            id=user_id if chat_id is None else chat_id, type=chat_type
        ),
        # returns the sent message, on which every method (delete, edit_text) is a no-op
        reply_text=lambda reply, **kwargs: replies.append(reply) or FakeClient(),
        stop_propagation=stop_propagation,
    )
    return message, replies


def fake_callback(data, user_id=2, chat_id=None):
    answers = []
    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=user_id if chat_id is None else chat_id)
        ),
        answer=lambda text=None, **kwargs: answers.append((text, kwargs)),
        stop_propagation=stop_propagation,
    )
    return query, answers


def fake_downloader(url, user_id=2, chat_id=None, chat_type=enums.ChatType.PRIVATE):
    # A YoutubeDownload whose progress message records its edits; in a group it replies to the requester's message.
    from engine.generic import YoutubeDownload

    edits = []
    bot_msg = SimpleNamespace(
        id=10,
        chat=SimpleNamespace(
            id=user_id if chat_id is None else chat_id, type=chat_type
        ),
        reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=user_id)),
        edit_text=lambda text, **kwargs: edits.append(text),
    )
    return YoutubeDownload(FakeClient(), bot_msg, url), edits
