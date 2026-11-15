# ytdlbot fork Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Katze-942/ytdlbot into an English, allow-listed, one-container Telegram bot that returns videos for YouTube/Shorts/TikTok/Instagram links, with safe defaults and a tested update pipeline.

**Architecture:** Keep the existing kurigram bot structure (`src/main.py` handlers, `src/engine/*` downloaders, `src/database/*`, `src/config/*`). Add small focused modules for the new concerns (access guard, error classifier, cookies, proxy, host check, notices, jobs, redaction). Dependencies move from PDM to uv; the image is a two-target Dockerfile (`runtime`, `test`).

**Tech Stack:** Python 3.12, kurigram 2.2.27 (imported as `pyrogram`), yt-dlp (latest stable) with curl-cffi, SQLAlchemy + SQLite, fakeredis, pytest, uv, Docker (python:3.12-alpine3.24), GitHub Actions, Dependabot.

**Spec:** `docs/superpowers/specs/2026-11-14-ytdlbot-fork-design.md` (read it; section numbers below refer to it).

## Global Constraints

- Python `requires-python = ">=3.12,<3.13"`. Local commands use `uv` (`uv sync`, `uv run pytest -q`); uv may download CPython 3.12 locally, but the Dockerfile sets `UV_PYTHON_DOWNLOADS=0`.
- Dependencies: `yt-dlp[default,curl-cffi]` (latest stable, no pre-releases), `curl-cffi` declared directly with no bound of our own, `kurigram[fast]==2.2.27`. No `yt-dlp-ejs` line, no `tgcrypto`, no `PyMySQL`. Dev group: `pytest`, `black`.
- All user-facing text is English and lives in `src/config/constant.py`. No Cyrillic anywhere in `src/` (a test enforces it).
- No private details in the repository: no IP addresses, Telegram IDs, hostnames or proxy URLs of the owner. Examples use placeholders (`123456789`, `http://proxy.example:8080`).
- Never send exception text, paths, hostnames or proxy details to Telegram users. Never log secrets (bot token, `APP_HASH`, cookie values, proxy credentials).
- Unit tests make no network calls and do not connect to Telegram.
- Every source file a task modifies for the first time gets one line under its existing header: `# Modified 2026 by megabitus98 (fork): <what changed>`. Existing `__author__` lines and the "By @BennyThink" banner stay.
- Commits: the clone's local git identity is already set; plain commit messages; no `Co-Authored-By` or AI attribution lines. Commit only on the current working branch; never push (the controller pushes).
- Handlers: `src/main.py` keeps plain handler functions (no decorators on a module-level client) and exposes `handler_table() -> list[HandlerSpec]`, where `HandlerSpec = tuple[type, Callable, Filter | None, int]` (handler class, callback, filters, group). `create_app() -> Client` builds the client and registers every entry with `app.add_handler(cls(callback, filters), group)`. Tests about which handlers exist inspect `handler_table()`, never `app.dispatcher.groups` (kurigram may fill that asynchronously; check the installed source in `.venv`).
- Repo-level tests (README, NOTICE, `.github/`, git history) live in `tests/repo/` and run on a full checkout only (`uv run pytest -q tests/repo`); `.dockerignore` excludes `tests/repo`, so the image's `test` target runs everything else.
- Docker safety: never run `docker system prune`, `docker image prune`, `docker builder prune` or any other prune; remove only this project's own images and containers, by name (`ytdlbot:*`, containers you started with `--name ytdlbot-*` or `--rm`).
- Check kurigram and yt-dlp behaviour against the installed source in `.venv`, not from memory. No requests to real websites in tasks other than Task 15's single regression run.
- Tests live in `tests/` at the repo root; `pyproject.toml` sets `[tool.pytest.ini_options] pythonpath = ["src"]`, `testpaths = ["tests"]`. `tests/conftest.py` sets safe env defaults (`APP_ID=1`, `APP_HASH=test`, `BOT_TOKEN=1:test`, `OWNER=1`, `AUTHORIZED_USER=1,2`, `DATA_DIR`/`TMPFILE_PATH`/`DB_DSN` under a temp dir) before any app module is imported.

## Review Focus

1. A link with other text around it ("look at this https://youtu.be/x lol", or a share-sheet message with a title line) must download the first http(s) URL in the message. Test: Task 3 `test_extract_first_url`.
2. With search off, plain text without a link must get "Send me a link to a video." and nothing else. Test: Task 3 `test_text_without_link_gets_hint`.
3. An allow-listed user writing in a group while `ENABLE_GROUPS=false` must be ignored silently (no reply, no download). Test: Task 3 `test_group_message_ignored_when_groups_off`.
4. A stream with unknown total size that keeps growing past the limit must abort that job only, with the "too large" reply. Test: Task 11 `test_unknown_size_overflow_aborts`.
5. Short-link hosts (`youtu.be`, `vm.tiktok.com`, `instagr.am`) must pass the host check when they resolve to public addresses. Test: Task 11 `test_short_link_hosts_pass`.

---

## Slice 1: hygiene, safety, state

### Task 1: uv, Docker image, test scaffold, kurigram 2.2.27, self-check

**Files:**
- Modify: `pyproject.toml`, `Dockerfile`, `.dockerignore`, `.gitignore`, `src/engine/base.py` (upload fallback loop, today lines 252-282), `src/main.py` (entry point)
- Create: `uv.lock`, `tests/conftest.py`, `tests/test_scaffold.py`, `src/selfcheck.py`
- Delete: `pdm.lock`, `requirements.txt`, `pre-push.py`, `.pdm-python`, `src/test.py`, `youtube-cookies.txt`

**Interfaces:**
- Produces: `selfcheck.run_selfcheck() -> dict[str, object]` with keys `yt_dlp`, `curl_cffi`, `kurigram` (version strings), `impersonation` (bool, from `YoutubeDL()._impersonate_target_available(ImpersonateTarget())`), `data_writable`, `tmp_writable` (bool), `ok` (bool, all checks true). `python main.py --self-check` prints that dict as JSON and exits 0 if `ok` else 1, without creating the Telegram client.
- Produces: Dockerfile targets `runtime` (shipped) and `test` (runtime + dev group + `tests/` without `tests/repo`, `CMD ["python", "-m", "pytest", "-q", "/app/tests"]`).
- Produces: `main.handler_table()` and `main.create_app()` as described in Global Constraints; importing `main` creates no client.

- [ ] **Step 1:** Rewrite `pyproject.toml` for uv (project table, `requires-python`, dependencies exactly as in Global Constraints plus `SQLAlchemy`, `fakeredis`, `redis`, `requests`, `filetype`, `beautifulsoup4`, `psutil`, `python-dotenv`, `ffmpeg-python`, `tqdm`; dev group; pytest options). Delete the PDM files listed above. Run `uv lock` and `uv sync`. Expected: lock resolves yt-dlp ≥ 2026.10.26 and kurigram 2.2.27.
- [ ] **Step 2: Write the failing tests** in `tests/test_scaffold.py`:
  - `test_imports`: `import yt_dlp, pyrogram, curl_cffi` succeed and `pyrogram.__version__ == "2.2.27"`.
  - `test_selfcheck_reports_versions`: `run_selfcheck()` returns the keys above; `impersonation is True` (curl-cffi installed).
  - `test_selfcheck_flags_unwritable_dir(tmp_path, monkeypatch)`: with `DATA_DIR` pointing at a read-only directory, `data_writable is False` and `ok is False`.
  - `test_import_main_creates_no_client`: `import main` succeeds and `main.handler_table()` returns a non-empty list without any network or client construction.
