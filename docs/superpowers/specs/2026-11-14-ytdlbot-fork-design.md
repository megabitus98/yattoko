# ytdlbot fork: design

Status: draft v2 for owner review, 2026-11-14 (v1 went through a builder check, a fact check against the code, and security and delivery reviews). Nothing in this document is built yet.

Base: `Katze-942/ytdlbot` master at `0d5bfcd` (54 commits ahead of `tgbot-collection/ytdlbot` master `e03e55e`, 0 behind). File references are `path:line` at that commit.

How to read the labels: **[Owner]** marks a decision the owner made. **[Design]** marks a call made while writing or reviewing this document; the owner can overturn any of them. Unlabelled text is fact found in the code or in upstream sources. Facts marked *(observed YYYY-MM-DD)* were seen in a live run, not read from code, and are re-checked by the regression suite.

This repository is going to be public. This document names roles and env vars only. Real values (Telegram IDs, proxy addresses, hostnames, cluster and CI details) live in a private deployment note outside this repository and never enter git history here. Before the first push, `docs/` is reviewed once more for anything private.

## 1. Intent

The owner wants to send a link from a phone (YouTube, YouTube Shorts, TikTok, Instagram Reels, or any other site yt-dlp supports) to a Telegram bot and get the video back as a reply in the same chat. The phone then saves the video and the owner forwards it anywhere. **[Owner]**

A small group of people (the owner plus a few others) use the same bot. **[Owner]**

The bot runs on the owner's home Kubernetes cluster as one container. **[Owner]**

The owner wants the fork public, credited to its origins, and kept working over time without manual babysitting: dependency updates arrive by themselves, get tested, and ship only when tests pass. **[Owner]**

## 2. Goals, non-goals, anti-goals

Goals:
- Send a link, get a playable video back in the same chat, for the four main sites and the rest of yt-dlp's list.
- English-only bot. **[Owner]**
- Instagram works with a cookies file when one is present, and also tries without one. **[Owner]**
- Dependencies stay current: each new stable release is tested and shipped automatically when tests pass. **[Owner]**
- Breakage is noticed by the owner before users notice it.

Non-goals:
- A public bot for strangers. Only allow-listed people use it.
- Photo or carousel downloads from Instagram. Videos only.
- Using payments or quotas. The code comes back from upstream but stays switched off (6.3).
- YouTube channel subscriptions (upstream itself removed them in `d472cdc`; see 6.3).
- Multi-language support.
- Re-encoding video. **[Design]** If a source has no H.264 format, the bot sends what exists.

Anti-goals (would make this a failure even if it works):
- The bot becomes a way into the home network (fetching LAN addresses, or the home's own public IP, for someone).
- Secrets (bot token, cookies, proxy addresses, Telegram IDs) end up in the public repo, its history, the public image, or logs.
- An update that the tests did not cover ships anyway (tests pass on one version or tree, the image ships another).
- The owner's Instagram account gets locked because the bot behaves like a stolen session.

## 3. Constraints found during research

Code (all confirmed by the fact check):
- **Only 1 of 14 handlers checks the allow-list.** `@private_use` (`src/main.py:91`) wraps only `download_handler` (`src/main.py:331-332`). `/start /help /about /ping /stats /settings /direct /spdl`, group `/ytdl` and all 4 callback handlers are open to any Telegram user. `/direct` (`src/main.py:260`) fetches any http(s) URL with `requests` (`src/engine/direct.py:27`), no timeout, no size cap.
- **An empty `AUTHORIZED_USER` opens the bot to everyone** (`src/main.py:102-109`: `if users and ...`). A malformed list (trailing comma, a name) makes the guard raise on every message.
- **Katze already removed** VIP/payments/`/buy`, APScheduler, rclone, `ENABLE_FFMPEG` and `RATE_LIMIT` (commit `4e21b35`). Channel subscriptions were removed upstream earlier (`d472cdc`). "Keep unused features, disable via env" can only apply to what still exists.
- **Search is on and has no switch.** Any non-URL text becomes a YouTube search (`src/main.py:340-352`).
- **A hard-coded Russian audio preference** (`[language=ru]`, `src/engine/generic.py:33-41,68`) survives a text-only translation.
- **Instagram's `/spdl` engine calls a service that does not exist** in either repo (`http://instagram:15000`, `src/engine/instagram.py:47`).
- **Cookies are only used for YouTube** (`src/engine/generic.py:139-144`), from a relative path.
- **The bot's default codec setting is VP9** (merged into MP4, `src/database/model.py:39`, `src/engine/generic.py:57,113-114`); yt-dlp's own default prefers AV1/VP9 for YouTube and H.265 for TikTok. Telegram plays H.264 most reliably.
- **Secrets leak to logs**: `src/engine/generic.py:155` logs the full yt-dlp options (proxy URL with credentials, PO token), and `verbose: True` (`src/engine/generic.py:80`) prints the proxy map.
- **Full exception text goes to users** (`src/main.py:275,295,316,370,373` and the engines), exposing hostnames, paths and proxy errors.
- **State lands in the image filesystem by default**: the SQLite file (README example) and kurigram's `main.session` (`Client("main")` with no `workdir`, `src/main.py:78-88`; kurigram's default workdir is the script's directory, `/app`).
- **The 2 GB upload guard is per stream and only when the size is known** (`src/engine/base.py:113-118`); a merged file can exceed it after a full download.
- **`WORKERS=100`** means up to ~100 parallel downloads in one thread pool; there is no per-job concurrency cap.
- **The file_id cache is shared across jobs only by accident**: a new `Redis()` per job (`src/engine/base.py:66`) shares data only because `src/database/cache.py:22` passes `host=REDIS_HOST`; fakeredis gives every client without a `host` its own private server.
- **The repo carries third-party payment and identity material**: `.github/FUNDING.yml`, payment QR codes (`assets/USD.png`, `assets/CNY.png`, `assets/tron.png`), screenshots with third-party content (`assets/1.jpeg`, `assets/instagram.png`), upstream authors' Telegram handles in `/help` and `/about` (`src/config/constant.py:62-75`), `.github/workflows/upgrade.yml` (root SSH deploy to the upstream author's server, a third party's chat ID), `.github/workflows/builder.yaml` (pushes `:latest` on every push to master with no test gate), and `docker-compose.yml` (MySQL with root password `root`, Redis, a third party's image, a bind-mounted cookies file).
- **Ignore files have gaps**: `.gitignore` misses `*.db`, `*cookies*.txt`, most `*.session`; `.dockerignore` misses `.env`, sessions, sqlite, cookies, while the Dockerfile does `COPY src /app`.
- **No tests exist.** `src/test.py` is a manual download script.
- **License**: Apache-2.0, no NOTICE file anywhere. Section 4(b) requires prominent notices in modified files; 4(c) requires keeping existing attribution (`__author__` lines in `src/main.py:8`, `src/config/config.py:8`, `src/config/constant.py:8`, `src/engine/krakenfiles.py:6`, `src/engine/pixeldrain.py:6`, and the "By @BennyThink" banner at `src/main.py:436`).

