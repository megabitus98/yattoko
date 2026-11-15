# Regression run

Real downloads of a few known links through the bot's own download path (`YoutubeDownload._download_fitting()`: host check, exits, format ladder, per-site rules, size guard, H.264 conversion), inside the image under test, with no Telegram. Each result is probed with `ffprobe`. It lives under `src/` so the shipped `runtime` image contains it; it uses only the standard library and the app's own modules.

Every run uses the same home IP as the production bot and spends its reputation with the sites, so the list stays small on purpose.

## How Jenkins runs it

Run it in the exact image under test, with the production security context, on a Docker network that cannot reach private address ranges:

```sh
docker run --rm --read-only --user 10001:10001 --tmpfs /tmp:size=10g \
  --cap-drop=ALL --security-opt no-new-privileges \
  <image> python /app/regression/run.py
```

With the real upload of the smallest result through the test bot (never the production bot), add the test bot's credentials and `--upload`:

```sh
docker run --rm --read-only --user 10001:10001 --tmpfs /tmp:size=10g \
  --cap-drop=ALL --security-opt no-new-privileges \
  -e TEST_BOT_TOKEN -e TEST_CHAT_ID -e APP_ID -e APP_HASH \
  <image> python /app/regression/run.py --upload
```

`TEST_CHAT_ID` is numeric (for example `123456789`). The upload goes through the bot's own upload code with an `in_memory=True` client, so no session file is written. `--links <file>` runs another list.

Defaults inside the run: `ENABLE_FFMPEG=true` (as in the owner's deployment), `DATA_DIR=/tmp/regression` (the root filesystem is read-only and there is no `/data` volume), the default settings (1440p, codec auto, sent as video), no cookies, `PROXY_EXITS=direct`. Each one can be overridden with `-e`.

## Output

One JSON line per link on stdout (logs and tracebacks go to stderr, redacted):

```json
{"name": "tiktok", "status": "passed", "vcodec": "hevc", "vtag": "hvc1", "acodec": "aac", "width": 1080, "height": 1920, "duration": 10.0, "size": 2345678}
```

With `--upload`, a last line `{"name": "upload", "status": ...}` follows.

- `passed`: the file meets every expectation in `links.json`.
- `link_gone`: yt-dlp says the video is private, deleted or not available here (`classify()` returns `unavailable`). Replace the link; this is not a downloader regression.
- `downloader_broken`: anything else that fails, including a file that misses an expectation (wrong codec, no sound, too small, only audio) and an upload that did not arrive as a video.

Exit code: 0 when every line passed, 2 when any line is `downloader_broken`, 3 when nothing is broken but a link is gone, 1 when the run itself could not start (for example `--upload` without the test bot's settings).

## links.json

One YouTube video, one YouTube Short, one TikTok and one Instagram reel, each from an official account (spec 6.13). Fields per link:

- `name`, `url`
- `vcodec`: the codecs ffprobe may report for the main video stream (the embedded cover does not count). Telegram plays H.264 everywhere; H.265 counts only with the `hvc1` tag (TikTok's files have it).
- `audio`: `true` when the file must have a sound stream.
- `duration_min` (optional): the shortest acceptable length in seconds.
- `min_short_side` (optional): the smallest acceptable smaller side in pixels.

The expectations come from the first real test through the bot (2026-11-15). There, an Instagram reel (11 s) had sound (HE-AAC) and came back at 1080 (VP9 converted to H.264 with `ENABLE_FFMPEG`), and a vertical 1080x1920 Short once came back at 480x854 (since fixed). Those were not necessarily the links listed here.

The first run of this suite in the `runtime` image on 2026-11-15 (yt-dlp 2026.10.26, cookie-less, direct exit) did not meet them for two of the links. The Short `Hb3rmh-_FMw` came back as H.264 720x1280 with sound. The reel `Chunk8-jurw` (5 s) came back as H.264 720x1280 with no sound stream. In both cases yt-dlp was offered nothing above 720p: the quality-first sort would have taken a 1080p format and converted it, and nothing was converted. yt-dlp also found no format with sound for the reel; it reads Instagram's `has_audio`. So either these sources (cookie-less) do not have what the expectations ask for, and the links need replacing with ones that do, or the sites now withhold it. The owner decides; until then these two links report `downloader_broken`.
