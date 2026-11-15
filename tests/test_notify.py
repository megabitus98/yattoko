import asyncio
import time
from datetime import datetime, timedelta

import pyrogram.errors
import pytest
import yt_dlp
from sqlalchemy.orm import sessionmaker

import main
from config import BotText
from database import model
from database.model import claim_notice, make_engine
from engine import errors, generic
from fakes import FakeClient, fake_downloader, fake_message
from utils.notify import notify_owners

T = datetime(2026, 11, 14, 12, 0)
INSTAGRAM_COOKIES = "".join(
    f".instagram.com\tTRUE\t/\tTRUE\t4102444800\t{name}\tvalue-{name}\n"
    for name in ("sessionid", "csrftoken")
)


def use_db(path, monkeypatch):
    # what a (re)start does: a new engine on the file, tables created if missing
    engine = make_engine(f"sqlite:///{path}")
    model.Base.metadata.create_all(engine)
    monkeypatch.setattr(model, "SessionFactory", sessionmaker(bind=engine))
    return engine


@pytest.fixture(autouse=True)
def notice_db(tmp_path, monkeypatch):
    # every test starts with no notice sent; the shared test database would carry claims over
    engine = use_db(tmp_path / "notices.db", monkeypatch)
    yield
    engine.dispose()


class RecordingClient:
    def __init__(self, failing=()):
        self.sent, self.failing = [], set(failing)

    def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.failing:
            raise pyrogram.errors.PeerIdInvalid()
        self.sent.append((chat_id, text))


def test_once_per_day():
    assert claim_notice("instagram", "blocked", T) is True
    assert claim_notice("instagram", "blocked", T + timedelta(hours=1)) is False
    # another kind or site is its own pair
    assert claim_notice("instagram", "login_required", T + timedelta(hours=1)) is True
    assert claim_notice("tiktok", "blocked", T + timedelta(hours=1)) is True
    assert claim_notice("instagram", "blocked", T + timedelta(hours=25)) is True
    assert claim_notice("instagram", "blocked", T + timedelta(hours=26)) is False


def test_survives_restart(tmp_path, monkeypatch):
    path = tmp_path / "restart.db"
    engine = use_db(path, monkeypatch)
    assert claim_notice("instagram", "blocked", T)
    engine.dispose()
    engine = use_db(path, monkeypatch)
    assert claim_notice("instagram", "blocked", T + timedelta(hours=23)) is False
    assert claim_notice("instagram", "blocked", T + timedelta(hours=25)) is True
    engine.dispose()


def test_each_owner_separately():
    client = RecordingClient(failing={1})
    assert (
        notify_owners(
            client, frozenset({1, 2}), "instagram", "blocked", "HTTP Error 429"
        )
        == 1
    )
    assert [chat_id for chat_id, _ in client.sent] == [2]
    # claimed: the next failure the same day sends nothing
    assert (
        notify_owners(client, frozenset({1, 2}), "instagram", "blocked", "again") == 0
    )
    assert len(client.sent) == 1


def test_message_redacted():
    client = RecordingClient()
    details = "proxy http://u:p@proxy.example:8080 refused " + "x" * 400
    notify_owners(
        client,
        frozenset({1}),
        "instagram",
        "blocked",
        details,
        cookies=True,
        exits=["direct", "http://u:p@proxy.example:8080", "direct"],
    )
    [(_, text)] = client.sent
    assert "u:p@" not in text
    head, details_line = text.rsplit("\n", 1)
    assert head == (
        "[Yattoko] blocked on instagram\ncookies: yes\nexits tried: direct, http://***@proxy.example:8080"
    )
    assert details_line.startswith("proxy http://***@proxy.example:8080 refused x")
    assert len(details_line) == 300


def test_message_without_cookies_or_exits():
    client = RecordingClient()
    notify_owners(
        client, frozenset({1}), "yt-dlp", "impersonation_missing", "no target"
    )
    assert client.sent == [
        (
            1,
            "[Yattoko] impersonation_missing on yt-dlp\ncookies: no\nexits tried: none\nno target",
        )
    ]


def test_claim_failure_sends_nothing(monkeypatch):
    # a broken database must not raise into the download that is replying to its user
    def broken(*args):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("utils.notify.claim_notice", broken)
    client = RecordingClient()
    assert notify_owners(client, frozenset({1}), "instagram", "blocked", "x") == 0
    assert client.sent == []


class App:
    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.mark.parametrize("available", [False, True])
def test_impersonation_missing_notified(monkeypatch, available):
    calls = []

    def record(client, owners, site, kind, details, **kwargs):
        # on the client's loop kurigram's sync calls return coroutines and send nothing
        try:
            asyncio.get_running_loop()
            calls.append((site, kind, "on the loop"))
        except RuntimeError:
            calls.append((site, kind, "in a thread"))
        return 1

    async def idle():
        pass

    monkeypatch.setattr(main, "run_selfcheck", lambda: {"impersonation": available})
    monkeypatch.setattr(main, "notify_owners", record)
    monkeypatch.setattr(main, "idle", idle)
    monkeypatch.setattr(main, "start_heartbeat", lambda client: None)
    asyncio.run(main.serve(App()))
    assert calls == (
        [] if available else [("yt-dlp", "impersonation_missing", "in a thread")]
    )