- [ ] **Step 3:** Run `uv run pytest -q tests/test_scaffold.py`. Expected: FAIL (`selfcheck` missing).
- [ ] **Step 4:** Implement `src/selfcheck.py` and the `--self-check` branch at the top of `src/main.py`'s `__main__` block (before the client is built; move client construction into a `create_app()` call made only when running the bot, so importing `main` in tests does not need network).
- [ ] **Step 5:** Rewrite the upload fallback loop in `src/engine/base.py` for kurigram 2.2.27, where `save_file` raises on failure: try the send methods in order, catch exceptions per attempt, log them (redacted later in Task 5), stop on first success, raise one error if all fail. Remove the "try again with /direct" text.
- [ ] **Step 6:** Rewrite `Dockerfile`: base `python:3.12-alpine3.24@sha256:<multi-arch index digest>` (the top-level "Digest" from `docker buildx imagetools inspect python:3.12-alpine3.24`, not a per-platform digest; local Docker is arm64, CI is amd64), `apk add ffmpeg deno aria2`, uv copied from `ghcr.io/astral-sh/uv:<pinned version>`, `ENV UV_PYTHON_DOWNLOADS=0`, `uv sync --locked --no-dev` into a venv on PATH, non-root user `app` (uid 10001), `WORKDIR /app`, `COPY src /app`, labels `org.opencontainers.image.source` plus `io.ytdlbot.yt-dlp`, `io.ytdlbot.curl-cffi`, `io.ytdlbot.kurigram` from build args filled from `uv.lock`. `test` target adds the dev group and copies `tests/`. Update `.dockerignore` and `.gitignore` as in spec 6.1.
- [ ] **Step 7:** Run `uv run pytest -q` (PASS), then `docker build --target test -t ytdlbot:test . && docker run --rm ytdlbot:test` (PASS) and `docker build --target runtime -t ytdlbot:dev . && docker run --rm --read-only --tmpfs /tmp -e DATA_DIR=/tmp/data ytdlbot:dev python main.py --self-check` (exit 0, JSON with `"impersonation": true`).
- [ ] **Step 8:** Commit: `build: move to uv, two-target image, kurigram 2.2.27, self-check`.

### Task 2: Config parsing and feature switches

**Files:**
- Modify: `src/config/config.py`, `src/config/__init__.py`, `src/main.py` (uses of `OWNER`, `AUTHORIZED_USER`, search, `/direct`, `/spdl`, `/stats`, `/ytdl`, m3u8)
- Test: `tests/test_config.py`, `tests/test_switches.py`

**Interfaces:**
- Produces in `config.config`: `class ConfigError(Exception)`; `parse_id_list(raw: str | None, name: str) -> frozenset[int]` (strip blanks, skip empty items, raise `ConfigError` naming the variable on a non-integer); `parse_bool(raw: str | None, default: bool) -> bool` (accepts true/false/1/0/yes/no, case-insensitive; raise `ConfigError` otherwise); constants `AUTHORIZED_USERS`, `OWNERS` (frozensets), `ALLOWED_USERS = AUTHORIZED_USERS | OWNERS`; booleans `ENABLE_SEARCH`, `ENABLE_DIRECT`, `ENABLE_ARIA2`, `ENABLE_SPDL`, `ENABLE_STATS`, `ENABLE_GROUPS`, `M3U8_SUPPORT` (all default False); `TG_NORMAL_MAX_SIZE` (bytes, from env MiB, default 2000); `WORKERS` default 16; `DATA_DIR` default `/data`; `TMPFILE_PATH` default `/tmp/ytdlbot`; `DB_DSN` default `sqlite:///{DATA_DIR}/ytdlbot.db`; `PREFERRED_AUDIO_LANG` default `""`.
- The old names `OWNER`/`AUTHORIZED_USER` disappear from code; env var names stay `OWNER` and `AUTHORIZED_USER`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`:
  - `test_parse_id_list_basic`: `parse_id_list(" 1, 2 ,,3,", "X") == frozenset({1, 2, 3})`.
  - `test_parse_id_list_empty_is_empty`: `parse_id_list("", "X") == frozenset()` and `parse_id_list(None, "X") == frozenset()`.
  - `test_parse_id_list_rejects_names`: `parse_id_list("1,@bob", "AUTHORIZED_USER")` raises `ConfigError` whose message contains `AUTHORIZED_USER`.
  - `test_parse_bool`: `parse_bool("TRUE", False) is True`, `parse_bool(None, True) is True`, `parse_bool("maybe", False)` raises `ConfigError`.
  - `test_tg_max_size_from_mib(monkeypatch)`: reloading config with `TG_NORMAL_MAX_SIZE=10` gives `10 * 1024 * 1024`.
- [ ] **Step 2: Write the failing tests** in `tests/test_switches.py` (drive handlers with fake client/message objects; assert the downloader entry functions are not called):
  - `test_direct_disabled_by_default`, `test_spdl_disabled_by_default`, `test_stats_disabled_by_default`, `test_search_disabled_by_default`: each command/plain text gets the reply `BotText.disabled` ("This feature is turned off.") and starts no download.
  - `test_m3u8_blocked_when_off`: a URL ending in `.m3u8` with `M3U8_SUPPORT=False` gets `BotText.disabled` and no download (today the return value is discarded, `src/main.py:327-328,354`).
  - `test_stats_owner_only_when_enabled`: with `ENABLE_STATS=True`, a non-owner allowed user gets `BotText.disabled`.
- [ ] **Step 3:** Run `uv run pytest -q tests/test_config.py tests/test_switches.py`. Expected: FAIL.
- [ ] **Step 4:** Implement the config functions and constants, and gate the handlers in `src/main.py`. Remove dead env names from config (`RATE_LIMIT` goes; `CAPTION_URL_LENGTH_LIMIT` becomes a module constant `150`).
- [ ] **Step 5:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 6:** Commit: `feat: strict config parsing and env feature switches`.

### Task 3: Access guard, link extraction, groups

**Files:**
- Create: `src/utils/access.py`
- Modify: `src/main.py` (remove `private_use`, register guards, anchor callback regexes, save settings by `from_user.id`, extract URL), `src/config/constant.py` (`BotText.denied`, `BotText.no_link`)
- Test: `tests/test_access.py`, `tests/test_links.py`

**Interfaces:**
- Produces in `utils.access`: `class DenialThrottle` with `should_reply(user_id: int, now: float) -> bool` (True at most once per 24 h per ID; in-memory dict); `guard_message(client, message) -> None` and `guard_callback(client, callback_query) -> None` (call `.stop_propagation()` when the sender is not allowed; return None otherwise); `register_guards(app) -> None` (adds both at `group=-1`).
- Produces in `utils`: `extract_first_url(text: str | None) -> str | None` (first `http://` or `https://` URL; strips trailing `)`, `.`, `,`).
- Exact copy: `BotText.denied = "You don't have access to this bot. Your Telegram ID is {user_id}. Send it to the owner to get access."`; `BotText.no_link = "Send me a link to a video."`.