yt-dlp and dependencies:
- **yt-dlp rewrites the cookie file on every close** (`YoutubeDL.close()` → `save_cookies()` → `open(path, 'w')`). On a read-only mount this raises `OSError` (EROFS; `PermissionError` on a read-only file). A missing path gets created. Parallel jobs sharing one file race. Passing an `io.StringIO` instead works, but yt-dlp truncates without rewinding, so the buffer ends up NUL-padded and must not be parsed back.
- **Anonymous Instagram needs curl-cffi.** yt-dlp runs the anonymous GraphQL path only when it can impersonate a browser (`yt_dlp/extractor/instagram.py:473-488`, issue #17074). Without curl-cffi it fails as a login/redirect error and **no warning is printed**, so missing impersonation must be checked explicitly. A cookie-less public reel worked from a residential IP *(observed 2026-11-14, yt-dlp 2026.08.19)*.
- **yt-dlp has no exception types for login-required or rate-limit.** They are `ExtractorError(expected=True)` with text; some texts come from the site, not from yt-dlp (YouTube's "Video unavailable" prefix is server text; yt-dlp appends "has been rate-limited by YouTube for up to an hour"). Fragment give-up errors carry no exception object at all.
- **Dependabot cannot update `pdm.lock`.** Its pip ecosystem skips PEP 621 dependencies when `pdm.lock` exists ("PDM is not yet supported", dependabot-core) and edits only `requirements.txt`, which the image never reads. Upstream re-did Dependabot bumps by hand in `pdm.lock`, sometimes as a "(PDM)" commit, otherwise inside later bulk bumps. The Dockerfile's plain `pdm install` also silently re-resolves a stale lock.
- **`requires-python = ">=3.10"`** (`pyproject.toml:10`) blocks yt-dlp 2026.10.26 (needs >=3.11) in a lock.
- **Image today ships yt-dlp 2026.8.19**; latest stable is 2026.10.26. kurigram 2.2.23 vs 2.2.27 (2.2.26 changed `save_file` to raise on upload failure).
- **yt-dlp pins `yt-dlp-ejs` exactly** in its `default` extra but only bounds curl-cffi (`>=0.5.10,...,<0.18`), so curl-cffi gets no Dependabot PRs unless it is a direct dependency.

## 4. Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| Own small bot (~50 lines, Bot API) | Full control, tiny code; 50 MB Bot API upload limit unless a local Bot API server is added; no quality choice or caching | Rejected by owner: no reason to start from zero |
| n8n workflow | Needs a public webhook into the home network and a custom image with yt-dlp/ffmpeg | Rejected |
| Upstream `tgbot-collection/ytdlbot` + small patches | English, MTProto (2 GB uploads); frozen since 2026-02-02 with yt-dlp 2026.1.31; same Instagram and cookie problems | Rejected in favour of Katze |
| Other forks | 631 forks; only Katze-942 and one other added work this year; the other is mostly AI-bot commits and forces 720p re-encodes | Rejected |
| **Fork `Katze-942/ytdlbot`** | Most current fork (yt-dlp 2026.8.19, SponsorBlock, codec choice, proxy option, temp cleanup); Russian UI; same Instagram gaps; one-person personal-use fork | **Picked by owner** |

**[Owner]** We own the fork outright and do not keep merging Katze's future changes; their changes would be Russian-text conflicts every time, and the freshness that matters (yt-dlp) comes from our own update pipeline.

## 5. Decisions recap

| # | Decision | Source |
|---|---|---|
| 1 | Public fork of Katze-942/ytdlbot with credit to Katze-942 and tgbot-collection/BennyThink | [Owner] |
| 2 | English only | [Owner] |
| 3 | Existing features stay in the code but are switched off by env when unused | [Owner] |
| 4 | SQLite, no external Redis, one container | [Owner] |
| 5 | Several users, listed in `AUTHORIZED_USER`; adding someone = edit env + restart | [Owner] |
| 6 | Non-allowed users are told their Telegram ID | [Owner] |
| 7 | Cookies: if a cookies file exists for a site, always use it; otherwise try without login | [Owner] |
| 8 | On login/block-type failures: reply to the user and notify the owner, at most once per site per day | [Owner] |
| 9 | Proxy fallback list, used only on block-type errors; Instagram pinned to one exit; Telegram uploads stay direct | [Owner] |
| 10 | Updates: a PR per new stable dependency release; unit tests on GitHub; real-download tests on home Jenkins; merge only when green; also run real-download tests weekly | [Owner] |
| 11 | No per-user download limit for now | [Owner] |
| 12 | Nothing published until the owner says so | [Owner] |
| 13 | Features Katze deleted are restored from upstream (`tgbot-collection/ytdlbot` master) and switched off | [Owner] |
| 14 | Commits are made under the owner's GitHub account (its noreply email address) | [Owner] |

## 6. Design

### 6.1 Repository, credit and license

- **[Design]** README opens with: "Fork of [Katze-942/ytdlbot](https://github.com/Katze-942/ytdlbot), itself a fork of [tgbot-collection/ytdlbot](https://github.com/tgbot-collection/ytdlbot) by [BennyThink](https://github.com/BennyThink). Original code by BennyThink, SanujaNS and contributors; intermediate fork by Katze-942 and contributors. Apache-2.0. Not affiliated with or endorsed by the upstream authors."
- **[Design]** Add a `NOTICE` file naming both upstream projects (neither upstream has one).
- **[Design]** Every file we change gets one line under its existing header: `# Modified 2026 by <fork owner>: <what>`. Existing `__author__` lines and the startup banner stay (license 4(c)).
- **[Design]** README gets a "Changes from upstream" section written from the code, not translated from Katze's Russian changelog (which is stale: it says search is off and Firefox cookies are used; the code does the opposite).
- **[Design]** Delete: `.github/FUNDING.yml`, `assets/USD.png`, `assets/CNY.png`, `assets/tron.png`, the README donation section, `assets/1.jpeg`, `assets/instagram.png`, `.github/workflows/upgrade.yml`, `.github/workflows/builder.yaml` (replaced by 6.14; no `:latest` tag anywhere), `docker-compose.yml` (replaced by a one-service SQLite example), `src/test.py`, the tracked empty `youtube-cookies.txt`, `.pdm-python`, `requirements.txt`, `pre-push.py`, the README sections advertising upstream's public bots and `bennythink/ytdlbot`. Rewrite `AGENTS.md`/`CLAUDE.md` from the new code (today they claim every handler is gated and the UI is Russian).
- **[Design]** `/about` and `/help` link the GitHub repos of the upstream projects only, never the upstream authors' Telegram handles as support contacts (third-party identity; no implied endorsement).
- **[Design]** `.gitignore` adds `*.session`, `*.session-journal`, `*.sqlite*`, `*.db`, `*cookies*.txt`, `cookies/`, `.env.*` with `!.env.example`, `.pdm-python`. `.dockerignore` adds `**/.env*`, `**/*.session*`, `**/*.sqlite*`, `**/*.db`, `**/*cookies*`, `.git`, `docs`.
- **[Design]** Every `actions/checkout` uses `persist-credentials: false`; actions are pinned by full commit SHA.
- **[Owner]** Commits use the owner's GitHub account: its profile name and its `users.noreply.github.com` address, set as the local git identity of this clone before the first commit.
- Until the owner says "publish": push URLs of the `katze` and `upstream` remotes stay disabled and nothing is pushed (see Q3 for where the code lives before then).

### 6.2 Access control

- **[Design]** One guard handles every message and every callback query, registered at kurigram dispatcher `group=-1`, ending with `stop_propagation()` when the sender is not allowed. Lower groups run first and `StopPropagation` ends dispatch, so all message and callback handlers, current and future, are covered by one check. `@private_use` is removed. A unit test fails if any registered handler type has no matching guard (so a future inline or edited-message handler cannot slip in unguarded).
- **[Design]** `AUTHORIZED_USER` is parsed once at startup into a frozenset of ints: strip blanks, skip empty items, and **refuse to start** if any item is not an integer. **An empty list denies everyone** (fail closed). `OWNER` is parsed the same way and owners are always allowed.
- **[Owner]** A non-allowed user in a private chat gets: "You don't have access to this bot. Your Telegram ID is {id}. Send it to the owner to get access." **[Design]** At most once per ID per day, tracked in an in-memory dict (never persisted; a restart resets it). Callback queries from non-allowed users get a short alert. Messages with no sender (`from_user is None`: channels, anonymous admins) are ignored.
- **[Design]** Private chats only by default. Group use (`/ytdl` in groups, shared group settings) is behind `ENABLE_GROUPS=false`. The owner also turns off "Allow groups" in BotFather (deployment checklist).
- **[Design]** Callback regexes are anchored (`^(...)$`), callback data is mapped through a dict, and settings are saved under `from_user.id`, not the chat ID.
- **[Design]** Every handler that touches the database runs after the guard, so strangers no longer create database rows.

### 6.3 Feature switches

**[Owner]** Unused features stay but are off by env. **[Design]** Every switch is a boolean env var read in `src/config/config.py`; defaults below are the shipped defaults.

| Feature | Env var | Default | Notes |
|---|---|---|---|
| YouTube search for non-URL text | `ENABLE_SEARCH` | false | New switch; today always on |
| `/direct` (requests/aria2 download of any URL) | `ENABLE_DIRECT` | false | New switch. If enabled: timeout, size cap, re-check host on each redirect; aria2 with `--follow-torrent=false --follow-metalink=false` |
| aria2 engine for `/direct` | `ENABLE_ARIA2` | false | Exists |
| `/spdl` (pixeldrain, krakenfiles) | `ENABLE_SPDL` | false | New switch. krakenfiles is broken today (`soup.xpath`); Instagram leaves `/spdl` entirely (6.5) |
| m3u8 links | `M3U8_SUPPORT` | false | Exists but does nothing today (return value discarded, `src/main.py:327-328,354`); fix so false really blocks |
| `/stats` | `ENABLE_STATS` | false | Owner-only when enabled |
| Groups | `ENABLE_GROUPS` | false | See 6.2 |
| SponsorBlock | per-user setting | off | Kept as a user setting; cache key fixed (6.8) |
| Codec, quality, send-as video/audio/document | per-user settings | see 6.4 | Kept |
| Russian audio preference | (removed) | | Replaced by `PREFERRED_AUDIO_LANG` (empty = original track) |
| VIP: free quota, paid quota, Telegram payments, `/buy`, daily free-quota reset | `ENABLE_VIP` (+ `PROVIDER_TOKEN`, `FREE_DOWNLOAD`, `TOKEN_PRICE`) | false | **[Owner]** Restored from upstream master (`src/config/config.py:46-49`, `src/database/model.py` `Payment` model and quota functions, `src/main.py:149-181` `/buy`, the APScheduler `reset_free` job at `src/main.py:404-405`), deleted by Katze in `4e21b35`. With `ENABLE_VIP=false`, `/buy` is unreachable, no quota is checked, and the scheduler job is not started |
| rclone upload | `RCLONE_PATH` | unset (off) | **[Owner]** Restored from upstream master. **[Design]** Upstream reads env `RCLONE` while its docs say `RCLONE_PATH`; the restored code reads `RCLONE_PATH` |
| ffmpeg extras | `ENABLE_FFMPEG` | false | **[Owner]** Restored from upstream master with upstream's meaning. ffmpeg itself stays required for merging and thumbnails |
| YouTube channel subscriptions | (not restored) | | **[Design]** Upstream itself removed them in `d472cdc` (2025-01), from code written for its older architecture, so "restore from upstream" has nothing current to restore. Porting the 2024 code is a separate decision |

Restored code comes back in upstream's English, passes through the access guard (6.2) like every handler, and uses the same SQLite database (the `Payment` table and quota columns are created by `create_all`). Unit tests prove each restored feature is unreachable when its switch is off.

Dead env vars documented today: `TG_NORMAL_MAX_SIZE` is wired up (6.8); `CAPTION_URL_LENGTH_LIMIT` stays a constant and leaves the docs; `RATE_LIMIT` leaves the docs (no code reads it, upstream included).

### 6.4 Download path

- **[Design]** One `YoutubeDL` instance per attempt (a proxy change needs a new instance; `proxies` and the request director are cached per instance). Extraction and download happen in the same instance through the same exit (YouTube media URLs are tied to the extracting IP).
- **[Design]** The playlist/channel refusal happens after `extract_info(download=False)` and before any download, by checking the extracted `_type`. It replaces the crude "URL contains `list`" check (`src/main.py:321-325`) and the `playlist_items: 1` hack (`src/engine/generic.py:95`). Live streams stay refused.
- **[Design]** Format choice prefers what Telegram plays inline: sort `vcodec:h264,res,acodec:m4a` with `merge_output_format: mp4`, keeping Katze's size-capped format ladder. The per-user codec setting still overrides (VP9/AV1 on request). The default codec setting changes from VP9 to "auto (H.264 first)". No re-encoding: if a source has no H.264 (some TikTok posts; YouTube above 1080p), the bot sends what exists.
- **[Design]** The generic extractor stays enabled (it is how "any site" works); protection against internal addresses is the host check plus the NetworkPolicy (6.9).
- **[Design]** `verbose` is off; a logger is passed to yt-dlp so warnings (cookie expiry and others) are captured for 6.6.
- **[Design]** Restore upstream's Google Drive `source` format case, prepended to the format list **before** it is joined with `/` (Katze's first commit `8640b2e` moved it after the join, which made it dead code, and `4e21b35` then deleted it).
- **[Design]** curl-cffi is required. At startup the bot runs yt-dlp's own check (`YoutubeDL()._impersonate_target_available(ImpersonateTarget())`, the check the Instagram extractor uses); if no target is available it sends the owner an `impersonation_missing` notice and logs an error. A unit test runs the same check inside the built image.

### 6.5 Cookies and Instagram

- **[Owner]** If a cookies file exists for a site, it is always used for that site. If none exists, the bot tries without login. Nothing is switched off.
- **[Design]** One Netscape cookies file per site in `COOKIES_DIR` (default `/cookies`, mounted read-only from a Secret): `instagram.txt`, `youtube.txt`, `tiktok.txt`, … The site is chosen from yt-dlp's extractor key, mapped to a file name in one table. Per-site files keep "we have cookies for this site" exact and stop one site's login (e.g. YouTube's logged-in clients) from switching on just because another site has cookies.
- **[Design]** The cookies should come from a spare account per site, not the owner's personal accounts: every allow-listed user's downloads run as that account.
- **[Design]** The mounted file is **never** passed to yt-dlp. Each job reads it into memory and passes `cookiefile=io.StringIO(text)`. yt-dlp's write-back goes into that buffer, which is treated as write-only scratch and discarded (it ends up NUL-padded; never parse it back).
- **[Design]** Cookie expiry detection: yt-dlp's Instagram extractor warns "The provided Instagram account cookies are no longer valid" and drops `sessionid`. The bot detects the warning (logger) or checks `ydl.cookiejar` for `sessionid` on `https://www.instagram.com/` before `close()`, and raises a `cookies_expired` notice (6.6).
- **[Design]** Instagram goes through yt-dlp only. The `/spdl` Instagram engine and its sidecar call are deleted.
- **[Owner]** Instagram is pinned to one exit (6.7).

### 6.6 Error handling and owner notices

- **[Design]** One classifier maps any download failure to `login_required`, `blocked`, `unavailable` or `other`. It walks the exception chain (`.cause`, `DownloadError.exc_info[1]`, `__cause__`, `__context__`), checks types first (`GeoRestrictedError` → unavailable; `HTTPError` 403/429 and proxy errors → blocked), then message regexes in this fixed order: blocked, unavailable, login_required. The order matters: YouTube's rate-limit message starts with the server text "Video unavailable", and private-video text also says "sign in". `blocked` keys on yt-dlp's own appended text where one exists ("has been rate-limited by YouTube", "Your IP is likely being blocked", Instagram's "exceeded the rate-limit for accessing posts anonymously") and on observed server text otherwise. Fragment give-up errors carry no exception object, so the text check is needed. The strings are pinned in a unit test (6.13), labelled "yt-dlp source" or "observed server text" with the version/date; upstream wording changes break that test loudly.
- **[Design]** What the user sees, per kind:
  - `login_required`: "{Site} needs a login for this video. The owner has been told."
  - `blocked` (after all exits tried): "{Site} is blocking downloads right now. The owner has been told. Try again later."
  - `unavailable`: "This video is private, deleted or not available here."
  - `other`: "Something went wrong with this download."
  No exception text, hostnames, paths or proxy details ever go to users. The full traceback goes to the log (redacted, 6.10).
- **[Owner]** The owner gets a Telegram message from the bot itself for `login_required`, `blocked`, `cookies_expired` and `impersonation_missing`, **at most one per (site, kind) per day**. **[Design]** The last-sent time is stored in SQLite so restarts do not re-send. The message includes site, kind, whether cookies were present, which exits were tried, and a short redacted error excerpt.
- **[Design]** The owner loop sends to each ID in `OWNER` separately, each wrapped in try/except (today's only owner message passes the whole list as `chat_id` and fails, `src/main.py:367`). Each owner must have sent `/start` to the bot once; the deployment checklist says so.
- **[Design]** The FloodWait handler stops sleeping inside a worker thread for the whole wait (`src/main.py:368`); it schedules the retry instead.

### 6.7 Proxy fallback

- **[Owner]** An ordered list of exits; the bot moves to the next exit only on `blocked` errors. Uploads to Telegram never use the proxy.
- **[Design]** `PROXY_EXITS` env: comma-separated, `direct` meaning no proxy (yt-dlp `proxy=""`, which also ignores `HTTP(S)_PROXY`), the rest HTTP proxy URLs (HTTP rather than SOCKS: ffmpeg only gets proxies via `HTTP_PROXY` and does not support SOCKS). Default `direct`.
- **[Design]** `PROXY_PIN` env: `site=exit` pairs, e.g. `instagram=direct`. A pinned site uses only that exit and never falls back; a `blocked` error on a pinned site goes straight to the user reply and owner notice.
- **[Design]** The list must contain **distinct public IPs**. A proxy that leaves through the same line as direct egress adds nothing; check this when configuring. Mail-server, office, mobile-data and datacenter exits do not belong in the list.
- **[Design]** Instagram is pinned to `direct`: a residential IP that may change on reconnect but stays with the same ISP and region, the closest thing to a stable home login location.
- **[Design]** The host check (6.9) runs before every attempt, including proxied ones, because a proxy on the home network would otherwise fetch LAN addresses on the pod's behalf. Each proxy also gets an ACL that denies private destinations, its own addresses and the home's own public IPs (deployment checklist).
- **[Design]** Proxy URLs are secrets (they may carry credentials): they come from a Secret and are never logged (6.10).
- **[Design]** No network-condition logic: slowness is not a block. Timeouts are generous (home lines can be slow; a 2 GB download can take 10+ minutes).

### 6.8 Size, disk, concurrency, state

- **[Design]** Jobs run on a `ThreadPoolExecutor(MAX_PARALLEL_JOBS)` (default 2); the Telegram handler hands the job over and returns at once, so queued jobs never hold kurigram workers (`WORKERS` lowered to 16). Queued users see "Queued, position N".
- **[Design]** `download_hook` aborts a job when its downloaded bytes exceed `TG_NORMAL_MAX_SIZE` even when the total is unknown, and when the total size of `TMPFILE_PATH` exceeds `TMP_BUDGET` (the emptyDir size minus a margin). This keeps one runaway download from filling the volume and getting the whole pod evicted. Per-job wall-clock limit: 45 minutes.
- **[Design]** After merge and post-processing, the final file size is checked against `TG_NORMAL_MAX_SIZE` (default 2000 MiB) **before** upload. If too big: one retry with the next lower quality in the ladder; if still too big, the user is told the video is too large for Telegram. The misleading "try /direct" fallback text goes.
- **[Design]** Scratch: one `emptyDir` mounted at `/tmp`, with `TMPFILE_PATH=/tmp/ytdlbot`, `HOME=/tmp/home`, `XDG_CACHE_HOME=/tmp/cache`, `DENO_DIR=/tmp/cache/deno` (yt-dlp and deno write caches under HOME; the root filesystem is read-only). Size: `MAX_PARALLEL_JOBS × ~4.5 GB` *(estimate: separate streams + merged file + post-processor copies; measure and adjust)*. The startup purge of `TMPFILE_PATH` stays; the bot refuses to start if `TMPFILE_PATH` is inside the data volume.
- **[Design]** SQLite at an absolute path on a small persistent volume: `DB_DSN=sqlite:////data/ytdlbot.db`. Engine with `pool_size=5`, WAL mode, and a 30 s busy timeout. The volume must be block storage, not NFS/SMB (SQLite WAL does not work on network filesystems), and the pod sets `fsGroup` so the non-root user can write it. `create_all` stays; new columns get a tiny startup migration (check-and-`ALTER`). The `init_user` race (`src/database/model.py:126-130`) is handled with insert-or-ignore.
- **[Design]** kurigram session on the same volume: `Client(..., workdir="/data")`. One replica, `Recreate` strategy (SQLite and the session must never be shared by two pods). Tests use `in_memory=True` sessions so no session file is written in CI or Jenkins.
- **[Owner]** No external Redis. **[Design]** The file_id cache stays in fakeredis through **one module-level client** (or one shared `fakeredis.FakeServer()`) reused by every job; a unit test checks two jobs see the same entry. The cache is in-process and lost on restart (re-sending a link after a restart just downloads again). The cache key adds SponsorBlock and any other output-changing setting (`src/engine/base.py:303-307` omits it today). `REDIS_HOST` unset means fakeredis directly.
- **[Design]** A background task calls Telegram (`get_me`) every 60 s and touches `/tmp/healthy`; liveness and startup probes fail when the file is older than 180 s. Any startup failure (bad env, read-only volume, unwritable `/data`) crashes the process, so the probe and the restart count show it.

### 6.9 Network safety

- **[Design]** Host check in one place (`BaseDownloader.__init__` plus the yt-dlp entry in the download handler): scheme http/https, host present, every resolved address `is_global` (after unwrapping IPv4-mapped IPv6), not in the `OWN_PUBLIC_IPS` list, and IPv4 only (IPv6 literals and AAAA-only hosts are refused; `source_address: 0.0.0.0` stays). Refuse otherwise with the `unavailable` reply. This is defence in depth only: redirects, page-embedded media URLs and DNS rebinding get around it.
- **[Design]** The real control is a Kubernetes egress NetworkPolicy: deny all egress, allow DNS to the cluster DNS, allow `0.0.0.0/0` except private, CGNAT, link-local, loopback and multicast ranges, and allow each configured proxy exit's IP:port explicitly. No IPv6 egress. `automountServiceAccountToken: false`.
- **[Design]** The home's own public IP passes both checks above and can reach port-forwarded services through the router's NAT loopback, and it may be dynamic. So the router drops traffic from the cluster's node subnet to its own WAN address (deployment checklist), and `OWN_PUBLIC_IPS` lists any static ones.
- **[Design]** The concrete policy and router rule live with the private deployment manifests.

### 6.10 Logging and secrets

- **[Design]** Remove the full-options log (`src/engine/generic.py:155`) and `verbose: True`. Redaction happens in a `logging.Formatter` on the root handler, applied to the fully formatted line **including tracebacks**: the bot token, `user:pass@` in URLs, proxy URLs and cookie values. HTTP client loggers (`httpx`, `httpcore`, `urllib3`) are set to WARNING (they log request URLs at INFO). The same redact function runs on owner-notice excerpts. A unit test logs an exception containing a credentialed proxy URL and the token and checks neither appears. `AUTHORIZED_USER` is no longer logged.
- **[Design]** Secrets come only from env/Secret mounts: `BOT_TOKEN`, `APP_ID`, `APP_HASH`, `OWNER`, `AUTHORIZED_USER`, `PROXY_EXITS`, `OWN_PUBLIC_IPS`, `COOKIES_DIR` contents, `POTOKEN` (only if ever needed). The `/data` volume also holds secret-class files (the kurigram session is a bot credential; the database holds Telegram IDs).
- **[Design]** The image runs as a non-root user with a read-only root filesystem; writable paths are `/data` and `/tmp`.

### 6.11 English texts

- **[Owner]** English only. 153 Cyrillic lines in 9 files: `src/config/constant.py` 51, `src/main.py` 50, `src/engine/*` 25, `README.md` 27.
- **[Design]** Where upstream English exists (most status/error strings, visible as `-` lines in `git diff upstream/master...HEAD`), reuse it. Katze-only texts (codec and SponsorBlock buttons, search strings, AV1 warning, settings paragraphs) get new English. The repeated "an error occurred" string becomes one constant. All user-facing text lives in `src/config/constant.py`.
- **[Design]** `/help` is rewritten from what the bot actually does after this fork. `/start` greets and points to `/help`.

### 6.12 Dependencies and image

- **[Design]** Switch from PDM to **uv**: `pyproject.toml` + `uv.lock`, image installs with `uv sync --locked --no-dev` (fails on drift) and `UV_PYTHON_DOWNLOADS=0` (an interpreter mismatch fails the build instead of downloading a different Python). Dependabot supports the `uv` ecosystem natively and updates the lock with each bump. (Renovate keeping PDM is the alternative; rejected to avoid a third-party app with write access.)
- **[Design]** `requires-python = ">=3.12,<3.13"` to match the image.
- **[Design]** Direct dependencies: `yt-dlp[default,curl-cffi]` (yt-dlp fixes the exact `yt-dlp-ejs` version and the allowed curl-cffi range; the separate `yt-dlp-ejs` line is dropped), `curl-cffi` (declared directly with no bound of our own, so Dependabot bumps it; it carries the browser impersonation Instagram needs), `kurigram[fast]==2.2.27` (kuricrypt replaces tgcrypto; every compiled dependency has a musl wheel, so no C compiler in the build), `SQLAlchemy`, `fakeredis`, `redis` (imported directly by `src/database/cache.py`), `requests`, `filetype`, `beautifulsoup4`, `psutil`, `python-dotenv`, `ffmpeg-python` (`src/engine/base.py:21`), `tqdm` (`src/engine/base.py:24`), `APScheduler` (back with the restored daily quota reset, 6.3). Dev group: `pytest`, `black`. Dropped on purpose: `tgcrypto`, `PyMySQL`, and explicit `cryptography`/`greenlet` pins. No pre-releases anywhere (yt-dlp publishes nightly `.dev0` builds to PyPI).
- **[Design]** kurigram 2.2.27 changes upload behaviour (`save_file` raises on failure since 2.2.26); the upload fallback loop in `src/engine/base.py:252-282` is rewritten for it, and slice 1 ends with a manual real-upload check (section 7).
- **[Design]** Base image `python:3.12-alpine3.24`, pinned by digest. deno from `apk` (Alpine 3.24 has 2.7.4; yt-dlp needs ≥2.3.0; the PyPI deno wheel is glibc-only). ffmpeg/ffprobe from `apk`. aria2 stays in the image for `ENABLE_ARIA2`.
- **[Design]** The Dockerfile has a `runtime` target (shipped) and a `test` target on top of it that adds the dev group, so unit tests run against the exact runtime layers.
- **[Design]** The build writes the resolved versions of yt-dlp, curl-cffi and kurigram from `uv.lock` into OCI image labels (used by the drift check).
- **[Design]** amd64 only (the owner's cluster is x86_64). arm64 can be added later with a native runner.

### 6.13 Tests

- **[Owner]** Unit tests and real-download regression tests gate every update.
- **[Design]** Unit tests (pytest, no network, fake Telegram client, fake yt-dlp where needed), run in the image's `test` target:
  - access guard: allowed/denied/empty list/malformed list/no sender/callback from stranger/owner always allowed; every handler type has a guard;
  - feature switches: each disabled feature is unreachable;
  - error classifier: table of pinned yt-dlp and observed server strings → expected kind, including the ordering traps;
  - cookies: per-site file chosen by extractor key; missing file → no cookiefile; mounted file never written; expired-cookie detection via `cookiejar`;
  - impersonation available inside the image;
  - proxy order: fallback only on `blocked`; pinned site never falls back; host check before each attempt; IPv6, NAT64, IPv4-mapped and own-public-IP addresses refused;
  - owner notices: once per (site, kind) per day across a simulated restart;
  - size guard: unknown-size overflow aborts; over-limit file retried lower, then refused before upload;
  - fakeredis cache shared across jobs; cache key includes SponsorBlock;
  - log redaction including tracebacks;
  - no Cyrillic left in `src/` (grep test);
  - config parsing: `AUTHORIZED_USER`/`OWNER`/`PROXY_EXITS`/`PROXY_PIN`/`OWN_PUBLIC_IPS`.
- **[Design]** Regression tests (real network, real downloads, run from the home network inside the exact image under test, **with the production security context**: `docker run --read-only --user <uid>:<gid> --tmpfs /tmp:size=<n> --cap-drop=ALL --security-opt no-new-privileges`, on a Docker network that cannot reach private ranges):
  - links: one long YouTube video, one YouTube Short, one TikTok, one Instagram reel, each from an official account. Candidates *(observed cookie-less with `--simulate`, 2026-11-14, yt-dlp 2026.08.19)*: `youtube.com/watch?v=jNQXAC9IVRw`, `youtube.com/shorts/Hb3rmh-_FMw`, `tiktok.com/@tiktok/video/7525846462563929375`, `instagram.com/reel/Chunk8-jurw/`;
  - Instagram runs cookie-less. A run with cookies is added only if the owner sets up a separate Instagram test account; production cookies never go to the regression host;
  - checks per link: a file is produced; `ffprobe` finds a video stream with codec H.264, an audio stream, duration > 0 (except Instagram, which may report none); size under the limit. With the H.264-first sort all four links picked H.264 *(observed 2026-11-14, `--simulate`, yt-dlp 2026.08.19)*, but the cookie-less Instagram pick reported **no audio codec**; whether the merged Instagram file has sound must be confirmed on the first real run before the audio check applies to Instagram;
  - one real upload of the smallest result through a separate **test bot** to a test chat (catches kurigram upload breakage); the regression host holds only the test bot token and its `APP_ID`/`APP_HASH`;
  - a test whose link is `unavailable` reports "link gone, replace it" separately from "downloader broken", so a deleted video does not look like a yt-dlp regression;
  - kept small on purpose: every run uses the same home IP as the production bot and spends its reputation with the sites.

### 6.14 Update and release pipeline

This is the target shape after the owner says "publish". Before that, see slices 1-4 in section 7 and Q3.

- **[Owner]** Each new stable release of a dependency becomes a PR; tests gate it; green PRs ship.
- **[Design]** Dependabot:
  - `uv` ecosystem, daily. yt-dlp is its own PR with no cooldown (site fixes are urgent); every other uv package is grouped into one PR with the default cooldown. This keeps lock conflicts and real-download reruns down and stops a stuck PR from blocking yt-dlp.
  - `docker` ecosystem with `ignore` for Python minor and major updates (they would break `requires-python`). Alpine minor bumps (which change deno and ffmpeg) are a manual, owner-reviewed PR; the weekly job reports when a newer `3.12-alpineX` tag exists.
  - `github-actions` ecosystem, grouped, keeping actions pinned by SHA.
  - Auto-merge only for `uv` PRs. `docker` and `github-actions` PRs wait for an owner click.
  - Dependabot and scheduled workflows are switched on by hand in the repo settings.
- **[Design]** GitHub Actions on every PR from a branch of this repository (never from forks): check out the PR **head** commit, build the image, run the unit tests in the `test` target, push the `runtime` image to the registry as `sha-<head sha>`. Nothing is built on push to `main`. Workflows declare minimal `permissions`; no workflow has `statuses: write`; no `pull_request_target`.
- **[Design]** Home Jenkins runs the regression tests:
  - it learns about PRs by **polling** GitHub for branches in our own repository only; it never builds PRs from forks;
  - its pipeline definition lives in Jenkins, not in the repo, in a folder whose only credentials are the test bot token, its API ID/hash and the status token;
  - it posts a `regression` commit status as `pending`, waits up to 60 minutes for `sha-<head sha>` to exist (a missing image is pending, not failure), runs the suite, then posts success or failure with a fixed description ("passed", "downloader broken", "link gone") and no `target_url`. Details go to the owner by the test bot;
  - the status token is a fine-grained token limited to commit statuses on this one repository, with an expiry date and a reminder.
- **[Design]** Branch protection on `main`: required checks `unit` and `regression`, **branches must be up to date before merging**, squash merge only. A PR behind `main` is rebased and re-tested.
- **[Design]** Promotion: a `promote` workflow runs every 15 minutes and on demand (it does not rely on the merge event, which a `GITHUB_TOKEN`-driven auto-merge does not raise). It takes the newest `main` commit, finds the PR head that was tested, checks that the trees are identical (`git rev-parse <sha>^{tree}`), and copies that exact digest to `stable` and `YYYY.MM.DD-<short sha>` with `docker buildx imagetools create` (no rebuild). If the trees differ, it promotes nothing and tells the owner. No other workflow can write `stable`.
- **[Design]** Deploy: Keel in the cluster polls `stable` (`keel.sh/policy: force`, `keel.sh/match-tag: "true"`, `keel.sh/trigger: poll`) and the container uses `imagePullPolicy: Always`, so a moved tag really pulls the new digest.
- **[Design]** A weekly Jenkins job runs the regression suite against the image the cluster is running (it reads the running pod's image digest), plus a drift check from the image labels: if the running yt-dlp or curl-cffi is more than 3 days behind PyPI's latest stable, or a Dependabot PR has been open more than 3 days, the owner is told. The job and the bot's heartbeat both ping the owner's existing uptime monitor as a dead-man's switch.

### 6.15 Kubernetes shape (generic)

- Deployment, 1 replica, `Recreate`, non-root, `fsGroup` set, read-only root filesystem, `automountServiceAccountToken: false`, `imagePullPolicy: Always`, Keel annotations from 6.14.
- Volumes: a small block-storage persistent volume at `/data` (SQLite + session); an `emptyDir` at `/tmp` with `sizeLimit` (6.8); a Secret at `COOKIES_DIR` (read-only).
- Env from a Secret: `BOT_TOKEN`, `APP_ID`, `APP_HASH`, `OWNER`, `AUTHORIZED_USER`, `PROXY_EXITS`, `PROXY_PIN`, `OWN_PUBLIC_IPS`. Plain env: `TMPFILE_PATH`, `HOME`, `XDG_CACHE_HOME`, `DENO_DIR`, `DB_DSN`, feature switches.
- Probes from 6.8. Resources: request equals limit, sized from a measured peak (yt-dlp + ffmpeg merge of a large video), not guessed; `ephemeral-storage` limit covers the `/tmp` emptyDir.
- The egress NetworkPolicy from 6.9.
- Concrete manifests live in the owner's private deployment repository. This repo ships an example `deploy/` with placeholders only.

## 7. Build order

Each slice ends in something that runs. Slices 1-4 happen before publishing (where the code and images live meanwhile is Q3).

1. **Hygiene, safety, state (first shippable slice)**: repo clean-up and credit (6.1), access guard (6.2), feature switches (6.3), logging/secrets (6.10), English texts (6.11), uv + pinned image + kurigram 2.2.27 (6.12), the H.264-first format sort and new codec default (6.4), and the state part of 6.8 (`/data` volume, `workdir="/data"`, absolute `DB_DSN`, `/tmp` emptyDir and env). Unit tests for the guard, switches, config, redaction and the no-Cyrillic check. Ends with a manual check in the real container, non-root and read-only: one YouTube, Short and TikTok link each arrives as a video that plays inline in Telegram for an allow-listed user, and a stranger gets the ID reply. (Instagram may still fail here; it is fixed in slice 2.)
2. **Downloads that work everywhere**: playlist refusal and the Google Drive case (6.4), per-site cookies and Instagram via yt-dlp (6.5), error classifier and user replies (6.6 without owner notices), the rest of 6.8 (job executor, size guards, cache fixes, heartbeat), host check (6.9 code part), the matching unit tests.
3. **Owner notices, proxy, restored features**: owner notices including the impersonation check (6.6, 6.4), proxy fallback and pin (6.7), the upstream features restored behind their switches (6.3), their unit tests.
4. **Regression and deployment at home**: regression suite (6.13), a Jenkins job running it against a locally built image, the weekly job and drift check, Kubernetes manifests with probes, NetworkPolicy and router rule (private repo), manual deploy by digest.
5. **Go public** (only when the owner says so): review `docs/` and the commit history for private details; create the GitHub repo, enable Actions, Dependabot, branch protection and auto-merge, the promote workflow; push images and make the registry package public (the image holds no secrets, so the cluster and Jenkins need no pull credentials); switch the Deployment to `stable` with Keel.

## 8. Left to the builder

- Exact English wording of `/help` and settings texts (plain, short; reviewed by the owner in the slice-1 PR).
- Internal module layout for the guard, classifier, cookie and proxy helpers.
- The exact quality ladder steps and retry-lower policy details.
- Queue message wording and progress update rate.
- Test framework details (pytest layout, fixtures).
- Whether to keep `debounce` or replace the global progress-edit lock.
- SIGTERM handling (editing in-flight progress messages to "restarting, send the link again").

## 9. Open questions for the owner

Q1. Answered: restore from upstream and switch off (decision 13, 6.3).

Q2. Answered: the owner's GitHub account (decision 14, 6.1).

Q3. Until you say "publish", where do the code and images live? Either a private GitHub repository and private registry package (the real pipeline gets built and tested early; flipping to public later publishes the whole history), or only this machine and the home network (slices 1-4 use local builds and manual deploys; the GitHub pipeline is first exercised in slice 5).

## 10. Private deployment note (outside this repository)

Kept next to the owner's private infrastructure notes, never committed here: real `OWNER`/`AUTHORIZED_USER` IDs, the proxy exits and which ones are distinct, the cluster's namespace/storage/NetworkPolicy specifics, the router rule against hairpin to the home's own public IP, the Jenkins job and its credentials, the alerting channel, Keel settings, the test bot and test chat, a leak runbook (BotFather `/revoke`, delete the session file), and the deployment checklist (BotFather: disable groups; each owner sends `/start` once; proxy ACLs).

## 11. Calls made while writing and reviewing (for the owner to check)

These change something agreed in the conversation, because research showed the agreed version would not work:
- **One fallback exit, not two.** Direct egress and one of the two home proxy exits are the same line and IP, so the list is direct plus one other home exit (6.7).
- **One cookies file per site**, not one file for all sites, so YouTube's logged-in mode does not switch on just because Instagram cookies exist (6.5).
- **uv replaces PDM.** Dependabot cannot update PDM's lock file, so "Dependabot opens a PR per release" only works after the switch (6.12).
- **Payments, quotas, rclone and ffmpeg extras are restored from upstream and switched off; channel subscriptions are not**, because upstream itself deleted them (6.3).
- **The bot messages the owner itself**; the old Telegram monitor bot no longer exists (6.6).
- **Keel deploys automatically** from the `stable` tag after promotion (6.14); deploys today are manual.
- **Default codec changes from VP9 to H.264-first** so videos play inline in Telegram (6.4).

Other calls:
- No re-encoding; non-H.264 sources are sent as they are (6.4).
- Cookies come from spare accounts, never personal ones; regression runs Instagram without cookies unless a separate test account exists (6.5, 6.13).
- Auto-merge only for Python dependency PRs; base-image and GitHub-action PRs wait for your click (6.14).
- Every other Python package is grouped into one daily PR; yt-dlp stays its own PR with no waiting period (6.14).
- Promotion runs on a 15-minute schedule and only ships an image whose tested tree equals `main` (6.14).
- The router blocks the cluster from reaching the home's own public IP (6.9).
- No existing bot instance or data to migrate; the bot starts with a fresh database.
- The owner-side infrastructure facts from v1 moved to the private note.
