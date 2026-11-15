# Modified 2026 by megabitus98 (fork): uv, pinned base, non-root, runtime and test targets, caches and scratch under /tmp, /data owned by app (a new Docker volume copies that owner), uv's malware check on every sync

FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

FROM python:3.12-alpine3.24@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89 AS runtime

# Resolved versions from uv.lock, passed by the build, e.g.
#   --build-arg YT_DLP_VERSION=$(awk '/^name = "yt-dlp"$/{getline; gsub(/"/,""); print $3}' uv.lock)
ARG YT_DLP_VERSION=unknown
ARG CURL_CFFI_VERSION=unknown
ARG KURIGRAM_VERSION=unknown
LABEL org.opencontainers.image.source="https://github.com/megabitus98/ytdlbot" \
      io.ytdlbot.yt-dlp="${YT_DLP_VERSION}" \
      io.ytdlbot.curl-cffi="${CURL_CFFI_VERSION}" \
      io.ytdlbot.kurigram="${KURIGRAM_VERSION}"

RUN apk add --no-cache ffmpeg deno aria2 \
    && addgroup -g 10001 app \
    && adduser -D -H -u 10001 -G app app \
    && install -d -o app -g app /data

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock /app/
# UV_MALWARE_CHECK: uv checks the locked versions against OSV's malware list first and stops on a match;
# it also stops when OSV cannot be reached, so a build needs that service
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    UV_MALWARE_CHECK=1 uv sync --locked --no-dev
COPY src /app

# The root filesystem is read-only at runtime: yt-dlp and deno caches go under HOME, scratch under /tmp.
ENV HOME=/tmp/home \
    XDG_CACHE_HOME=/tmp/cache \
    DENO_DIR=/tmp/cache/deno \
    TMPFILE_PATH=/tmp/ytdlbot

USER app
CMD ["python", "main.py"]

FROM runtime AS test
USER root
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    UV_MALWARE_CHECK=1 uv sync --locked
COPY tests /app/tests
# /app is not writable for `app`, so no pytest cache
ENV PYTEST_ADDOPTS="-p no:cacheprovider"
USER app
CMD ["python", "-m", "pytest", "-q", "/app/tests"]