- [ ] **Step 1: Write the failing tests** in `tests/test_access.py` (fake objects via `types.SimpleNamespace`; a fake `stop_propagation` that raises `pyrogram.StopPropagation`):
  - `test_allowed_user_passes`: user 2 (in `AUTHORIZED_USER=1,2`) in a private chat → guard returns None, no reply.
  - `test_stranger_gets_id_reply_once`: user 99 → `StopPropagation` raised; reply text equals `BotText.denied.format(user_id=99)`; a second message within 24 h raises again but sends no reply.
  - `test_owner_always_allowed`: user in `OWNER` but not in `AUTHORIZED_USER` passes.
  - `test_empty_list_denies_everyone(monkeypatch)`: with both lists empty, user 1 is denied.
  - `test_no_sender_ignored`: `from_user=None` → `StopPropagation`, no reply.
  - `test_stranger_callback_alert`: callback from user 99 → `answer(..., show_alert=True)` called and `StopPropagation` raised.
  - `test_group_message_ignored_when_groups_off`: allowed user 2 in a group chat with `ENABLE_GROUPS=False` → `StopPropagation`, no reply.
  - `test_every_handler_type_has_guard`: for every handler class used in `handler_table()` at group ≥ 0 (`MessageHandler`, `CallbackQueryHandler`, …) there is an entry of the same class at group -1 whose callback is a guard.
  - `test_settings_saved_by_user_id`: a settings callback from user 2 in chat 555 stores the setting for user 2.
  - `test_callback_regex_anchored`: callback data `"x1080p"` matches no settings handler.
- [ ] **Step 2: Write the failing tests** in `tests/test_links.py`:
  - `test_extract_first_url`: `extract_first_url("look https://youtu.be/abc, ok") == "https://youtu.be/abc"`; `extract_first_url("Title\nhttps://www.instagram.com/reel/X/?igsh=1") == "https://www.instagram.com/reel/X/?igsh=1"`; `extract_first_url("no link") is None`.
  - `test_text_without_link_gets_hint`: plain text without a URL (search off) → reply `BotText.no_link`, no download.
- [ ] **Step 3:** Run the two test files. Expected: FAIL.
- [ ] **Step 4:** Implement `utils/access.py`, `extract_first_url`, register guards, remove `private_use`, switch the download handler to `extract_first_url`, anchor callback regexes (`^(...)$`), map callback data through dicts, save settings under `callback_query.from_user.id`.
- [ ] **Step 5:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 6:** Commit: `feat: one fail-closed access guard for every update`.

### Task 4: State on /data, SQLite settings, temp dir safety

**Files:**
- Modify: `src/database/model.py` (engine, `init_user`), `src/main.py` (`Client(..., workdir=DATA_DIR)`, startup purge), `src/config/config.py`
- Create: `src/database/migrate.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `database.model.make_engine(dsn: str) -> Engine` (for SQLite file DSNs: `pool_size=5`, `connect_args={"timeout": 30}`, WAL enabled on connect via `PRAGMA journal_mode=WAL`); `init_user(uid: int) -> None` is idempotent under concurrency (insert-or-ignore); `database.migrate.ensure_columns(engine, table: str, columns: dict[str, str]) -> list[str]` (adds missing columns with `ALTER TABLE ... ADD COLUMN`, returns added names); `config.check_paths(data_dir: str, tmp_dir: str) -> None` raises `ConfigError` if `tmp_dir` is inside `data_dir`.

- [ ] **Step 1: Write the failing tests** in `tests/test_state.py`:
  - `test_wal_enabled(tmp_path)`: an engine from `make_engine(f"sqlite:///{tmp_path}/t.db")` reports `PRAGMA journal_mode` = `wal`.
  - `test_init_user_concurrent(tmp_path)`: 8 threads call `init_user(42)` at once; no exception; exactly one row.
  - `test_ensure_columns_adds_missing(tmp_path)`: on a table without column `sponsorblock`, `ensure_columns` adds it and returns `["sponsorblock"]`; a second call returns `[]`.
  - `test_tmp_inside_data_refused`: `check_paths("/data", "/data/tmp")` raises `ConfigError`; `check_paths("/data", "/tmp/ytdlbot")` returns None.
  - `test_client_workdir_is_data_dir`: `create_app()` builds the client with `workdir == DATA_DIR`.
- [ ] **Step 2:** Run `uv run pytest -q tests/test_state.py`. Expected: FAIL.
- [ ] **Step 3:** Implement. Engine creation stays at import of `database.model` but uses `make_engine(DB_DSN)`; `check_paths` runs at startup before the purge of `TMPFILE_PATH`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: persistent state under DATA_DIR with WAL SQLite`.

### Task 5: Log redaction and generic user errors

