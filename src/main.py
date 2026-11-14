#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - new.py
# 8/14/21 14:37
#
# Modified 2026 by megabitus98 (fork): handler_table()/create_app() instead of a module-level client, --self-check, no quote= (kurigram 2.2.27)

__author__ = "Benny <benny.think@gmail.com>"

import functools
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
    # ponytail: runs before the app imports below, so it needs no bot config, database or Telegram client
    import json

    from selfcheck import run_selfcheck

    selfcheck_result = run_selfcheck()
    print(json.dumps(selfcheck_result))
    sys.exit(0 if selfcheck_result["ok"] else 1)

import psutil
import pyrogram.errors
import yt_dlp
from pyrogram import Client, enums, filters, types
from pyrogram.filters import Filter
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

from config import (
    APP_HASH,
    APP_ID,
    AUTHORIZED_USER,
    BOT_TOKEN,
    M3U8_SUPPORT,
    OWNER,
    TMPFILE_PATH,
    WORKERS,
    BotText,
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
from utils import extract_url_and_name, sizeof_fmt, timeof_fmt

localize_filetype=dict(document="Файл", video="Видео", audio="Аудио")
localize_vcodec={"vcodec-auto": "АВТО", "vcodec-vp9": "VP9 (рекомендовано)", "vcodec-av01": "AV1 (самый сжатый, но требовательный)" ,"vcodec-avc1": "AVC1 (H.264)"}
localize_sponsorblock = {"disabled": "Не вырезать рекламу", "remove": "Вырезать рекламу"}

logging.info("Authorized users are %s", AUTHORIZED_USER)


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
        title = entry.get("title", "Нет названия")
        url = entry.get("url") or entry.get("webpage_url", "Нет ссылки")
        lines.append(f"<b>{index}. {title}</b>\n{url}")

    if not lines:
        return "🔎 Ничего не нашёл по этому запросу."
    return "\n\n".join(lines)


def private_use(func):
    @functools.wraps(func)
    def wrapper(client: Client, message: types.Message):
        chat_id = getattr(message.from_user, "id", None)

        # message type check
        if message.chat.type != enums.ChatType.PRIVATE and not getattr(message, "text", "").lower().startswith("/ytdl"):
            logging.debug("%s, it's annoying me...🙄️ ", message.text)
            return

        # authorized users check
        if AUTHORIZED_USER:
            users = [int(i) for i in AUTHORIZED_USER.split(",")]
        else:
            users = []

        if users and chat_id and chat_id not in users:
            message.reply_text(BotText.private)
            return

        return func(client, message)

    return wrapper


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
    client.send_message(chat_id, BotText.about)


def ping_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)

    def send_message_and_measure_ping():
        start_time = int(round(time.time() * 1000))
        reply: types.Message | typing.Any = client.send_message(chat_id, "Пинг...")

        end_time = int(round(time.time() * 1000))
        ping_time = int(round(end_time - start_time))
        message_sent = True
        if message_sent:
            message.reply_text(f"Ping: {ping_time:.2f} ms")
        time.sleep(0.5)
        client.edit_message_text(chat_id=reply.chat.id, message_id=reply.id, text="Понг!")
        time.sleep(1)
        client.delete_messages(chat_id=reply.chat.id, message_ids=reply.id)

    thread = threading.Thread(target=send_message_and_measure_ping)
    thread.start()


def stats_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    cpu_usage = psutil.cpu_percent()
    total, used, free, disk = psutil.disk_usage("/")
    swap = psutil.swap_memory()
    memory = psutil.virtual_memory()
    boot_time = psutil.boot_time()

    stats = (
        "\n\n⌬─────「 Статистика 」─────⌬\n\n"
        f"<b>╭🖥️ **Использование ЦП »**</b>  __{cpu_usage}%__\n"
        f"<b>├💾 **RAM »**</b>  __{memory.percent}%__\n"
        f"<b>╰🗃️ **Использование диска »**</b>  __{disk}%__\n\n"
        f"<b>╭📤Выгрузка:</b> {sizeof_fmt(psutil.net_io_counters().bytes_sent)}\n"
        f"<b>╰📥Загрузка:</b> {sizeof_fmt(psutil.net_io_counters().bytes_recv)}\n\n\n"
        f"<b>Общая память:</b> {sizeof_fmt(memory.total)}\n"
        f"<b>Свободная память:</b> {sizeof_fmt(memory.available)}\n"
        f"<b>Используемая память:</b> {sizeof_fmt(memory.used)}\n"
        f"<b>Размер подкачки:</b> {sizeof_fmt(swap.total)} | <b>Используемая подкачка:</b> {swap.percent}%\n\n"
        f"<b>Физическая память:</b> {sizeof_fmt(total)}\n"
        f"<b>Используется:</b> {sizeof_fmt(used)} | <b>Свободно:</b> {sizeof_fmt(free)}\n\n"
        f"<b>Количество физических ЦП ядер:</b> {psutil.cpu_count(logical=False)}\n"
        f"<b>Общее количество ЦП ядер:</b> {psutil.cpu_count(logical=True)}\n\n"
        f"<b>🤖Время работы бота:</b> {timeof_fmt(time.time() - botStartTime)}\n"
        f"<b>⏲️Время работы системы:</b> {timeof_fmt(time.time() - boot_time)}\n"
    )

    message.reply_text(stats)


