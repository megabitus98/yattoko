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

Each line also has `reason` (why it is not `passed`) and `offered`: what the site listed for this very download, `{"short_side", "audio"}` (the biggest smaller side up to 1440 among video formats, and whether any format has sound; `null` when the site listed no formats). The bot is judged against `offered`, so a link that changes does not read as a broken bot.

- `passed`: the file plays everywhere (H.264, or H.265 tagged `hvc1`), is at least `duration_min` long, has sound when the site offered sound, and its smaller side is at least what the site offered. The link still has what it is listed for.
- `downloader_broken`: the download failed for any reason other than "unavailable", or the file misses what the site offered (sound, picture size), or it does not play everywhere (VP9, AV1, hev1, audio only), or the upload did not arrive as a video. This is the bot's or yt-dlp's fault.
- `link_gone`: yt-dlp says the video is private, deleted or not available here (`classify()` returns `unavailable`), or the site no longer offers what the link is listed for (`audio`, `min_short_side`). Replace the link; this is not a downloader regression.

Exit code: 0 when every line passed, 2 when any line is `downloader_broken`, 3 when nothing is broken but a link is gone, 1 when the run itself could not start: no network or DNS (checked first, so an outage does not read as every link being gone), or `--upload` without the test bot's settings.

## links.json

One YouTube video, one YouTube Short, one TikTok and one Instagram reel, each from an official account (spec 6.13). Fields per link:

- `name`, `url`
- `vcodec`: the codecs ffprobe may report for the main video stream (the embedded cover does not count). Telegram plays H.264 everywhere; H.265 counts only with the `hvc1` tag (TikTok's files have it).
- `audio`: `true` when the link is in the list for its sound: the site must still offer sound, else `link_gone`. With `false` the link is not checked for that, but a file without the sound the site offered is still `downloader_broken`.
- `duration_min` (optional): the shortest acceptable length in seconds.
- `min_short_side` (optional): the smallest smaller side the site must still offer, else `link_gone`.
- `note` (optional): why the link is in the list.

What the links offered on 2026-11-15 (yt-dlp 2026.10.26, cookie-less, direct exit): the Short `Hb3rmh-_FMw` 720x1280 at most (H.264, VP9, AV1) with sound, so it still catches a height filter that drops vertical videos (a 1080x1920 Short once came back 480x854); the reel `Chunk8-jurw` H.264 720x1280 at most and no sound at all. The first run expected 1080 and sound from both and reported `downloader_broken` for a bot that had picked the best the sites offered; that is why the checks compare with `offered`. No link here makes the bot convert VP9 to H.264; an Instagram reel with sound and 1080p VP9 from an official account would (the first real test converted an 11 s 1080p VP9 reel in about 1 s on 2 cores); the conversion itself is covered by `tests/test_transcode.py` with real clips.
