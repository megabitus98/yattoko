#!/usr/local/bin/python3
# coding: utf-8

# ytdlbot - constant.py
# 8/16/21 16:59
#
# Modified 2026 by megabitus98 (fork): BotText.disabled for switched-off features, BotText.denied and BotText.no_link, generic BotText.error, English texts for every user-facing string, /about credits both upstream repositories, per-kind download error texts, quality button labels, flood-wait file name, BotText.refused, BotText.queued and BotText.too_large, owner notice texts, upstream's quota and payment texts (ENABLE_VIP)

__author__ = "Benny <benny.think@gmail.com>"

import typing

from pyrogram import Client, types


class BotText:

    start = "Hi! Send me a link to a video and I send the video back. See /help for details."

    disabled = "This feature is turned off."

    denied = "You don't have access to this bot. Your Telegram ID is {user_id}. Send it to the owner to get access."

    no_link = "Send me a link to a video."

    error = "Something went wrong with this download."

    # download failures by kind (engine/errors.py); {site} is the display name, e.g. "Instagram"
    login_required = "{site} needs a login for this video. The owner has been told."

    blocked = "{site} is blocking downloads right now. The owner has been told. Try again later."

    unavailable = "This video is private, deleted or not available here."

    refused = "Send a link to a single video, not a playlist, channel or live stream."

    too_large = "This video is too large for Telegram (over 2 GB)."

    queued = "Queued, position {n}."

    # quota and payments, only with ENABLE_VIP (upstream's texts)
    quota = "\n\nYou have {free} free and {paid} paid quota."

    quota_exhausted = "Quota exhausted. Please /buy or wait until free quota is reset."

    buy = "Please choose the amount you want to buy."

    invoice_title = "{} permanent download quota"

    invoice_description = "Please make a payment via Stripe"

    invoice_label = "VIP"

    payment_done = "Payment successful! You now have {free} free and {paid} paid quota."

    payment_failed = "Something went wrong. Please contact the admin."

    bad_link = "Check the link and send it again."

    received = "Request received, working on it..."

    downloading = "▶️ Downloading..."
    converting = "🔄 Converting the video so it plays on every device..."

    uploading = "📤 Uploading..."

    done = "✅ Success"

    speed = "Speed:"

    eta = "ETA:"

    caption = "{url}\n{filename}\n\nResolution: {width}x{height}\nDuration: {duration} seconds"

    aria2_start = "Aria2 download starting..."

    krakenfiles_start = "Processing krakenfiles download link..."

    searching = "🔎 Searching YouTube..."

    search_empty = "🔎 Nothing found for this search."

    search_no_title = "No title"

    search_no_link = "No link"

    ping = "Pinging..."

    ping_result = "Ping: {:.2f} ms"

    pong = "Pong!"

    flood_wait = "Telegram asked me to slow down. Please wait {} seconds..."

    flood_file = "Your job will be done soon. Just wait!"

    flood_file_name = "Please wait.txt"

    # to the owners (utils/notify.py); {details} is a redacted error excerpt
    owner_notice = "[ytdlbot] {kind} on {site}\ncookies: {cookies}\nexits tried: {exits}\n{details}"

    owner_cookies_expired = "yt-dlp dropped sessionid: the cookies in {site}.txt no longer work. Export fresh ones."

    owner_no_impersonation = (
        "yt-dlp has no impersonation target (curl-cffi missing or broken). Anonymous Instagram downloads fail."
    )

    stats = (
        "\n\n⌬─────「 Stats 」─────⌬\n\n"
        "<b>╭🖥️ **CPU Usage »**</b>  __{cpu}%__\n"
        "<b>├💾 **RAM Usage »**</b>  __{ram}%__\n"
        "<b>╰🗃️ **DISK Usage »**</b>  __{disk}%__\n\n"
        "<b>╭📤Upload:</b> {sent}\n"
        "<b>╰📥Download:</b> {received}\n\n\n"
        "<b>Memory Total:</b> {memory_total}\n"
        "<b>Memory Free:</b> {memory_free}\n"
        "<b>Memory Used:</b> {memory_used}\n"
        "<b>SWAP Total:</b> {swap_total} | <b>SWAP Usage:</b> {swap_percent}%\n\n"
        "<b>Total Disk Space:</b> {disk_total}\n"
        "<b>Used:</b> {disk_used} | <b>Free:</b> {disk_free}\n\n"
        "<b>Physical Cores:</b> {physical_cores}\n"
        "<b>Total Cores:</b> {total_cores}\n\n"
        "<b>🤖Bot Uptime:</b> {bot_uptime}\n"
        "<b>⏲️OS Uptime:</b> {os_uptime}\n"
    )

    help = """
<b>Send me a link to a video</b> and I send the video back.

I work with YouTube, Shorts, TikTok, Instagram and the other [sites yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md). If your message has other text around the link, I use the first link in it.

<b>What you get</b>
→ Video up to 1440p (2K) by default, in a form that plays inline in every Telegram app
→ The original audio track, unless the owner set a preferred language
→ Thumbnail and metadata embedded in the file
→ Long videos may come in a lower resolution to stay under Telegram's 2 GB limit

<b>Not supported</b>
→ Playlists, channels and live streams

<b>Commands</b>
/settings: quality, send as video, audio or file, video codec, SponsorBlock
/ping: check that the bot is up
/about: credits and license
    """

    about = """
ytdlbot, a fork of github.com/Katze-942/ytdlbot, itself a fork of github.com/tgbot-collection/ytdlbot by BennyThink.

Original code by BennyThink, SanujaNS and contributors; intermediate fork by Katze-942 and contributors.

License: Apache-2.0. Not affiliated with or endorsed by the upstream authors.
    """

    settings = """
Choose how I send your videos.

<b>Video codec</b>
→ Auto: plays inline in every Telegram app (H.264, or H.265 from TikTok). Above 1080p YouTube has no H.264; short videos may be converted, longer ones come in 1080p.
→ VP9: smaller files, up to 1440p on YouTube.
→ AVC1 (H.264): H.264 only where the site has it.
→ AV1: smallest files, but older devices may not play it.

<b>Send as</b>
Video plays in Telegram. File keeps the original file but needs another player. Choose audio for music.

<b>SponsorBlock</b>
Cuts sponsor segments out of YouTube videos. The video is not re-encoded, so some players may stutter at the cuts.

<b>Your settings</b>
Quality: <b>{}</b>
Send as: <b>{}</b>
Codec: <b>{}</b>
SponsorBlock: <b>{}</b>
    """

    # stored setting value -> what the user sees in /settings and in the "saved" answer
    names = {
        "document": "File",
        "video": "Video",
        "audio": "Audio",
        "vcodec-auto": "Auto (H.264 first)",
        "vcodec-vp9": "VP9",
        "vcodec-avc1": "AVC1 (H.264)",
        "vcodec-av01": "AV1",
        "disabled": "Off",
        "remove": "On",
    }

    # callback data -> button label
    buttons = {
        "document": "Send as file",
        "video": "Send as video",
        "audio": "Send as audio",
        "vcodec-auto": "Auto (H.264 first)",
        "vcodec-vp9": "VP9",
        "vcodec-avc1": "AVC1 (H.264)",
        "vcodec-av01": "AV1 (smallest, needs a newer device)",
        "sponsorblock-disabled": "Keep sponsor segments",
        "sponsorblock-remove": "Cut sponsor segments",
        "1440p": "1440p",
        "1080p": "1080p",
        "720p": "720p",
        "480p": "480p",
        "240p": "240p",
        # /buy: quota for US dollars
        "buy-10-1": "10-$1",
        "buy-20-2": "20-$2",
        "buy-40-3.5": "40-$3.5",
        "buy-50-4": "50-$4",
        "buy-75-6": "75-$6",
        "buy-100-8": "100-$8",
    }

    # setting key -> answer shown after a settings button is pressed
    saved = {
        "format": "Send as: {}",
        "quality": "Quality: {}",
        "vcodec": "Codec: {}",
        "sponsorblock": "SponsorBlock: {}",
    }


class Types:
    Message = typing.Union[types.Message, typing.Coroutine]
    Client = Client
