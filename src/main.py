#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - new.py
# 8/14/21 14:37
#
# Modified 2026 by megabitus98 (fork): handler_table()/create_app() instead of a module-level client, --self-check, no quote= (kurigram 2.2.27), env feature switches, access guard at group -1, first URL in the message, anchored settings callbacks saved by user ID, session in DATA_DIR, refuse TMPFILE_PATH overlapping DATA_DIR, BotText.error instead of exception text in replies, English texts from config.constant, download failures replied per kind (engine.errors), /about without link preview, every settings button labelled from BotText.buttons, no URL-based playlist check (engine.generic.attempt refuses playlists after extraction), downloads handed to a JobQueue of MAX_PARALLEL_JOBS with queue positions, heartbeat for the probes, /stats uptime from create_app()

__author__ = "Benny <benny.think@gmail.com>"

import logging
import os
import re
import shutil
import sys
import threading
import time
import typing
from collections.abc import Callable
from io import BytesIO
from typing import Any

if __name__ == "__main__" and "--self-check" in sys.argv[1:]:
    # runs before the app imports below, so it needs no bot config, database or Telegram client
    import json

    from selfcheck import run_selfcheck

    selfcheck_result = run_selfcheck()
    print(json.dumps(selfcheck_result))
    sys.exit(0 if selfcheck_result["ok"] else 1)

import psutil
import pyrogram.errors
import yt_dlp
from pyrogram import Client, enums, filters, idle, types
from pyrogram.filters import Filter
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.utils import loops

from config import (
    APP_HASH,
    APP_ID,
    BOT_TOKEN,
    DATA_DIR,
    ENABLE_DIRECT,
    ENABLE_GROUPS,
    ENABLE_SEARCH,
    ENABLE_SPDL,
    ENABLE_STATS,
    M3U8_SUPPORT,
    MAX_PARALLEL_JOBS,
    OWNERS,
    TMPFILE_PATH,
    WORKERS,
    BotText,
    check_paths,
)
from database.model import (
    get_format_settings,
    get_quality_settings,
    get_sponsorblock_settings,
    get_vcodec_settings,
    init_user,
    set_user_settings,
)
from engine import direct_entrance, youtube_entrance, special_download_entrance
from engine.base import QUALITIES
from engine.errors import classify, site_name, user_message
from engine.jobs import JobQueue
from health import HEALTH_FILE, start_heartbeat
from utils import extract_first_url, extract_url_and_name, sizeof_fmt, timeof_fmt
from utils.access import GUARDS

# Every download runs here; handlers hand the job over and return, so queued jobs hold no kurigram worker.
JOBS = JobQueue(MAX_PARALLEL_JOBS)
# for the /stats uptime; create_app() sets it again
started_at = time.time()

def search_ytb(kw: str, num_results: int = 10) -> str:
    # Single flat search query — no per-result extract_info (avoids N+1 latency)
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        search_result = ydl.extract_info(f"ytsearch{num_results}:{kw}", download=False)

    entries = (search_result or {}).get("entries") or []
    lines = []
    for index, entry in enumerate((e for e in entries if e), start=1):
        title = entry.get("title", BotText.search_no_title)
        url = entry.get("url") or entry.get("webpage_url", BotText.search_no_link)
        lines.append(f"<b>{index}. {title}</b>\n{url}")

    if not lines:
        return BotText.search_empty
    return "\n\n".join(lines)


def start_handler(client: Client, message: types.Message):
    from_id = message.chat.id
    init_user(from_id)
    logging.info("%s welcome to youtube-dl bot!", message.from_user.id)
    client.send_chat_action(from_id, enums.ChatAction.TYPING)
    client.send_message(
        from_id,
        BotText.start,
        disable_web_page_preview=True,
    )


def help_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    client.send_message(chat_id, BotText.help, disable_web_page_preview=True)


def about_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    client.send_message(chat_id, BotText.about, disable_web_page_preview=True)