def settings_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    markup = types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton("Отправлять файл", callback_data="document"),
                types.InlineKeyboardButton("Отправлять видео", callback_data="video"),
                types.InlineKeyboardButton("Отправлять аудио", callback_data="audio"),
            ],
            [
                types.InlineKeyboardButton(
                    "Кодек AVC1 (H.264)", callback_data="vcodec-avc1"
                ),
                types.InlineKeyboardButton("Кодек VP9 (рекомендуется)", callback_data="vcodec-vp9"),
                types.InlineKeyboardButton(
                    "Кодек АВТО", callback_data="vcodec-auto"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    "Кодек AV1 (сжатый, требовательный к ресурсам)", callback_data="vcodec-av01"
                ),
            ],
            [
                types.InlineKeyboardButton("Не вырезать рекламу", callback_data="sponsorblock-disabled"),
                types.InlineKeyboardButton("Вырезать рекламу", callback_data="sponsorblock-remove"),
            ],
            [
                types.InlineKeyboardButton("Качество 1440p", callback_data="1440p"),
                types.InlineKeyboardButton("Качество 1080p", callback_data="1080p"),
                types.InlineKeyboardButton("Качество 720p", callback_data="720p"),
            ],
            [
                types.InlineKeyboardButton("Качество 480p", callback_data="480p"),
                types.InlineKeyboardButton("Качество 240p", callback_data="240p"),
            ],
        ]
    )

    quality = get_quality_settings(chat_id)
    send_type = get_format_settings(chat_id)
    vcodec = get_vcodec_settings(chat_id)
    sponsorblock = get_sponsorblock_settings(chat_id)

    localize_send_type = localize_filetype.get(send_type, send_type)
    localize_vcodec_local = localize_vcodec.get(vcodec, vcodec)
    localized_sb = localize_sponsorblock.get(sponsorblock, sponsorblock)

    client.send_message(
        chat_id,
        BotText.settings.format(quality, localize_send_type, localize_vcodec_local, localized_sb),
        reply_markup=markup,
    )


