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
| `/spdl <url>` | pixeldrain and krakenfiles, needs `ENABLE_SPDL` |
| `/ytdl <url>` | Download in a group, needs `ENABLE_GROUPS` |
| `/buy` | Buy download quota through Telegram payments, needs `ENABLE_VIP` and `PROVIDER_TOKEN` |

## Configuration

Everything is set through environment variables (or a `.env` file, see `.env.example`). A blank value (`VAR=`) means the default. An invalid value (a non-numeric ID, a boolean that is not `true`/`false`/`1`/`0`/`yes`/`no`, a non-integer number, a proxy exit that is not `direct` or an http(s) URL, a pin to an exit that is not listed) stops the bot at startup.

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
| `TG_NORMAL_MAX_SIZE` | `2000` | Largest file in MiB. A download that grows past it stops; a finished file over it is downloaded once more one quality lower, then refused |
| `MAX_PARALLEL_JOBS` | `2` | Downloads running at once. The others wait and their users see "Queued, position N." |
| `TMP_BUDGET` | `MAX_PARALLEL_JOBS` × 4500 MiB | Bytes all downloads together may keep under `TMPFILE_PATH`; a download stops when they go over. Set it to the scratch volume's size minus a margin |
| `JOB_TIMEOUT` | `2700` | Seconds one download may take |
| `OWN_PUBLIC_IPS` | empty | Comma-separated static public IPs of your own network. Links that resolve to them are refused |
| `AUDIO_FORMAT` | `m4a` | Audio format preferred when a user sends as audio |
| `PREFERRED_AUDIO_LANG` | empty | Audio language to prefer, e.g. `en`. Empty: the original track |
| `PROXY_EXITS` | `direct` | Comma-separated exits yt-dlp tries in order, e.g. `direct,http://proxy.example:8080`. `direct` is no proxy; the others are `http://` or `https://` proxy URLs (no SOCKS: ffmpeg cannot use it). The next exit is tried only when a site blocks the current one. Uploads to Telegram never use them. Use exits with distinct public IPs. Proxy URLs are secrets: they never appear in logs or messages |
| `PROXY_PIN` | empty | Comma-separated `site=exit` pairs, e.g. `instagram=direct`. A pinned site uses only that exit and never falls back. The exit must be in `PROXY_EXITS`; the site is the cookies file name below (`instagram`, `youtube`, `tiktok`, ...) |
| `COOKIES_DIR` | `/cookies` | Directory with one Netscape cookies file per site, see below |
| `POTOKEN` | empty | YouTube only: a PO token, see yt-dlp's [PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide) |
| `ENABLE_SEARCH` | `false` | Text without a link searches YouTube. Off: the bot asks for a link |
| `ENABLE_DIRECT` | `false` | `/direct` |
| `ENABLE_ARIA2` | `false` | aria2 for `/direct` |
| `ENABLE_SPDL` | `false` | `/spdl` |
| `ENABLE_STATS` | `false` | `/stats` for owners |
| `ENABLE_GROUPS` | `false` | `/ytdl` in groups. Off: group messages are ignored |
| `M3U8_SUPPORT` | `false` | m3u8 links. Off: refused |
| `ENABLE_VIP` | `false` | Quota and payments, restored from upstream: each user gets `FREE_DOWNLOAD` downloads, reset every day at midnight (container time), and can buy more with `/buy`. A cached file counts as a download. Off: no quota is checked, `/buy` does not exist and no daily job runs |
| `PROVIDER_TOKEN` | empty | Payment provider token from BotFather, for `/buy`. A secret: it never appears in logs |
| `FREE_DOWNLOAD` | `3` | Free downloads per user per day, with `ENABLE_VIP` |
| `TOKEN_PRICE` | `10` | Downloads per US dollar. Read but unused, as in upstream: the `/buy` price list is fixed |
| `RCLONE_PATH` | unset | Restored from upstream (which reads it as `RCLONE`), where no code uses it any more. No effect |
| `ENABLE_FFMPEG` | `false` | Upstream's name (it once converted webm/flv to mp4). On: a video up to `REENCODE_MAX_SECONDS` long gets the best picture up to the quality setting (default 1440p), and a VP9 or AV1 result is converted to H.264 so Telegram plays it on every device. Off: H.264 first, nothing converted. ffmpeg is always used to merge streams and make thumbnails |
| `REENCODE_MAX_SECONDS` | `300` | Longest video `ENABLE_FFMPEG` converts; longer ones keep H.264 first. 0 turns conversion off |

