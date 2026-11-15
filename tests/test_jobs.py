import asyncio
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyrogram import enums

import main
from config import TG_NORMAL_MAX_SIZE, BotText
from database.model import init_user, set_user_settings
from engine import base, generic
from engine.jobs import JobQueue, JobTimeout, TooLarge
from fakes import FakeClient, fake_downloader
from health import is_healthy, start_heartbeat

URL = "https://www.youtube.com/watch?v=x"
PROGRESS = {"status": "downloading", "_speed_str": "1.00MiB/s", "_eta_str": "00:01"}


def test_positions():
    queue = JobQueue(1)
    release = threading.Event()
    finished = [threading.Event() for _ in range(3)]

    def job(n):
        release.wait(5)
        finished[n].set()

    assert [queue.submit(lambda n=n: job(n)) for n in range(3)] == [0, 1, 2]
    release.set()
    assert all(event.wait(5) for event in finished)
    queue.shutdown(wait=True)


def test_failed_job_frees_its_place():
    queue = JobQueue(1)
    done = threading.Event()

    def boom():
        raise RuntimeError("boom")

    queue.submit(boom)
    queue.submit(done.set)
    assert done.wait(5)
    queue.shutdown(wait=True)


def test_unknown_size_overflow_aborts():
    downloader, _ = fake_downloader(URL)
    downloader.download_hook(PROGRESS | {"downloaded_bytes": TG_NORMAL_MAX_SIZE})
    with pytest.raises(TooLarge):
        # no total_bytes and no estimate: the stream keeps growing past the limit
        downloader.download_hook(
            PROGRESS | {"downloaded_bytes": TG_NORMAL_MAX_SIZE + 1}
        )


def test_tmp_budget_abort(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "TMPFILE_PATH", str(tmp_path))
    monkeypatch.setattr(base, "TMP_BUDGET", 1000)
    downloader, _ = fake_downloader(URL)  # its temp dir is under tmp_path now
    (Path(downloader._tempdir.name) / "video.mp4.part").write_bytes(b"x" * 600)
    downloader.download_hook(PROGRESS | {"downloaded_bytes": 600})
    (tmp_path / "other-job").mkdir()
    (tmp_path / "other-job" / "audio.m4a.part").write_bytes(b"x" * 600)
    with pytest.raises(TooLarge):
        downloader.download_hook(PROGRESS | {"downloaded_bytes": 600})


def test_hook_abort_replies_too_large_without_retry(monkeypatch):
    # Review Focus 4 through start(): the stream outgrows the limit mid-download, so that job stops
    attempts = []

    def growing_attempt(url, site, exit, opts, tmpdir, **kwargs):
        attempts.append(url)
        hook = opts["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": TG_NORMAL_MAX_SIZE + 1})

    monkeypatch.setattr(generic, "attempt", growing_attempt)
    downloader, edits = fake_downloader(URL)
    downloader.start()
    assert edits == [BotText.too_large]
    assert len(attempts) == 1  # no retry a quality lower after a hook abort


def test_job_timeout_in_hook():
    downloader, _ = fake_downloader(URL)
    downloader._deadline = time.monotonic() - 1
    with pytest.raises(JobTimeout):
        downloader.download_hook(PROGRESS | {"downloaded_bytes": 1})


def test_oversized_result_retries_lower_then_refuses(monkeypatch):
    monkeypatch.setattr(base, "TG_NORMAL_MAX_SIZE", 100)
    formats = []

    def oversized_attempt(url, site, exit, opts, tmpdir, **kwargs):
        formats.append(opts["format"])
        # yt-dlp would skip a file that is already there, so the retry must start from an empty dir
        assert list(tmpdir.iterdir()) == []
        (tmpdir / "video.mp4").write_bytes(b"x" * 101)

    monkeypatch.setattr(generic, "attempt", oversized_attempt)
    init_user(811)
    set_user_settings(811, "quality", "1080p")
    downloader, edits = fake_downloader(URL, user_id=811)
    key = downloader._calc_video_key()
    downloader.start()
    assert [f.split("+")[0] for f in formats] == [
        "bestvideo[height<=1080][filesize<1.5G]",
        "bestvideo[height<=720][filesize<1.5G]",
    ]
    assert edits == [BotText.too_large]
    assert BotText.too_large == "This video is too large for Telegram (over 2 GB)."
    # the file is cached under the quality the user asked for
    assert downloader._video_key == key


def test_queued_reply(monkeypatch, downloads):
    submitted = []
    monkeypatch.setattr(
        main, "JOBS", SimpleNamespace(submit=lambda fn: submitted.append(fn) or 2)
    )
    edits = []
    bot_msg = SimpleNamespace(edit_text=lambda text, **kwargs: edits.append(text))
    message = SimpleNamespace(
        text="https://youtu.be/abc",
        from_user=SimpleNamespace(id=2),
        chat=SimpleNamespace(id=2, type=enums.ChatType.PRIVATE),
        reply_text=lambda text, **kwargs: bot_msg,
    )
    main.download_handler(FakeClient(), message)
    # the handler returned before the job ran
    assert len(submitted) == 1 and downloads == []
    assert edits == ["Queued, position 2."]
    submitted[0]()
    assert downloads == ["youtube_entrance"]


def parking_client(fail: bool, beats: int):
    # get_me answers (or fails) `beats` times, then parks the daemon thread for good
    calls, parked = [], threading.Event()

    class Client:
        def get_me(self):
            if len(calls) == beats:
                parked.set()
                threading.Event().wait()
            calls.append(1)
            if fail:
                raise ConnectionError("not connected")

    return Client(), parked


def test_heartbeat_touches_file(tmp_path):
    client, parked = parking_client(fail=False, beats=1)
    path = tmp_path / "healthy"
    thread = start_heartbeat(client, path=path, interval=0.01)
    assert thread.daemon
    assert parked.wait(1) and path.exists()


def test_heartbeat_skips_touch_when_telegram_fails(tmp_path):
    # a failed beat is logged and the loop goes on, but the file is not touched
    client, parked = parking_client(fail=True, beats=2)
    path = tmp_path / "healthy"
    start_heartbeat(client, path=path, interval=0.01)
    assert parked.wait(1) and not path.exists()


def test_health_probe(tmp_path):
    path = tmp_path / "healthy"
    assert is_healthy(path) is False
    path.touch()
    assert is_healthy(path) is True
    old = time.time() - 181
    os.utime(path, (old, old))
    assert is_healthy(path) is False


def test_serve_uses_real_kurigram_calls():
    # serve() awaits app.start() and idle(); inside a running loop kurigram's sync wrappers must hand
    # back coroutines for that. Nothing is awaited, so nothing connects.
    app = main.create_app()

    async def check():
        for coroutine in (app.start(), main.idle()):
            assert asyncio.iscoroutine(coroutine)
            coroutine.close()

    asyncio.run(check())
    assert callable(main.loops.run)


def test_heartbeat_starts_after_client(monkeypatch):
    # get_me needs a started client, so the heartbeat starts between start() and idle()
    events = []

    class App:
        async def start(self):
            events.append("start")

        async def stop(self):
            events.append("stop")

    async def idle():
        events.append("idle")

    monkeypatch.setattr(main, "idle", idle)
    monkeypatch.setattr(
        main, "start_heartbeat", lambda client: events.append("heartbeat")
    )
    monkeypatch.setattr(
        main, "check_impersonation", lambda client: events.append("impersonation")
    )
    asyncio.run(main.serve(App()))
    assert events == ["start", "heartbeat", "impersonation", "idle", "stop"]