def direct_download(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("Direct download using aria2/requests start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("Укажи корректную ссылку!")
        return
    bot_msg = message.reply_text("Запрос принят, обрабатываю...")
    try:
        direct_entrance(client, bot_msg, url)
    except ValueError as e:
        message.reply_text(e.__str__())
        bot_msg.delete()
        return


def spdl_handler(client: Client, message: types.Message):
    chat_id = message.chat.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("spdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("Произошла какая-то ошибка, проверьте URL.")
        return
    bot_msg = message.reply_text("Запрос принят, обрабатываю....")
    try:
        special_download_entrance(client, bot_msg, url)
    except ValueError as e:
        message.reply_text(e.__str__())
        bot_msg.delete()
        return


def ytdl_handler(client: Client, message: types.Message):
    # for group only
    init_user(message.from_user.id)
    client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
    message_text = message.text
    url, new_name = extract_url_and_name(message_text)
    logging.info("ytdl start %s", url)
    if url is None or not re.findall(r"^https?://", url.lower()):
        message.reply_text("Check your URL.")
        return

    bot_msg = message.reply_text("Group download request received.")
    try:
        youtube_entrance(client, bot_msg, url)
    except ValueError as e:
        message.reply_text(e.__str__())
        bot_msg.delete()
        return


def check_link(url: str):
    ytdl = yt_dlp.YoutubeDL()
    if re.findall(r"^https://www\.youtube\.com/channel/", url) or "list" in url:
        # TODO maybe using ytdl.extract_info
        raise ValueError("📛 Загрузка плейлистов отключена!")

    if not M3U8_SUPPORT and (re.findall(r"m3u8|\.m3u8|\.m3u$", url.lower())):
        return "m3u8 links are disabled."


@private_use
def download_handler(client: Client, message: types.Message):
    chat_id = message.from_user.id
    init_user(chat_id)
    client.send_chat_action(chat_id, enums.ChatAction.TYPING)
    url = message.text
    logging.info("start %s", url)

    try:
        # No URL -> treat the text as a YouTube search query
        if not re.findall(r"^https?://", url.lower()):
            reply = message.reply_text("🔎 Ищу ролики на YouTube...")
            text = search_ytb(url)
            client.edit_message_text(
                chat_id=reply.chat.id,
                message_id=reply.id,
                text=text,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
            return

        check_link(url)
        bot_msg: types.Message | Any = message.reply_text(
            "▶️ Загружаю...\nМогут наблюдаться проблемы с AV1 кодеком."
        )
        client.send_chat_action(chat_id, enums.ChatAction.UPLOAD_VIDEO)
        youtube_entrance(client, bot_msg, url)
    except pyrogram.errors.Flood as e:
        f = BytesIO()
        f.write(str(e).encode())
        f.write(b"Your job will be done soon. Just wait!")
        f.name = "Please wait.txt"
        message.reply_document(f, caption=f"Пожалуйста, подожди {e} секунд...")
        f.close()
        client.send_message(OWNER, f"Пожалуйста, подожди {e} секунд...")
        time.sleep(e.value)
    except ValueError as e:
        message.reply_text(e.__str__())
    except Exception as e:
        logging.error("Download failed", exc_info=True)
        message.reply_text(f"❌ Произошла ошибка!: {e}")


def format_callback(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    logging.info("Setting %s file type to %s", chat_id, data)
    callback_query.answer(
        f"Вы установили тип отправки: {localize_filetype.get(callback_query.data, callback_query.data)}"
    )
    set_user_settings(chat_id, "format", data)


def quality_callback(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    logging.info("Setting %s download quality to %s", chat_id, data)
    callback_query.answer(f"Вы установили качество видео: {callback_query.data}")
    set_user_settings(chat_id, "quality", data)


def vcodec_callback(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data
    logging.info("Setting %s download vcodec to %s", chat_id, data)
    callback_query.answer(f"Вы установили кодек: {localize_vcodec.get(callback_query.data, callback_query.data)}")
    set_user_settings(chat_id, "vcodec", data)


def sponsorblock_callback(client: Client, callback_query: types.CallbackQuery):
    chat_id = callback_query.message.chat.id
    data = callback_query.data.replace('sponsorblock-', '')
    logging.info("Setting %s sponsorblock to %s", chat_id, data)
    callback_query.answer(f"SponsorBlock: {localize_sponsorblock.get(data, data)}")
    set_user_settings(chat_id, "sponsorblock", data)


HandlerSpec = tuple[type, Callable, Filter | None, int]


def handler_table() -> list[HandlerSpec]:
    # Order matters: within a group the first matching handler wins, so the catch-all text handler
    # must stay after the commands.
    return [
        (MessageHandler, start_handler, filters.command(["start"]), 0),
        (MessageHandler, help_handler, filters.command(["help"]), 0),
        (MessageHandler, about_handler, filters.command(["about"]), 0),
        (MessageHandler, ping_handler, filters.command(["ping"]), 0),
        (MessageHandler, stats_handler, filters.command(["stats"]), 0),
        (MessageHandler, settings_handler, filters.command(["settings"]), 0),
        (MessageHandler, direct_download, filters.command(["direct"]), 0),
        (MessageHandler, spdl_handler, filters.command(["spdl"]), 0),
        (MessageHandler, ytdl_handler, filters.command(["ytdl"]) & filters.group, 0),
        (MessageHandler, download_handler, filters.incoming & filters.text, 0),
        (CallbackQueryHandler, format_callback, filters.regex(r"document|video|audio"), 0),
        (CallbackQueryHandler, quality_callback, filters.regex(r"1440p|1080p|720p|480p|240p"), 0),
        (CallbackQueryHandler, vcodec_callback, filters.regex(r"vcodec-vp9|vcodec-avc1|vcodec-av01|vcodec-auto"), 0),
        (CallbackQueryHandler, sponsorblock_callback, filters.regex(r"sponsorblock-disabled|sponsorblock-remove"), 0),
    ]


def create_app() -> Client:
    app = Client("main", APP_ID, APP_HASH, bot_token=BOT_TOKEN, workers=WORKERS)
    for handler_cls, callback, handler_filters, group in handler_table():
        app.add_handler(handler_cls(callback, handler_filters), group)
    return app


if __name__ == "__main__":
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

    botStartTime = time.time()
    banner = """
▌ ▌         ▀▛▘     ▌       ▛▀▖              ▜            ▌
▝▞  ▞▀▖ ▌ ▌  ▌  ▌ ▌ ▛▀▖ ▞▀▖ ▌ ▌ ▞▀▖ ▌  ▌ ▛▀▖ ▐  ▞▀▖ ▝▀▖ ▞▀▌
 ▌  ▌ ▌ ▌ ▌  ▌  ▌ ▌ ▌ ▌ ▛▀  ▌ ▌ ▌ ▌ ▐▐▐  ▌ ▌ ▐  ▌ ▌ ▞▀▌ ▌ ▌
 ▘  ▝▀  ▝▀▘  ▘  ▝▀▘ ▀▀  ▝▀▘ ▀▀  ▝▀   ▘▘  ▘ ▘  ▘ ▝▀  ▝▀▘ ▝▀▘

By @BennyThink
    """
    print(banner)
    create_app().run()