@pytest.mark.parametrize("lost", [True, False])
def test_cookies_expired_notified(tmp_path, monkeypatch, lost):
    (tmp_path / "instagram.txt").write_text(
        "# Netscape HTTP Cookie File\n" + INSTAGRAM_COOKIES
    )
    monkeypatch.setattr(generic, "COOKIES_DIR", str(tmp_path))
    notices = []
    monkeypatch.setattr(
        errors,
        "notify_owners",
        lambda client, owners, site, kind, details, **kwargs: notices.append(
            (site, kind, kwargs["cookies"])
        ),
    )
    monkeypatch.setattr(errors, "COOKIES_DIR", str(tmp_path))

    class LosingYDL(yt_dlp.YoutubeDL):
        # what yt-dlp's Instagram extractor does when the cookies stopped working: it drops sessionid
        def extract_info(
            self, url, download=True, ie_key=None, extra_info=None, process=True
        ):
            if lost:
                self.cookiejar.clear(".instagram.com", "/", "sessionid")
            return {"id": "x", "title": "x"}

        def process_ie_result(self, info, download=True, extra_info=None):
            return info

    monkeypatch.setattr(yt_dlp, "YoutubeDL", LosingYDL)
    downloader, _ = fake_downloader("https://www.instagram.com/reel/C0abcdefghi/")
    downloader.start()  # nothing downloaded, so the upload fails afterwards ("other": no notice)
    assert notices == ([("instagram", "cookies_expired", True)] if lost else [])


@pytest.mark.parametrize(
    "kind_text, kind",
    [("HTTP Error 429: Too Many Requests", "blocked"), ("boom", "other")],
)
def test_failure_notifies_after_reply(monkeypatch, kind_text, kind):
    events = []
    monkeypatch.setattr(
        errors,
        "notify_owners",
        lambda client, owners, site, kind, details, **kwargs: events.append(
            ("notice", site, kind, kwargs["exits"])
        ),
    )

    def failing_attempt(url, site, exit, opts, tmpdir, **kwargs):
        raise yt_dlp.utils.DownloadError(f"ERROR: [Instagram] x: {kind_text}")

    monkeypatch.setattr(generic, "attempt", failing_attempt)
    downloader, edits = fake_downloader("https://www.instagram.com/reel/C0abcdefghi/")
    downloader._bot_msg.edit_text = lambda text, **kwargs: events.append(
        ("reply", text)
    )
    downloader.start()
    expected = [
        (
            "reply",
            (
                BotText.blocked.format(site="Instagram")
                if kind == "blocked"
                else BotText.error
            ),
        )
    ]
    if kind == "blocked":
        expected.append(("notice", "instagram", "blocked", ["direct"]))
    assert events == expected


def test_handler_failure_notifies(monkeypatch):
    # failures outside BaseDownloader.start() get the same "The owner has been told" text, so the owner is told
    notices = []
    monkeypatch.setattr(
        errors,
        "notify_owners",
        lambda client, owners, site, kind, details, **kwargs: notices.append(
            (site, kind)
        ),
    )

    def blocked(*args):
        raise RuntimeError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(main, "youtube_entrance", blocked)
    message, replies = fake_message("https://youtu.be/abc")
    main.download_handler(FakeClient(), message)
    assert replies[-1] == BotText.blocked.format(site="YouTube")
    assert notices == [("youtube", "blocked")]


def test_flood_wait_retries_later(monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, interval, function):
            self.interval, self.function, self.daemon, self.started = (
                interval,
                function,
                False,
                False,
            )
            timers.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(main.threading, "Timer", FakeTimer)
    runs = []

    def entrance(client, bot_msg, url):
        runs.append(url)
        if len(runs) == 1:
            raise pyrogram.errors.FloodWait(value=30)

    monkeypatch.setattr(main, "youtube_entrance", entrance)
    message, replies = fake_message("https://youtu.be/abc")
    documents = []
    message.reply_document = lambda document, caption=None, **kwargs: documents.append(
        caption
    )
    began = time.monotonic()
    main.download_handler(FakeClient(), message)
    assert time.monotonic() - began < 5  # no thread sleeps through the wait
    assert documents == [BotText.flood_wait.format(30)]
    [timer] = timers
    assert (timer.interval, timer.daemon, timer.started) == (30, True, True)
    assert runs == ["https://youtu.be/abc"]
    timer.function()  # the wait is over: the job goes back into the queue (run inline here)
    assert runs == ["https://youtu.be/abc"] * 2


def test_flood_without_number_still_retries(monkeypatch):
    # FLOOD_SKIP_FAILED_WAIT and a bare Flood carry no seconds; Timer(None) would never fire
    timers = []
    monkeypatch.setattr(
        main.threading,
        "Timer",
        lambda interval, function: timers.append(interval) or FakeClient(),
    )
    message, _ = fake_message("https://youtu.be/abc")
    message.reply_document = lambda *args, **kwargs: None
    main.flood_wait(
        FakeClient(), message, pyrogram.errors.FloodSkipFailedWait(), retry=lambda: None
    )
    assert timers and isinstance(timers[0], int) and timers[0] > 0
