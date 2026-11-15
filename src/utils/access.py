#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - access.py
# Modified 2026 by megabitus98 (fork): new file, one fail-closed access guard for every update, pre-checkout queries guarded too (ENABLE_VIP payments)

import logging
import threading
import time

from pyrogram import enums
from pyrogram.handlers import CallbackQueryHandler, MessageHandler, PreCheckoutQueryHandler

from config import AUTHORIZED_USERS, ENABLE_GROUPS, OWNERS, BotText

DENIAL_REPLY_INTERVAL = 24 * 3600


class DenialThrottle:
    # In memory on purpose: a restart resets it. One entry per stranger ID; fine for a private bot,
    # prune expired entries if strangers ever number in the millions.
    def __init__(self):
        self._last_reply: dict[int, float] = {}
        self._lock = threading.Lock()

    def should_reply(self, user_id: int, now: float) -> bool:
        with self._lock:
            last = self._last_reply.get(user_id)
            if last is not None and now - last < DENIAL_REPLY_INTERVAL:
                return False
            self._last_reply[user_id] = now
            return True


_denials = DenialThrottle()


def _allowed(user_id: int) -> bool:
    # owners are always allowed; with both lists empty nobody is
    return user_id in OWNERS or user_id in AUTHORIZED_USERS


# The guards run at group -1, before every other handler. Any error inside them (a failed reply,
# an odd update) still ends in stop_propagation(): the dispatcher would otherwise log the error and
# carry on to group 0. StopPropagation subclasses Exception, so it is raised outside the try.


def guard_message(client, message) -> None:
    try:
        user = message.from_user  # None for channel posts and anonymous admins
        private = message.chat.type == enums.ChatType.PRIVATE
        if user is not None and (private or ENABLE_GROUPS) and _allowed(user.id):
            return None
        if user is not None and private and _denials.should_reply(user.id, time.time()):
            message.reply_text(BotText.denied.format(user_id=user.id))
    except Exception:
        logging.exception("Access guard error, message dropped")
    message.stop_propagation()


def guard_callback(client, callback_query) -> None:
    try:
        user = callback_query.from_user
        if user is not None and _allowed(user.id):
            return None
        if user is not None:
            callback_query.answer(
                BotText.denied.format(user_id=user.id), show_alert=True
            )
    except Exception:
        logging.exception("Access guard error, callback dropped")
    callback_query.stop_propagation()


def guard_pre_checkout(client, query) -> None:
    # payments (ENABLE_VIP): an invoice can reach someone else, so the payer is checked too
    try:
        user = query.from_user
        if user is not None and _allowed(user.id):
            return None
        if user is not None:
            query.answer(ok=False, error_message=BotText.denied.format(user_id=user.id))
    except Exception:
        logging.exception("Access guard error, pre-checkout query dropped")
    query.stop_propagation()


# filters=None: a guard must see every update of its type
GUARDS = [
    (MessageHandler, guard_message, None, -1),
    (CallbackQueryHandler, guard_callback, None, -1),
    (PreCheckoutQueryHandler, guard_pre_checkout, None, -1),
]


def register_guards(app) -> None:
    for handler_cls, callback, handler_filters, group in GUARDS:
        app.add_handler(handler_cls(callback, handler_filters), group)
