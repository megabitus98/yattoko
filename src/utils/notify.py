#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - notify.py
# Modified 2026 by megabitus98 (fork): new file, owner notices (at most one per site and kind a day, each owner messaged separately, redacted), announce_version after an update

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from pyrogram import enums, types

from config import BotText
from database.model import claim_notice, get_state, set_state
from utils.redact import redact

DETAILS_LIMIT = 300


def send_to_owners(client, owners: Iterable[int], text: str) -> int:
    # One send per owner: an owner who never sent /start (or blocked the bot) must not stop the others.
    # Error text goes out as plain text, so stray markup in it cannot break or reshape the message.
    sent = 0
    for owner_id in sorted(owners):
        try:
            client.send_message(
                owner_id,
                text,
                parse_mode=enums.ParseMode.DISABLED,
                link_preview_options=types.LinkPreviewOptions(is_disabled=True),
            )
            sent += 1
        except Exception:
            logging.exception("Could not message an owner")
    return sent


def notify_owners(
    client,
    owners: frozenset[int],
    site: str,
    kind: str,
    details: str,
    *,
    cookies: bool = False,
    exits: Iterable[str] = (),
) -> int:
    # Returns how many owners got the notice; 0 when one already went out for (site, kind) in the last 24 h.
    try:
        if not claim_notice(site, kind, datetime.now(timezone.utc)):
            return 0
    except Exception:
        # the caller is replying to a user; a broken database must not cost them that reply
        logging.exception("Could not record the owner notice")
        return 0
    logging.warning("Telling the owners: %s on %s", kind, site)
    text = BotText.owner_notice.format(
        kind=kind,
        site=site,
        cookies="yes" if cookies else "no",
        exits=", ".join(dict.fromkeys(exits)) or "none",
        # redacted before the cut, which could split user:pass@ where the pattern no longer finds it
        details=redact(details)[:DETAILS_LIMIT],
    )
    # once more as a whole: the exits may be proxy URLs
    return send_to_owners(client, owners, redact(text))


def announce_version(
    client, owners: Iterable[int], version: str, title: str, url: str
) -> int:
    # Once per new version, at startup. The first start stores the version silently, a local build ("dev")
    # never announces, and the version is stored before sending, so a crash loop cannot repeat the message.
    # Never raises: a failure here must not stop the bot from starting.
    try:
        if version == "dev":
            return 0
        previous = get_state("announced_version")
        if previous == version:
            return 0
        set_state("announced_version", version)
        if previous is None:
            return 0
        text = BotText.owner_updated.format(
            version=version, previous=previous, title=title, url=url
        )
        return send_to_owners(client, owners, text.strip())
    except Exception:
        logging.exception("Could not announce the version")
        return 0