Cookies are per site: `COOKIES_DIR/instagram.txt`, `youtube.txt`, `tiktok.txt`, and for other sites the yt-dlp extractor name in lower case (`vimeo.txt`). The site is the one yt-dlp's extractor would pick for the link. When the file for a site exists and is not empty, every download from that site uses it; otherwise the bot tries without a login. The bot only reads the files: each download gets an in-memory copy, so the directory can be a read-only mount (in Compose, add `- ./cookies:/cookies:ro` under `volumes`). Use a spare account for each site, not a personal one: every allowed user's downloads run as that account.

## Run locally with Docker Compose

1. `cp .env.example .env` and fill in `APP_ID`, `APP_HASH`, `BOT_TOKEN`, `OWNER` and `AUTHORIZED_USER`.
2. `docker compose build` builds the `runtime` image as `ytdlbot:local`.
3. `docker compose run --rm ytdlbot python main.py --self-check` checks the image without contacting Telegram: it prints the yt-dlp, curl-cffi and kurigram versions and whether impersonation works and `/data` and `/tmp` are writable, and exits non-zero if something is wrong.
4. `docker compose up -d` starts the bot; `docker compose logs -f` follows the log.

While the bot runs, a heartbeat asks Telegram for the bot's own account every 60 s and touches `/tmp/healthy` when it answers. `python health.py` (in `/app`) exits 0 while that file is younger than 180 s and 1 otherwise; use it as the liveness and startup probe.

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
- **Cookies and Instagram.** One cookies file per site in `COOKIES_DIR` instead of a YouTube-only `youtube-cookies.txt` in the working directory; yt-dlp gets an in-memory copy, so the mounted file is never written. `BROWSERS` (cookies from a browser) is gone. Instagram goes through yt-dlp; the `/spdl` Instagram engine and its call to an external service are removed.
- **Downloads in a queue.** Handlers hand each download to a pool of `MAX_PARALLEL_JOBS` (default 2) and return at once; waiting users see their place in the queue. A download stops when it grows past `TG_NORMAL_MAX_SIZE` (even when the size is not known in advance), when all downloads together go over `TMP_BUDGET`, or after `JOB_TIMEOUT`. A finished file over the limit is downloaded once more one quality lower before the bot says it is too large; the old "try /direct" text is gone.
- **Proxy fallback.** `PROXY_EXITS` replaces `YT_DLP_PROXY` with an ordered list of exits, tried one after another only when a site blocks the download; `PROXY_PIN` keeps a site (Instagram, for its login) on one exit. Each attempt extracts and downloads through the same exit, after its own host check. Logs and owner notices name an exit by its position (`exit 2`), never by URL.
- **Host check.** Before any download the link must be http(s) and its host must resolve to public IPv4 addresses only, none of them in `OWN_PUBLIC_IPS`; otherwise the user gets "This video is private, deleted or not available here." It is defence in depth: redirects and addresses inside pages get past it, so an egress network policy is still needed.
- **Cache and health.** One in-process file cache shared by every job, with SponsorBlock in the key. A heartbeat file for container probes (`python health.py`).
- **Logs and errors.** One log formatter redacts the bot token, the configured proxy exits, credentials in URLs and cookie values, tracebacks included. yt-dlp runs without verbose output and logs through it. Users never see exception text, only "Something went wrong with this download."
- **Build.** uv with a lock file instead of PDM, Python 3.12, kurigram 2.2.27, yt-dlp with curl-cffi for browser impersonation. Alpine image pinned by digest, non-root user, caches and scratch under `/tmp` so the root filesystem can be read-only, `runtime` and `test` targets, and `python main.py --self-check`.
- **Repository.** Donation and payment material, the upstream public bot links and images, the old workflows and Dependabot file, and the Redis and MySQL compose services are gone. A unit test suite lives in `tests/`. New workflows test every PR, and only a tested image reaches the `stable` tag; `deploy/` has a Kubernetes example and explains the pipeline.

Kept from Katze-942/ytdlbot: embedded thumbnails and metadata, quality, codec and SponsorBlock settings, IPv4-only downloads. Restored from tgbot-collection/ytdlbot and off by default: VIP quota, Telegram payments, `/buy` and the daily free-quota reset (`ENABLE_VIP`), with the quota columns added to an existing database at startup, and the `RCLONE_PATH` and `ENABLE_FFMPEG` settings (read but unused, as upstream).

## License

Apache License 2.0, see `LICENSE` and `NOTICE`.
