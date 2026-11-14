# ytdlbot

Fork of [Katze-942/ytdlbot](https://github.com/Katze-942/ytdlbot), itself a fork of [tgbot-collection/ytdlbot](https://github.com/tgbot-collection/ytdlbot) by [BennyThink](https://github.com/BennyThink). Original code by BennyThink, SanujaNS and contributors; intermediate fork by Katze-942 and contributors. Apache-2.0. Not affiliated with or endorsed by the upstream authors.

## What it does

A Telegram bot for a small allow-listed group of people. Send it a link in a private chat (YouTube, YouTube Shorts, TikTok, Instagram Reels, or any other [site yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)) and it sends the video back in the same chat. If the message has other text around the link, the bot uses the first http(s) link in it.

- Videos come as MP4 with H.264 first, so they play inline in every Telegram app. Nothing is re-encoded: if a site has no H.264 (YouTube above 1080p, some TikTok posts), the bot sends what exists.
- Long videos may come in a lower resolution to stay under Telegram's 2 GB limit.
- Thumbnail and metadata are embedded in the file.
- Each user chooses quality, video codec, send as video, audio or file, and SponsorBlock cutting in `/settings`.
- Playlists, channels and live streams are not supported.
- People who are not on the allow list get their Telegram ID (at most once a day) so they can send it to the owner, and nothing else.

## Commands

| Command | What it does |
|---|---|
| `/start` | Greeting |
| `/help` | What the bot does |
| `/about` | Credits and license |
| `/ping` | Check that the bot is up |
| `/settings` | Quality, send as, codec, SponsorBlock |
| `/stats` | Server stats, owners only, needs `ENABLE_STATS` |
| `/direct <url>` | Download a file over plain HTTP (aria2 with `ENABLE_ARIA2`), needs `ENABLE_DIRECT` |
| `/spdl <url>` | pixeldrain, krakenfiles and Instagram through an external service, needs `ENABLE_SPDL` |
| `/ytdl <url>` | Download in a group, needs `ENABLE_GROUPS` |

## Configuration

Everything is set through environment variables (or a `.env` file, see `.env.example`). A blank value (`VAR=`) means the default. An invalid value (a non-numeric ID, a boolean that is not `true`/`false`/`1`/`0`/`yes`/`no`, a non-integer number) stops the bot at startup.

| Variable | Default | Meaning |
|---|---|---|
| `APP_ID` | none, required | Telegram API ID from my.telegram.org |
| `APP_HASH` | none, required | Telegram API hash from my.telegram.org |
| `BOT_TOKEN` | none, required | Bot token from BotFather |
| `OWNER` | empty | Comma-separated Telegram IDs of the owners. Owners are always allowed |
| `AUTHORIZED_USER` | empty | Comma-separated Telegram IDs of the other allowed users. With `OWNER` and `AUTHORIZED_USER` both empty, nobody can use the bot |
| `WORKERS` | `16` | Handler threads |
| `DATA_DIR` | `/data` | Persistent state: the SQLite database and the Telegram session file |
| `DB_DSN` | `sqlite:///<DATA_DIR>/ytdlbot.db` | SQLAlchemy database URL |
| `TMPFILE_PATH` | `/tmp/ytdlbot` | Scratch directory for downloads. Emptied at startup, so it must not overlap `DATA_DIR` |
| `REDIS_HOST` | unset | Redis host for the cache of already-sent files. Unset or unreachable: an in-process cache that a restart clears |
| `TG_NORMAL_MAX_SIZE` | `2000` | Largest download in MiB; a bigger download stops |
| `AUDIO_FORMAT` | `m4a` | Audio format preferred when a user sends as audio |
| `PREFERRED_AUDIO_LANG` | empty | Audio language to prefer, e.g. `en`. Empty: the original track |
| `YT_DLP_PROXY` | empty | Proxy for yt-dlp, e.g. `http://proxy.example:8080`. Empty: direct connection |
| `BROWSERS` | empty | YouTube only: yt-dlp's cookies-from-browser value, e.g. `firefox`. The image has no browser |
| `POTOKEN` | empty | YouTube only: a PO token, see yt-dlp's [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) |
| `ENABLE_SEARCH` | `false` | Text without a link searches YouTube. Off: the bot asks for a link |
| `ENABLE_DIRECT` | `false` | `/direct` |
| `ENABLE_ARIA2` | `false` | aria2 for `/direct` |
| `ENABLE_SPDL` | `false` | `/spdl` |
| `ENABLE_STATS` | `false` | `/stats` for owners |
| `ENABLE_GROUPS` | `false` | `/ytdl` in groups. Off: group messages are ignored |
| `M3U8_SUPPORT` | `false` | m3u8 links. Off: refused |

For YouTube, a Netscape cookies file named `youtube-cookies.txt` in the working directory (`/app` in the image) is used when it exists.

## Run locally with Docker Compose

1. `cp .env.example .env` and fill in `APP_ID`, `APP_HASH`, `BOT_TOKEN`, `OWNER` and `AUTHORIZED_USER`.
2. `docker compose build` builds the `runtime` image as `ytdlbot:local`.
3. `docker compose run --rm ytdlbot python main.py --self-check` checks the image without contacting Telegram: it prints the yt-dlp, curl-cffi and kurigram versions and whether impersonation works and `/data` and `/tmp` are writable, and exits non-zero if something is wrong.
4. `docker compose up -d` starts the bot; `docker compose logs -f` follows the log.

The container runs as a non-root user with a read-only root filesystem. The database and the session file live in the `ytdlbot-data` volume (`/data`); downloads go to the `ytdlbot-tmp` volume (`/tmp`). One SQLite file, no Redis or other database service.

## Development

- `uv sync` installs Python 3.12 dependencies from `uv.lock`.
- `uv run pytest -q` runs the unit tests (no network, no Telegram). `tests/repo` holds checks that need a full git checkout; the image's `test` target leaves them out.
- `docker build --target test -t ytdlbot:test . && docker run --rm ytdlbot:test` runs the unit tests inside the image.
- To run the bot without Docker, set `DATA_DIR` and `TMPFILE_PATH` to local directories in `.env`, then `cd src && uv run python main.py`. YouTube needs [deno](https://deno.com) on the PATH.

## Changes from upstream

This list is written from the code at this fork's head, compared with Katze-942/ytdlbot at `0d5bfcd`. Every source file changed here carries a `Modified 2026 by megabitus98 (fork)` line under its header.

- **English only.** Every user-facing text lives in `src/config/constant.py`; a test fails on Cyrillic in `src/`. `/about` credits both upstream projects and links their GitHub repositories only.
- **Access control.** One guard at dispatcher group -1 checks every message and every button press before any other handler runs. `OWNER` and `AUTHORIZED_USER` are parsed strictly and an empty list allows nobody. Messages without a sender (channels, anonymous admins) are ignored. Private chats only unless `ENABLE_GROUPS` is on.
- **Links in text.** The first http(s) link in a message is downloaded, so share-sheet messages with a title line work. Text without a link gets "Send me a link to a video." unless `ENABLE_SEARCH` is on.
- **Feature switches.** Search, `/direct`, aria2, `/spdl`, `/stats` (owners only), groups and m3u8 links are all off by default. `M3U8_SUPPORT=false` now really refuses m3u8 links.
- **Format choice.** H.264 first and merged into MP4 so Telegram plays videos inline; the codec setting defaults to "Auto (H.264 first)" and VP9 or AV1 can still be chosen. Katze's size-capped format ladder stays. `PREFERRED_AUDIO_LANG` replaces the fixed Russian audio preference.
- **Settings.** Button data is matched exactly and a setting is saved for the user who pressed the button, not for the chat.
- **State.** SQLite under `DATA_DIR` with WAL and a 30 s busy timeout; the Telegram session file sits next to it. `src/database/migrate.py` holds a check-and-`ALTER` helper for columns added later. The bot refuses to start when `TMPFILE_PATH` and `DATA_DIR` overlap. No MySQL driver.
- **Logs and errors.** One log formatter redacts the bot token, credentials in URLs and cookie values, tracebacks included. yt-dlp runs without verbose output and logs through it. Users never see exception text, only "Something went wrong with this download."
- **Build.** uv with a lock file instead of PDM, Python 3.12, kurigram 2.2.27, yt-dlp with curl-cffi for browser impersonation. Alpine image pinned by digest, non-root user, caches and scratch under `/tmp` so the root filesystem can be read-only, `runtime` and `test` targets, and `python main.py --self-check`.
- **Repository.** Donation and payment material, the upstream public bot links and images, the old workflows and Dependabot file, and the Redis and MySQL compose services are gone. A unit test suite lives in `tests/`.

Kept from Katze-942/ytdlbot: embedded thumbnails and metadata, quality, codec and SponsorBlock settings, IPv4-only downloads, `YT_DLP_PROXY`. Still absent, as in Katze-942/ytdlbot: VIP quota, payments and `/buy`.

## License

Apache License 2.0, see `LICENSE` and `NOTICE`.
