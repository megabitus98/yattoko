# syntax=docker/dockerfile:1
# Modified 2026 by megabitus98 (fork): uv, pinned base, non-root, runtime and test targets

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
    && adduser -D -H -u 10001 -G app app

ENV UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock /app/
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --locked --no-dev
COPY src /app

USER app
CMD ["python", "main.py"]

FROM runtime AS test
USER root
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --locked
COPY tests /app/tests
# /app is not writable for `app`, so no pytest cache
ENV PYTEST_ADDOPTS="-p no:cacheprovider"
USER app
CMD ["python", "-m", "pytest", "-q", "/app/tests"]