def ping_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    def send_message_and_measure_ping():
        start_time = int(round(time.time() * 1000))
        reply: types.Message | typing.Any = client.send_message(chat_id, BotText.ping)

        end_time = int(round(time.time() * 1000))
        ping_time = int(round(end_time - start_time))
        message_sent = True
        if message_sent:
            message.reply_text(BotText.ping_result.format(ping_time))
        time.sleep(0.5)
        client.edit_message_text(chat_id=reply.chat.id, message_id=reply.id, text=BotText.pong)
        time.sleep(1)
        client.delete_messages(chat_id=reply.chat.id, message_ids=reply.id)

    thread = threading.Thread(target=send_message_and_measure_ping)
    thread.start()


def stats_handler(client: Client, message: types.Message):
    if not ENABLE_STATS or getattr(message.from_user, "id", None) not in OWNERS:
        message.reply_text(BotText.disabled)
        return
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    cpu_usage = psutil.cpu_percent()
    total, used, free, disk = psutil.disk_usage("/")
    swap = psutil.swap_memory()
    memory = psutil.virtual_memory()
    boot_time = psutil.boot_time()

    stats = BotText.stats.format(
        cpu=cpu_usage,
        ram=memory.percent,
        disk=disk,
        sent=sizeof_fmt(psutil.net_io_counters().bytes_sent),
        received=sizeof_fmt(psutil.net_io_counters().bytes_recv),
        memory_total=sizeof_fmt(memory.total),
        memory_free=sizeof_fmt(memory.available),
        memory_used=sizeof_fmt(memory.used),
        swap_total=sizeof_fmt(swap.total),
        swap_percent=swap.percent,
        disk_total=sizeof_fmt(total),
        disk_used=sizeof_fmt(used),
        disk_free=sizeof_fmt(free),
        physical_cores=psutil.cpu_count(logical=False),
        total_cores=psutil.cpu_count(logical=True),
        bot_uptime=timeof_fmt(time.time() - started_at),
        os_uptime=timeof_fmt(time.time() - boot_time),
    )

    message.reply_text(stats)