**Files:**
- Create: `src/utils/redact.py`
- Modify: `src/config/__init__.py` (logging setup), `src/engine/generic.py` (remove the options log at today's line 155 and `verbose: True` at line 80), `src/main.py` and `src/engine/*.py` (every reply that interpolates an exception: `src/main.py:275,295,316,370,373`, `src/engine/direct.py`, `pixeldrain.py`, `krakenfiles.py`, `instagram.py`), `src/config/constant.py` (`BotText.error`)
- Test: `tests/test_redact.py`

**Interfaces:**
- Produces: `utils.redact.redact(text: str) -> str` (replaces the bot token, `APP_HASH`, any `scheme://user:pass@` credentials and values of `sessionid=`/`csrftoken=` with `***`); `class RedactingFormatter(logging.Formatter)` whose `format()` returns `redact(super().format(record))` (tracebacks included). Root logging uses it; `httpx`, `httpcore`, `urllib3` loggers set to WARNING. `AUTHORIZED_USER` is no longer logged.
- Exact copy: `BotText.error = "Something went wrong with this download."`

- [ ] **Step 1: Write the failing tests** in `tests/test_redact.py`:
  - `test_redact_token_and_proxy`: `redact("bot 1:test via http://u:p@proxy.example:8080")` contains neither `1:test` nor `u:p@`.
  - `test_formatter_redacts_traceback(caplog-free: use a StreamHandler on io.StringIO)`: logging an exception whose message contains `http://u:secret@proxy.example:8080` writes output without `secret`.
  - `test_no_exception_text_to_users`: a handler whose downloader raises `RuntimeError("http://10.0.0.1 failed")` replies exactly `BotText.error`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement and replace every exception-interpolating reply with `BotText.error` (the classifier in Task 8 refines this).
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `fix: redact secrets in logs and stop sending errors to users`.

### Task 6: English texts, audio language, H.264-first formats

**Files:**
- Modify: `src/config/constant.py`, `src/main.py`, `src/engine/base.py`, `src/engine/generic.py`, `src/engine/direct.py`, `src/engine/krakenfiles.py`, `src/engine/pixeldrain.py`, `src/database/model.py` (default codec)
- Test: `tests/test_texts.py`, `tests/test_formats.py`

**Interfaces:**
- Produces: `engine.generic.build_format_options(quality: str, vcodec: str, send_as: str, audio_lang: str) -> dict` returning at least `format` and `format_sort` and `merge_output_format`. With `vcodec == "auto"` the sort starts `["vcodec:h264", "res", "acodec:m4a"]` and `merge_output_format == "mp4"`; `audio_lang` empty adds no `[language=...]` filter, otherwise filters for that language with fallback to any.
- Default codec setting becomes `"auto"` (new enum value; keep `vp9`, `avc1`, `av01` selectable).

- [ ] **Step 1: Write the failing tests**:
  - `tests/test_texts.py::test_no_cyrillic_in_src`: no file under `src/` contains a character in U+0400–U+04FF.
  - `tests/test_texts.py::test_about_credits_upstream`: `BotText.about` contains `github.com/tgbot-collection/ytdlbot` and `github.com/Katze-942/ytdlbot` and no `t.me/` link.
  - `tests/test_formats.py::test_auto_prefers_h264`: `build_format_options("1080p", "auto", "video", "")["format_sort"][0] == "vcodec:h264"`.
  - `tests/test_formats.py::test_no_russian_audio_by_default`: no `language=ru` substring in the `format` string for `audio_lang=""`.
  - `tests/test_formats.py::test_audio_lang_filter`: `audio_lang="en"` puts `[language=en]` in `format` with a fallback alternative after it.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Translate every Russian string (153 lines; reuse upstream English from `git diff upstream/master...HEAD` where it exists), make "an error occurred" one constant, rewrite `/help` from current behaviour, `/start` = one greeting line pointing to `/help`, `/about` = credit to both upstream repos (GitHub links only) and "Apache-2.0". Implement `build_format_options` and use it in `_setup_formats`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: English texts and H.264-first format choice`.

### Task 7: Repository hygiene and credit

**Files:**
- Delete: `.github/FUNDING.yml`, `assets/USD.png`, `assets/CNY.png`, `assets/tron.png`, `assets/1.jpeg`, `assets/instagram.png`, `.github/workflows/upgrade.yml`, `.github/workflows/builder.yaml`, `.github/workflows/codeql-analysis.yml`, `.github/dependabot.yml` (replaced in Task 16)
- Create: `NOTICE`
- Modify/rewrite: `README.md`, `.env.example`, `docker-compose.yml` (one service, SQLite, volumes for `/data` and `/tmp`, no Redis/MySQL), `AGENTS.md`, `CLAUDE.md`
- Test: `tests/repo/test_repo.py` (repo-level group; runs with `uv run pytest -q tests/repo`)

- [ ] **Step 1: Write the failing tests** in `tests/repo/test_repo.py`:
  - `test_no_funding_or_payment_assets`: none of the deleted paths exist.
  - `test_notice_names_both_upstreams`: `NOTICE` contains `tgbot-collection/ytdlbot` and `Katze-942/ytdlbot`.
  - `test_readme_credit_first`: the first 15 lines of `README.md` contain both upstream links and "Not affiliated".
  - `test_env_example_has_no_dead_vars`: `.env.example` contains none of `RATE_LIMIT`, `CAPTION_URL_LENGTH_LIMIT`, `REDIS_HOST=redis`, `mysql`.
  - `test_modified_files_carry_notice`: every `src/**/*.py` file changed since `0d5bfcd` (via `git diff --name-only 0d5bfcd -- src`) contains `Modified 2026 by megabitus98 (fork)`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Make the changes. README: credit paragraph (spec 6.1, verbatim), what the bot does, configuration table of every env var with default, "Changes from upstream" written from the code, how to run locally with docker compose. `.env.example`: every env var with placeholder values only.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `chore: credit upstream, remove third-party payment material and stale files`.

## Slice 2: downloads that work everywhere

### Task 8: Error classifier and per-kind replies

**Files:**
- Create: `src/engine/errors.py`
- Modify: `src/main.py`, `src/engine/base.py` (catch and classify), `src/config/constant.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Produces: `Kind = Literal["login_required", "blocked", "unavailable", "other"]`; `classify(err: BaseException) -> Kind` (walks `.cause`, `DownloadError.exc_info[1]`, `__cause__`, `__context__`; types first: `GeoRestrictedError` → unavailable, `HTTPError` with status 403/429 and `ProxyError` → blocked; then regexes in order blocked, unavailable, login_required); `user_message(kind: Kind, site: str) -> str`.
- Exact copy (`{site}` is the display name, e.g. "Instagram"): login_required `"{site} needs a login for this video. The owner has been told."`; blocked `"{site} is blocking downloads right now. The owner has been told. Try again later."`; unavailable `"This video is private, deleted or not available here."`; other `BotText.error`.

- [ ] **Step 1: Write the failing tests** in `tests/test_errors.py` as one parametrized table `test_classify_strings` (wrap each string in `yt_dlp.utils.ExtractorError(msg, expected=True)` inside a `DownloadError`), labelled source/observed in comments:
  - blocked: `"Sign in to confirm you’re not a bot. This helps protect our community."`, `"Video unavailable. This content isn’t available, try again later. The current session has been rate-limited by YouTube for up to an hour."`, `"The webpage request was redirected to the login page. You have exceeded the rate-limit for accessing posts anonymously"`, `"Your IP address is blocked from accessing this post"`, `"All player responses are invalid. Your IP is likely being blocked by Youtube"`, `"Unexpected response from webpage request"`, `"Instagram sent an empty media response."`, `"[download] Got error: HTTP Error 403: Forbidden. Giving up after 10 retries"` (plain `DownloadError` with no exc_info);
  - unavailable: `"Private video. If the owner of this video has granted you access, please sign in."`, `"Video unavailable. This video is not available"`, `"This content is only available for registered users who follow this account"`, `"There is no video in this post"`, `"You do not have permission to view this post. Log into an account that has access"`, `"Join this channel to get access to members-only content like this video, and other exclusive perks."`;
  - login_required: `"Sign in to confirm your age. This video may be inappropriate for some users."`, `"Restricted Video: You must be 18 years old or over to see this video"`, `"TikTok is requiring login for access to this content"`;
  - other: `"Unsupported something odd"`.
  - `test_geo_restricted_is_unavailable`: a `GeoRestrictedError` → unavailable.
  - `test_http_429_cause_is_blocked`: `DownloadError` whose `exc_info[1]` is a yt-dlp `HTTPError` with status 429 → blocked.
  - `test_user_message_copy`: each kind returns the exact copy above.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement and use `user_message(classify(e), site)` for every download failure reply; the traceback goes to the log.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: classify download errors and reply per kind`.

### Task 9: Per-site cookies, Instagram through yt-dlp

**Files:**
- Create: `src/engine/cookies.py`, `src/engine/sites.py`
- Modify: `src/engine/generic.py` (cookie options replace the YouTube-only block at today's lines 138-152), `src/engine/__init__.py` (remove `instagram.com` from `DOWNLOADER_MAP`), `src/config/config.py` (`COOKIES_DIR` default `/cookies`)
- Delete: `src/engine/instagram.py`
- Test: `tests/test_cookies.py`

**Interfaces:**
- Produces: `engine.sites.site_for_url(url: str) -> str` (first suitable non-generic yt-dlp extractor via `ie.suitable(url)`, offline; family name lowercased by prefix: `youtube`, `instagram`, `tiktok`, else the key lowercased; `"generic"` if none); `engine.sites.display_name(site: str) -> str` (`"YouTube"`, `"Instagram"`, `"TikTok"`, else title case).
- Produces: `engine.cookies.cookie_options(cookies_dir: Path, site: str) -> dict` (`{"cookiefile": io.StringIO(text)}` when `<cookies_dir>/<site>.txt` exists and is non-empty, else `{}`; never returns a path); `engine.cookies.instagram_session_present(ydl) -> bool` (`sessionid` among `ydl.cookiejar.get_cookies_for_url("https://www.instagram.com/")`).

- [ ] **Step 1: Write the failing tests** in `tests/test_cookies.py`:
  - `test_site_for_url`: `youtube.com/watch?v=x` → `youtube`; `youtu.be/x` → `youtube`; `instagram.com/reel/x/` → `instagram`; `tiktok.com/@a/video/1` → `tiktok`; `example.com/page` → `generic`.
  - `test_cookie_options_present(tmp_path)`: with `instagram.txt` present, returns a `StringIO` whose value equals the file text.
  - `test_cookie_options_missing(tmp_path)`: no file → `{}`; the directory stays empty afterwards (no file created).
  - `test_mounted_file_never_written(tmp_path)`: after a `YoutubeDL(cookie_options(...))` is created and closed, the file's bytes and mtime are unchanged.
  - `test_instagram_session_detection`: a cookiejar containing `sessionid` for `.instagram.com` → True; without → False.
  - `test_instagram_not_in_spdl_map`: `"instagram.com" not in DOWNLOADER_MAP`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement; the download path picks `site_for_url(url)` once and passes `cookie_options` into each `YoutubeDL`. Keep `POTOKEN` support (YouTube only) in the format the current code uses.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: per-site cookies from memory copies, Instagram via yt-dlp`.

### Task 10: Extract, check, then download

**Files:**
- Modify: `src/engine/generic.py`, `src/main.py` (remove the "contains list" check at today's lines 321-325 and `playlist_items: 1`)
- Test: `tests/test_download_flow.py`

**Interfaces:**
- Produces: `engine.proxy.ydl_proxy(exit: str) -> str` (create `src/engine/proxy.py` with just this: `"direct"` → `""`, any URL unchanged; Task 13 adds the rest of the module).
- Produces: `engine.generic.attempt(url: str, site: str, exit: str, opts: dict, tmpdir: Path) -> dict` — builds one `YoutubeDL` with `opts | {"proxy": ydl_proxy(exit)}`, runs `extract_info(url, download=False)`, raises `RefusedContent` when `_type` is `playlist`, `multi_video` or `url`-to-playlist, or `is_live` is true, then `process_ie_result(info, download=True)` in the same instance, and returns the info dict. `class RefusedContent(Exception)` → reply `"Send a link to a single video, not a playlist, channel or live stream."` (exact copy, `BotText.refused`).
- Google Drive: for `drive.google.com` URLs the format list starts with `"source"` before it is joined with `/`.

- [ ] **Step 1: Write the failing tests** in `tests/test_download_flow.py` (patch `yt_dlp.YoutubeDL` with a fake that records calls):
  - `test_playlist_refused_before_download`: fake `extract_info` returns `{"_type": "playlist"}` → `RefusedContent`, and `process_ie_result` never called.
  - `test_live_refused`: `{"is_live": True}` → `RefusedContent`.
  - `test_single_video_downloads_in_same_instance`: one fake instance receives both `extract_info(download=False)` and `process_ie_result(download=True)`.
  - `test_gdrive_source_first`: for a `drive.google.com` URL the `format` option starts with `source/`.
  - `test_list_in_url_not_refused`: `https://www.youtube.com/watch?v=x&list=y` with a single-video fake result downloads.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement and route `YoutubeDownload._download` through `attempt`.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: refuse playlists after extraction, one instance per attempt`.

### Task 11: Jobs, size guards, cache, heartbeat, host check

**Files:**
- Create: `src/engine/jobs.py`, `src/utils/netcheck.py`, `src/health.py`
- Modify: `src/engine/base.py` (`download_hook`, final size check, cache key), `src/database/cache.py` (one module-level client), `src/main.py` (submit jobs, start heartbeat), `src/config/config.py` (`MAX_PARALLEL_JOBS` default 2, `TMP_BUDGET` bytes default `MAX_PARALLEL_JOBS * 4500 MiB`, `JOB_TIMEOUT` seconds default 2700, `OWN_PUBLIC_IPS` parsed as a frozenset of IP strings)
- Test: `tests/test_jobs.py`, `tests/test_netcheck.py`, `tests/test_cache.py`

**Interfaces:**
- Produces: `engine.jobs.JobQueue(max_parallel: int)` with `submit(fn: Callable[[], None]) -> int` (returns the number of jobs ahead of this one; 0 means it starts now) and `shutdown(wait: bool) -> None`. Queue reply when position > 0: `"Queued, position {n}."` (`BotText.queued`).
- Produces: `utils.netcheck.BlockedHost(Exception)`; `check_url(url: str, own_ips: frozenset[str], resolver=socket.getaddrinfo) -> None` (scheme http/https, host present, IPv4 only, every address `is_global` after unwrapping IPv4-mapped, not in `own_ips`; else raise). Called in `BaseDownloader.__init__` and before every attempt.
- Produces: `engine.jobs.TooLarge(Exception)`; `utils.dir_size(path: Path) -> int`; `download_hook` raises `TooLarge` when `downloaded_bytes > TG_NORMAL_MAX_SIZE` (known or unknown total) or `dir_size(TMPFILE_PATH) > TMP_BUDGET`; after post-processing, a file over `TG_NORMAL_MAX_SIZE` triggers one retry with the next lower quality, then `TooLarge`. Reply: `"This video is too large for Telegram (over 2 GB)."` (`BotText.too_large`).
- Produces: `database.cache.get_cache() -> redis.Redis` returning one shared instance (fakeredis when `REDIS_HOST` is unset); cache key includes the SponsorBlock setting.
- Produces: `health.start_heartbeat(client, path: Path = Path("/tmp/healthy"), interval: int = 60) -> threading.Thread` (daemon; calls `client.get_me()` then touches the file); `python health.py` exits 0 if the file is younger than 180 s, else 1.

- [ ] **Step 1: Write the failing tests**:
  - `tests/test_jobs.py::test_positions`: with `max_parallel=1`, three blocking jobs submitted return positions 0, 1, 2; all complete after release.
  - `tests/test_jobs.py::test_unknown_size_overflow_aborts`: `download_hook({"status": "downloading", "downloaded_bytes": limit + 1})` (no total) raises `TooLarge`.
  - `tests/test_jobs.py::test_tmp_budget_abort(tmp_path)`: files totalling more than `TMP_BUDGET` under `TMPFILE_PATH` → `TooLarge`.
  - `tests/test_jobs.py::test_oversized_result_retries_lower_then_refuses`: a fake downloader producing an oversized file twice → second call used the next lower quality; final reply `BotText.too_large`.
  - `tests/test_netcheck.py::test_private_and_loopback_refused`: `127.0.0.1`, `10.1.2.3`, `192.168.1.1`, `100.64.0.1`, `169.254.1.1` → `BlockedHost`.
  - `tests/test_netcheck.py::test_ipv6_and_nat64_refused`: an AAAA-only host, `64:ff9b::a00:1` and `::ffff:10.0.0.1` → `BlockedHost`.
  - `tests/test_netcheck.py::test_own_public_ip_refused`: resolver returns `203.0.113.7`, `own_ips={"203.0.113.7"}` → `BlockedHost`.
  - `tests/test_netcheck.py::test_short_link_hosts_pass`: `youtu.be`, `vm.tiktok.com`, `instagr.am` resolving to `142.250.0.1` pass.
  - `tests/test_netcheck.py::test_file_scheme_refused`: `file:///etc/passwd` → `BlockedHost`.
  - `tests/test_cache.py::test_shared_between_jobs`: a value set through one `get_cache()` call is visible through another.
  - `tests/test_cache.py::test_key_includes_sponsorblock`: the cache key differs when only the SponsorBlock setting differs.
  - `tests/test_jobs.py::test_heartbeat_touches_file(tmp_path)`: with a fake client and `interval=0.01`, the file exists within 1 s.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Handlers submit downloads to one module-level `JobQueue(MAX_PARALLEL_JOBS)` and return at once; each job enforces `JOB_TIMEOUT` with a socket timeout and a wall-clock check in the hook.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: job queue, size guards, shared cache, heartbeat, host check`.

## Slice 3: owner notices, proxy, restored features

### Task 12: Owner notices

**Files:**
- Create: `src/utils/notify.py`
- Modify: `src/database/model.py` (`OwnerNotice` table), `src/main.py` (startup impersonation check, FloodWait handler at today's lines 365-368), `src/engine/base.py` (notify on login_required/blocked, cookies expired)
- Test: `tests/test_notify.py`

**Interfaces:**
- Produces: `OwnerNotice(site: str, kind: str, last_sent: datetime)` with a unique constraint on `(site, kind)`; `database.model.claim_notice(site: str, kind: str, now: datetime) -> bool` (True and records `now` when nothing was sent for that pair in the last 24 h); `utils.notify.notify_owners(client, owners: frozenset[int], site: str, kind: str, details: str) -> int` (claims first, then sends to each owner separately inside try/except, text passed through `redact`; returns how many sends succeeded). Kinds: `login_required`, `blocked`, `cookies_expired`, `impersonation_missing`.
- Owner message format: `"[ytdlbot] {kind} on {site}\ncookies: {yes|no}\nexits tried: {list}\n{details}"` with `details` cut to 300 characters.
- FloodWait: the handler no longer sleeps in the worker; it re-submits the job to `JobQueue` after `e.value` seconds via `threading.Timer`.

- [ ] **Step 1: Write the failing tests** in `tests/test_notify.py`:
  - `test_once_per_day`: two `claim_notice("instagram", "blocked", t)` calls 1 h apart → True then False; 25 h later → True.
  - `test_survives_restart(tmp_path)`: after disposing and recreating the engine on the same file, a claim within 24 h is still False.
  - `test_each_owner_separately`: owners `{1, 2}`, the fake client raises for 1 → returns 1 and still sends to 2.
  - `test_message_redacted`: details containing `http://u:p@proxy.example:8080` are sent without `u:p@`.
  - `test_impersonation_missing_notified(monkeypatch)`: with `run_selfcheck()["impersonation"]` patched False, startup calls `notify_owners(..., "yt-dlp", "impersonation_missing", ...)`.
  - `test_cookies_expired_notified`: a job on `instagram` with cookies whose jar lost `sessionid` triggers `cookies_expired`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement and call `notify_owners` from the failure path for `login_required` and `blocked` (after all exits), and from the post-job cookie check.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: owner notices once per site and kind per day`.

### Task 13: Proxy fallback

**Files:**
- Create: `src/engine/proxy.py`
- Modify: `src/config/config.py` (`PROXY_EXITS`, `PROXY_PIN`; remove `YT_DLP_PROXY`), `src/engine/generic.py` (loop over exits)
- Test: `tests/test_proxy.py`

**Interfaces:**
- Produces: `parse_exits(raw: str | None) -> list[str]` (default `["direct"]`; each item is `direct` or an `http://`/`https://` URL, else `ConfigError`); `parse_pins(raw: str | None) -> dict[str, str]` (`site=exit` pairs, the exit must be in the exits list); `exits_for(site: str, exits: list[str], pins: dict[str, str]) -> list[str]` (pinned → `[pin]`, else `exits`); `ydl_proxy(exit: str) -> str` (`"direct"` → `""`).
- The download loop: for each exit from `exits_for`, run `check_url` then `attempt(...)`; on `classify(e) == "blocked"` continue with the next exit; any other kind stops. Uploads to Telegram never use these exits.

- [ ] **Step 1: Write the failing tests** in `tests/test_proxy.py`:
  - `test_parse_exits_default`: `parse_exits(None) == ["direct"]`; `parse_exits("direct,http://proxy.example:8080")` keeps order.
  - `test_parse_exits_rejects_socks`: `"socks5://proxy.example:1080"` → `ConfigError`.
  - `test_pin_must_exist`: `parse_pins("instagram=http://other.example:1", ["direct"])` → `ConfigError`.
  - `test_fallback_only_on_blocked`: fake `attempt` raising a blocked error on `direct` then succeeding on the proxy → two attempts, success; with an `unavailable` error on `direct` → one attempt.
  - `test_pinned_site_never_falls_back`: `instagram` pinned to `direct`, blocked → one attempt, then the blocked reply.
  - `test_host_check_before_each_attempt`: `check_url` is called once per attempt.
  - `test_proxy_value_never_logged(caplog)`: a run with a credentialed proxy logs no `u:p@`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: ordered proxy fallback on block errors with per-site pins`.

### Task 14: Restore upstream features behind switches

**Files:**
- Modify: `src/config/config.py` (`ENABLE_VIP`, `PROVIDER_TOKEN`, `FREE_DOWNLOAD`, `TOKEN_PRICE`, `RCLONE_PATH`, `ENABLE_FFMPEG` as in `git show upstream/master:src/config/config.py`, lines 38-49; read `RCLONE_PATH`, not `RCLONE`), `src/database/model.py` (`Payment` model and quota functions from `upstream/master:src/database/model.py`), `src/main.py` (`/buy` and payment handlers from `upstream/master:src/main.py:149-181` and the `reset_free` scheduler job from lines 404-405), `src/engine/*` (wherever upstream uses `RCLONE_PATH` and `ENABLE_FFMPEG`; find with `git grep -n -E "RCLONE|ENABLE_FFMPEG" upstream/master -- src`), `pyproject.toml` (`APScheduler`)
- Test: `tests/test_restored.py`

**Interfaces:**
- With `ENABLE_VIP=False` (default): `/buy` and payment handlers are not in `handler_table()`, `check_quota`/`use_quota` are not called, and no scheduler is started. With `ENABLE_VIP=True`: upstream behaviour, quotas stored in SQLite.
- `RCLONE_PATH` unset → no rclone call. `ENABLE_FFMPEG=False` → upstream's ffmpeg extras skipped (merging and thumbnails keep using ffmpeg).

- [ ] **Step 1: Write the failing tests** in `tests/test_restored.py`:
  - `test_buy_not_registered_by_default`: no entry in `handler_table()` has the `buy` callback.
  - `test_no_quota_checks_by_default`: a download with `ENABLE_VIP=False` never calls `check_quota`.
  - `test_no_scheduler_by_default`: `create_app()` starts no `BackgroundScheduler`.
  - `test_vip_on_registers_buy(monkeypatch)`: with `ENABLE_VIP=True` the `/buy` handler exists and the scheduler has one `reset_free` job.
  - `test_payment_tables_on_sqlite(tmp_path)`: `create_all` on SQLite creates the `payment` table and quota columns; `use_quota` decrements the free count.
  - `test_rclone_skipped_when_unset`: no subprocess call to rclone when `RCLONE_PATH` is unset.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Port the upstream code (it is already English), adapt it to `OWNERS`/`ALLOWED_USERS`, the guard and SQLite, and gate it as above. Add the variables to `.env.example` and the README table (off by default).
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat: restore upstream VIP, rclone and ffmpeg extras behind switches`.

## Slice 4 (repository side): regression suite and pipeline files

### Task 15: Regression suite

**Files:**
- Create: `src/regression/__init__.py`, `src/regression/run.py`, `src/regression/links.json`, `src/regression/README.md` (under `src/` so the shipped `runtime` image contains it; stdlib and app modules only, no pytest)

**Interfaces:**
- `python /app/regression/run.py [--links /app/regression/links.json] [--upload]` runs inside the `runtime` image (production security context), downloads each link through the bot's own download path (`attempt` + format options + size guard, no Telegram), probes the result with `ffprobe`, and prints one JSON line per link: `{"name", "status": "passed" | "downloader_broken" | "link_gone", "vcodec", "acodec", "duration", "size"}`. Exit code 0 when no link is `downloader_broken`, 2 when any is, 3 when all failures are `link_gone`. `--upload` sends the smallest result through `TEST_BOT_TOKEN`/`APP_ID`/`APP_HASH` to `TEST_CHAT_ID` with an `in_memory=True` client.
- `links.json`: the four links from spec 6.13 with expectations (`vcodec: "h264"`, `audio: true` except Instagram `audio: null` until confirmed, `duration_min: 1` except Instagram).
- Classification: `link_gone` when `classify()` returns `unavailable`; everything else that fails is `downloader_broken`.

- [ ] **Step 1:** Write `tests/test_regression_runner.py` (unit, no network): `test_status_mapping` (fake attempt raising unavailable → `link_gone`; raising other → `downloader_broken`; a fake file with an h264 stream → `passed`) and `test_exit_codes`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement `run.py`, `links.json` and the README (how Jenkins runs it: `docker run --read-only --user 10001:10001 --tmpfs /tmp:size=10g --cap-drop=ALL --security-opt no-new-privileges <image> python /app/regression/run.py`).
- [ ] **Step 4:** Run `uv run pytest -q` (PASS). Then one real run locally: `docker build --target runtime -t ytdlbot:dev . && docker run --rm --read-only --user 10001:10001 --tmpfs /tmp:size=4g --cap-drop=ALL --security-opt no-new-privileges ytdlbot:dev python /app/regression/run.py`. Expected: exit 0 (or 3 with a `link_gone` that needs a replacement link); record the Instagram audio result in `links.json`.
- [ ] **Step 5:** Commit: `test: real-download regression suite`.

### Task 16: GitHub workflows, Dependabot, deployment example

*Superseded in part by Task 17 (2026-11-15): `merge-and-promote.yml` and the Jenkins regression are gone; `ci.yml` is split into jobs.*

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/merge-and-promote.yml`, `.github/dependabot.yml`, `deploy/kubernetes.example.yaml`, `deploy/README.md`
- Test: `tests/repo/test_pipeline_files.py`

**Interfaces:**
- `ci.yml`: on `pull_request` from branches of this repository (`if: github.event.pull_request.head.repo.full_name == github.repository`), checks out `github.event.pull_request.head.sha` with `persist-credentials: false` and `fetch-depth: 0`, runs `uv run pytest -q tests/repo` on the checkout, builds the `test` target and runs it (job name `unit`, posts the check), builds `runtime` for linux/amd64 and pushes `ghcr.io/${{ github.repository }}:sha-<head sha>`; `permissions: {contents: read, packages: write}`; no `statuses: write`; no `pull_request_target`; every `uses:` pinned to a full commit SHA with the tag in a comment.
- `merge-and-promote.yml`: `schedule: "*/15 * * * *"` and `workflow_dispatch`; implements spec 6.14 merge and promote steps with `gh` and `docker buildx imagetools create`; tags `stable` and `YYYY.MM.DD-<short sha>`; on any mismatch it promotes nothing and fails the run.
- `dependabot.yml`: `uv` daily, group `python-deps` (all except `yt-dlp`), `cooldown: {default-days: 3, exclude: ["yt-dlp"]}`; `docker` weekly with `ignore` for `python` `version-update:semver-minor` and `semver-major`; `github-actions` weekly, grouped.
- `deploy/kubernetes.example.yaml`: Deployment (1 replica, `Recreate`, uid 10001, `fsGroup: 10001`, read-only root, `automountServiceAccountToken: false`, `imagePullPolicy: Always`, Keel annotations, `imagePullSecrets`, exec probes `python /app/health.py`, env from Secret), PVC (block storage, 1Gi), `emptyDir` at `/tmp` with `sizeLimit: 10Gi`, cookies Secret mount, egress NetworkPolicy (DNS + `0.0.0.0/0` except private/CGNAT/link-local/loopback/multicast + placeholder proxy `ipBlock`). Placeholders only.

- [ ] **Step 1:** Write `tests/repo/test_pipeline_files.py`: `test_actions_pinned_by_sha` (every `uses:` value matches `@[0-9a-f]{40}`), `test_no_pull_request_target`, `test_ci_checks_out_head_sha`, `test_dependabot_yt_dlp_alone` (yt-dlp excluded from the group and from cooldown), `test_docker_python_minor_ignored`, `test_example_has_no_real_addresses` (no RFC1918 address other than inside `except:` lists, no `t.me`).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Write the files (look up each action's current release SHA with `gh api repos/<owner>/<action>/commits/<tag> --jq .sha`).
- [ ] **Step 4:** Run `uv run pytest -q`. Expected: PASS. Validate YAML with `uv run python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml .github/dependabot.yml deploy/kubernetes.example.yaml` (add `pyyaml` to the dev group).
- [ ] **Step 5:** Commit: `ci: build, test, merge and promote workflows; dependabot; deploy example`.

## Owner-side steps (not agent tasks; need the owner or live systems)

- Create the private repository `megabitus98/ytdlbot`, disable Actions, push `main` (controller, after slice 1). Enable Actions after Task 16.
- Create the bot in BotFather (disable groups), get `APP_ID`/`APP_HASH` from my.telegram.org, create the test bot and test chat; each owner sends `/start` to both bots.
- The home runner (label `ytdlbot-regression`, registered to this repository only, internet only) and the test bot secrets under Actions and Dependabot (`deploy/README.md`; owner's explicit go for each credential), Kubernetes Secret/PVC/NetworkPolicy/router rule and Keel in the owner's private deployment repository (see the private deployment note). Jenkins is no longer used (Task 17).

## Carry-over from reviews (each item belongs to the task named; that task's implementer must do it and its reviewer must check it)

- **Task 4:** In the Dockerfile `runtime` stage add `ENV HOME=/tmp/home XDG_CACHE_HOME=/tmp/cache DENO_DIR=/tmp/cache/deno TMPFILE_PATH=/tmp/ytdlbot` (spec 6.8; with a read-only root the yt-dlp cache under the default HOME is unwritable). Add `pytest.mark.skipif(os.geteuid() == 0, ...)` to `test_selfcheck_flags_unwritable_dir`. Drop the floating `# syntax=docker/dockerfile:1` line (or pin it by digest).
- **Task 5:** Every download entry point (`/direct`, `/spdl`, group `/ytdl`, the plain-text handler, and `youtube_entrance`/`direct_entrance` callers) catches `Exception` and replies `BotText.error`; since Task 1 the upload loop raises `RuntimeError`, which today escapes `/direct`, `/spdl` and `/ytdl`. Extend `test_no_exception_text_to_users` to cover those handlers.
- **Task 7:** `test_modified_files_carry_notice` must use `git diff --name-only --diff-filter=d 0d5bfcd -- src` (deleted files have no notice to carry). Rephrase any `ponytail:` comment prefixes in the repo as plain comments (the repo goes public).
- **Task 9:** `.dockerignore`: use spec 6.1's `**/*cookies*` with exceptions `!src/engine/cookies.py` and `!tests/test_cookies.py` instead of the narrower patterns from Task 1.
- **Task 16:** `ci.yml` passes `--build-arg YT_DLP_VERSION`, `CURL_CFFI_VERSION`, `KURIGRAM_VERSION` extracted from `uv.lock` (see the Dockerfile comment); `tests/repo/test_pipeline_files.py` checks that it does.
- **Task 8:** Engines that catch an error, edit the progress message and return `[]` make the handler reply a second time; after classification the user gets exactly one reply. Extend `test_no_cyrillic_in_src` to every file under `src/`, not only `*.py`. `/about` is sent with `disable_web_page_preview=True`. Quality buttons get a label in `BotText.buttons`; the flood-wait file name "Please wait.txt" moves to `constant.py`.
- **Task 10:** `BaseDownloader` reads quality/codec/format settings by the requesting user's ID (`from_user.id`), not `chat.id` (settings are saved by user since Task 3). `PREFERRED_AUDIO_LANG` matches region-tagged tracks too (`[language^=en]`, so `en-US` counts as `en`). The Google Drive case prepends `source/` to the joined format string (`build_format_options` returns a joined string since Task 6).
- **Task 11:** `/stats` must not depend on `botStartTime` defined only under `__main__` (record the start time in a module-level value set by `create_app()`).
- **Task 12:** Make the token-masking test real: use a token in the test that does not contain `APP_HASH` (conftest's `APP_HASH=test` currently masks `1:test` by accident).
- **Task 13:** Redaction also masks every configured proxy exit URL as a whole (spec 6.7/6.10), and the credentials regex handles a raw `@` inside a password (`http://user:p@ss@host:1` must not leak `ss@host` credentials; split at the last `@` like `urllib.parse`). `ConfigError` messages from `parse_id_list`/`parse_bool` name the variable but never echo the raw value.
- **Task 14:** `get_env` no longer exists; port upstream's VIP/rclone/ffmpeg settings with the Task 2 helpers (`_bool_env`, `_int_env`, `parse_bool`). When a table gains columns (users: `free`, `paid`, `config`), call `database.migrate.ensure_columns` at startup so an existing slice-1 database is upgraded. Update README configuration table and `.env.example`.
- **Task 16:** `tests/repo/test_repo.py` lists `.github/dependabot.yml` as a removed file; remove it from that list when Task 16 creates the new one. Run `tests/repo` in CI with `fetch-depth: 0` (it needs commit `0d5bfcd`).

### Added after the first real test (2026-11-15) and the slice 2-3 reviews

- **Task 15:** the regression run goes through the bot's whole download path, not `attempt()` alone: build a `YoutubeDownload` with a stub client and progress message (no Telegram) and call `_download_fitting()`, so the format ladder, the per-site rules, the size guard and the `ENABLE_FFMPEG` conversion are all exercised. Run it with `ENABLE_FFMPEG=true` (the owner's deployment) and the default quality (1440p).
- **Task 15:** expectations come from the real test: every result has a video stream whose codec is `h264`, or `hevc` with tag `hvc1` (TikTok), and an audio stream (Instagram has audio: HE-AAC, confirmed 2026-11-15, so `audio: true` for it too). A result with only audio is `downloader_broken` (TikTok once came back as its mp3). The YouTube Short's smaller side is at least 1080 when the source has it (it once came back 480x854). With `ENABLE_FFMPEG`, the Instagram reel's smaller side is 1080 (VP9 converted to H.264). Record in each JSON line `width`, `height` and `vtag`.
- **Task 16:** `ci.yml` runs the unit tests in the `test` image, which has ffmpeg (`tests/test_transcode.py` converts real clips; it skips only where ffmpeg is missing).
- **Later (no task yet; the owner decides):**
  - `engine/errors.py`: `captcha` has no word boundary (`xcaptchaxyz` in a video ID reads as blocked); the bare `log ?in` pattern also runs over the bot's own text (a host such as `login.example.com`); `__context__` in the chain can turn a handled 403 into `blocked` for a later private-video error; curl-cffi's `TransportError ... over proxy <host>` comes out as `other`, not `blocked`.
  - Flood: `_upload()` writes the file_id cache before `edit_text(BotText.done)`, so a FloodWait there sends the file twice on the retry; flood retries have no limit.
  - `_download_fitting()` retries one quality lower even when quality does not change the format (send as audio, Google Drive), starts again at the first exit and lists the exits twice in an owner notice.
  - `JOB_TIMEOUT`, the size limit and `TMP_BUDGET` are checked in progress callbacks and around the H.264 conversion, not during extraction or upload.
  - The Alpine image has no tz database, so APScheduler (only with `ENABLE_VIP`) resets the free quota at 00:00 UTC unless `TZ` is set and `tzdata` installed.
  - `PROXY_PIN` defaults to nothing; the deployment must set `PROXY_PIN=instagram=direct` (spec 6.7).
  - TikTok age-restricted posts need `tiktok.txt` cookies (login_required, as designed).

### Task 17: Pipeline without Jenkins (2026-11-15, owner decision)

Why: the first `ci.yml` built, tested and pushed in one job holding `packages: write`, so a malicious dependency release in a Dependabot PR could read the token from the runner's memory and push its own `stable`; the 15-minute `merge-and-promote` cron alone was about 2,900 billable minutes a month, above GitHub Free's included $12; and the Jenkins VM is reachable from the internet and holds work credentials.

- `ci.yml`: jobs `unit` (read-only; `UV_MALWARE_CHECK=1`; saves the image as a one-day artifact), `scan` (read-only; `uv audit` of head and base locks for `x86_64-unknown-linux-musl`, Python 3.12; fails on added `<package> <id>` pairs), `push` (`packages: write`, `actions: write`, no checkout; loads `ytdlbot:runtime`, pushes `sha-<head sha>` unless it exists, deletes the artifact), `regression` (`[self-hosted, ytdlbot-regression]`, `packages: read`, no checkout, `--upload` when `TEST_BOT_TOKEN` is set), `merge` (Dependabot `uv` PRs; squash-merge when `behind_by == 0`, then `gh workflow run promote.yml`; else `@dependabot rebase`), `notify` (test bot message on failure).
- `promote.yml`: push to `main` and `workflow_dispatch`; requires `unit`, `scan`, `push`, `regression` green on the tested head and the same tree; a commit from no PR is a notice, not a failure.
- `weekly.yml`: regression on `stable`, full `uv audit` (fails on fixable), Grype `v0.121.3` by digest on the saved image (`--only-fixed --fail-on high`), drift (yt-dlp, curl-cffi, Dependabot PRs, `python:3.12-alpine` tag), heartbeat or test bot message.
- `Dockerfile`: `UV_MALWARE_CHECK=1` on both `uv sync` lines (fails closed when OSV is unreachable, checked 2026-11-15 with uv 0.13.8).
- `.github/actionlint.yaml` declares the runner label. `tests/repo/test_pipeline_files.py` pins the rules: workflow permissions `{}`, write tokens only in `ci.push`, `ci.merge`, `promote.promote` and none of them checks out code, `packages: write` only in `push` and `promote`, the home runner only for the two regression jobs with `packages: read` and no checkout, promote's check list equals the ci gates, the malware check on every sync, Grype pinned by digest.
- Checked: actionlint 1.7.12 and zizmor 1.32.0 (`--persona auditor`: only the expected self-hosted runner, secrets without environments and job-name notes), the scan step run for real against a clean and a vulnerable lock, the image build with the malware check, the unit tests in the image.
- Not checked until Actions is on: the jobs on GitHub's runners, whether Dependabot obeys an `@dependabot rebase` comment from `github-actions[bot]` (the weekly drift check reports a Dependabot PR open more than 3 days either way).
- Review fixes (same day): `push` runs no action (a PR run uses the PR's own workflow file, so Dependabot's GitHub Actions PR picks the action versions of its own run); it fetches the artifact with the runner's `gh` and checks the upload digest. Artifact deletion moved to a `cleanup` job that always runs. `notify` also reports cancelled runs (an offline runner is cancelled after 24 h) unless a newer push replaced the run; `promote` messages the owner on failure; GitHub itself notifies only whoever started a run, often a bot. `merge` passes the tested head to `promote` (`-f head_sha=`) and uses `concurrency.queue: max`. `green()` takes the most recently started run per check. The upload needs all four test secrets (some but not all fails with their names). Chat IDs go through curl's config too. Drift: every check records its problem and goes on; curl-cffi 5 days. Runner docs: container-to-host traffic needs an `INPUT` rule. Tests: no job has `name:`, write jobs have no `uses:` and no `docker run`, every job not on the home runner is on `ubuntu-24.04`; the three mutations the reviewer used and an action in `push` each fail a test.