def settings_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    init_user(user_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    rows = [
        ["document", "video", "audio"],
        ["vcodec-auto", "vcodec-avc1", "vcodec-vp9"],
        ["vcodec-av01"],
        ["sponsorblock-disabled", "sponsorblock-remove"],
        ["1440p", "1080p", "720p"],
        ["480p", "240p"],
    ]
    markup = types.InlineKeyboardMarkup(
        [
            [types.InlineKeyboardButton(BotText.buttons[data], callback_data=data) for data in row]
            for row in rows
        ]
    )

    quality = get_quality_settings(user_id)
    send_type = get_format_settings(user_id)
    vcodec = get_vcodec_settings(user_id)
    sponsorblock = get_sponsorblock_settings(user_id)

    names = BotText.names
    client.send_message(
        chat_id,
        BotText.settings.format(
            quality,
            names.get(send_type, send_type),
            names.get(vcodec, vcodec),
            names.get(sponsorblock, sponsorblock),
        ),
        reply_markup=markup,
    )


def direct_download(client: Client, message: types.Message):
    if not ENABLE_DIRECT:
        message.reply_text(BotText.disabled)
        return
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("Direct download using aria2/requests start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text(BotText.bad_link)
        return
    submit_download(client, message, url, direct_entrance)


def spdl_handler(client: Client, message: types.Message):
    if not ENABLE_SPDL:
        message.reply_text(BotText.disabled)
        return
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("spdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text(BotText.bad_link)
        return
    submit_download(client, message, url, special_download_entrance)


def ytdl_handler(client: Client, message: types.Message):
    # for group only; with groups off it stays silent
    if not ENABLE_GROUPS:
        return
    init_user(message.from_user.id)
    client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("ytdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text(BotText.bad_link)
        return
    if m3u8_blocked(url):
        message.reply_text(BotText.disabled)
        return
    submit_download(client, message, url, youtube_entrance)


def submit_download(
    client: Client,
    message: types.Message,
    url: str,
    entrance: Callable[[Client, Any, str], Any],
    first_text: str = BotText.received,
) -> None:
    # The progress message is sent now; the download runs in JOBS. Errors are replied from inside the job,
    # since the handler has returned by then.
    bot_msg = message.reply_text(first_text)

    def job():
        try:
            entrance(client, bot_msg, url)
        except pyrogram.errors.Flood as e:
            flood_wait(client, message, e)
        except Exception as e:
            reply_error(message, url, e)
            bot_msg.delete()

    if position := JOBS.submit(job):
        bot_msg.edit_text(BotText.queued.format(n=position))


def flood_wait(client: Client, message: types.Message, e: pyrogram.errors.Flood) -> None:
    f = BytesIO()
    f.write(BotText.flood_file.encode())
    f.name = BotText.flood_file_name
    message.reply_document(f, caption=BotText.flood_wait.format(e.value))
    f.close()
    for owner_id in OWNERS:
        client.send_message(owner_id, BotText.flood_wait.format(e.value))
    time.sleep(e.value)


def reply_error(message: types.Message, url: str | None, err: BaseException) -> None:
    # for failures outside BaseDownloader.start(), which replies by itself
    # the traceback goes to the (redacted) log, never to the user
    logging.error("Download failed for %s", url, exc_info=err)
    message.reply_text(user_message(classify(err), site_name(url)))


def m3u8_blocked(url: str) -> bool:
    return not M3U8_SUPPORT and bool(re.search(r"m3u8|\.m3u$", url.lower()))


def download_handler(client: Client, message: types.Message):
    chat_id = message.from_user.id
    url = extract_first_url(message.text)
    if url is None and not ENABLE_SEARCH:
        message.reply_text(BotText.no_link)
        return
    if url is not None and m3u8_blocked(url):
        message.reply_text(BotText.disabled)
        return
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    logging.info("start %s", url or message.text)

    try:
        # No URL -> treat the text as a YouTube search query
        if url is None:
            reply = message.reply_text(BotText.searching)
            text = search_ytb(message.text)
            client.edit_message_text(
                chat_id=reply.chat.id,
                message_id=reply.id,
                text=text,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
            return

        submit_download(client, message, url, youtube_entrance, BotText.downloading)
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_VIDEO)
    except pyrogram.errors.Flood as e:
        flood_wait(client, message, e)
    except Exception as e:
        reply_error(message, url, e)


# Callback data -> stored setting value. The handler regexes are built from these keys and anchored,
# so only exact button data matches; anything else never reaches the database.
FORMAT_CHOICES = {"document": "document", "video": "video", "audio": "audio"}
QUALITY_CHOICES = {q: q for q in QUALITIES}
VCODEC_CHOICES = {v: v for v in ("vcodec-auto", "vcodec-vp9", "vcodec-avc1", "vcodec-av01")}
SPONSORBLOCK_CHOICES = {"sponsorblock-disabled": "disabled", "sponsorblock-remove": "remove"}


def choice_filter(choices: dict[str, str]) -> Filter:
    return filters.regex("^(" + "|".join(map(re.escape, choices)) + ")$")


def save_setting(callback_query: types.CallbackQuery, key: str, choices: dict[str, str]) -> str:
    # saved for the person who pressed the button, not for the chat the button is in
    user_id = callback_query.from_user.id
    value = choices[callback_query.data]
    init_user(user_id)
    set_user_settings(user_id, key, value)
    logging.info("Setting %s %s to %s", user_id, key, value)
    return value


def format_callback(client: Client, callback_query: types.CallbackQuery):
    value = save_setting(callback_query, "format", FORMAT_CHOICES)
    callback_query.answer(BotText.saved["format"].format(BotText.names.get(value, value)))


def quality_callback(client: Client, callback_query: types.CallbackQuery):
    value = save_setting(callback_query, "quality", QUALITY_CHOICES)
    callback_query.answer(BotText.saved["quality"].format(value))


def vcodec_callback(client: Client, callback_query: types.CallbackQuery):
    value = save_setting(callback_query, "vcodec", VCODEC_CHOICES)
    callback_query.answer(BotText.saved["vcodec"].format(BotText.names.get(value, value)))


def sponsorblock_callback(client: Client, callback_query: types.CallbackQuery):
    value = save_setting(callback_query, "sponsorblock", SPONSORBLOCK_CHOICES)
    callback_query.answer(BotText.saved["sponsorblock"].format(BotText.names.get(value, value)))


HandlerSpec = tuple[type, Callable, Filter | None, int]


def handler_table() -> list[HandlerSpec]:
    # Order matters: within a group the first matching handler wins, so the catch-all text handler
    # must stay after the commands. The access guards run first, at group -1.
    return [
        *GUARDS,
        (MessageHandler, start_handler, filters.command(["start"]), 0),
        (MessageHandler, help_handler, filters.command(["help"]), 0),
        (MessageHandler, about_handler, filters.command(["about"]), 0),
        (MessageHandler, ping_handler, filters.command(["ping"]), 0),
        (MessageHandler, stats_handler, filters.command(["stats"]), 0),
        (MessageHandler, settings_handler, filters.command(["settings"]), 0),
        (MessageHandler, direct_download, filters.command(["direct"]), 0),
        (MessageHandler, spdl_handler, filters.command(["spdl"]), 0),
        (MessageHandler, ytdl_handler, filters.command(["ytdl"]) & filters.group, 0),
        (MessageHandler, download_handler, filters.private & filters.incoming & filters.text, 0),
        (CallbackQueryHandler, format_callback, choice_filter(FORMAT_CHOICES), 0),
        (CallbackQueryHandler, quality_callback, choice_filter(QUALITY_CHOICES), 0),
        (CallbackQueryHandler, vcodec_callback, choice_filter(VCODEC_CHOICES), 0),
        (CallbackQueryHandler, sponsorblock_callback, choice_filter(SPONSORBLOCK_CHOICES), 0),
    ]


def create_app() -> Client:
    global started_at
    started_at = time.time()
    # the session file lives on the data volume next to the database, not in the image
    app = Client("main", APP_ID, APP_HASH, bot_token=BOT_TOKEN, workers=WORKERS, workdir=DATA_DIR)
    for handler_cls, callback, handler_filters, group in handler_table():
        app.add_handler(handler_cls(callback, handler_filters), group)
    return app


async def serve(app: Client) -> None:
    # Client.run(), with the heartbeat started once the client is up: get_me needs a started client
    await app.start()
    start_heartbeat(app)
    await idle()
    await app.stop()


if __name__ == "__main__":
    check_paths(DATA_DIR, TMPFILE_PATH)  # before the purge below empties TMPFILE_PATH
    # Clean up stale temp directories from previous runs
    if os.path.exists(TMPFILE_PATH):
        for item in os.listdir(TMPFILE_PATH):
            item_path = os.path.join(TMPFILE_PATH, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                logging.error(f"Failed to remove {item_path}: {e}")
    os.makedirs(TMPFILE_PATH, exist_ok=True)
    logging.info(f"Temp directory set to {TMPFILE_PATH}")
    # a container restart keeps /tmp; the probe must wait for this run's first heartbeat
    HEALTH_FILE.unlink(missing_ok=True)

    banner = """
▌ ▌         ▀▛▘     ▌       ▛▀▖              ▜            ▌
▝▞  ▞▀▖ ▌ ▌  ▌  ▌ ▌ ▛▀▖ ▞▀▖ ▌ ▌ ▞▀▖ ▌  ▌ ▛▀▖ ▐  ▞▀▖ ▝▀▖ ▞▀▌
 ▌  ▌ ▌ ▌ ▌  ▌  ▌ ▌ ▌ ▌ ▛▀  ▌ ▌ ▌ ▌ ▐▐▐  ▌ ▌ ▐  ▌ ▌ ▞▀▌ ▌ ▌
 ▘  ▝▀  ▝▀▘  ▘  ▝▀▘ ▀▀  ▝▀▘ ▀▀  ▝▀   ▘▘  ▘ ▘  ▘ ▝▀  ▝▀▘ ▝▀▘

By @BennyThink
    """
    print(banner)
    # same event loop as Client.run() (uvloop with kurigram[fast])
    loops.run(serve(create_app()))
    JOBS.shutdown(wait=False)
