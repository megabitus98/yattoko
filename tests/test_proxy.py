import logging
from pathlib import Path

import pytest
from yt_dlp.networking.exceptions import ProxyError
from yt_dlp.utils import DownloadError

import config.config
from config import BotText
from config.config import ConfigError
from engine import errors, generic
from engine.proxy import exits_for, parse_exits, parse_pins
from fakes import fake_downloader
from utils import netcheck
from utils.redact import RedactingFormatter

PROXY = "http://proxy.example:8080"
CREDENTIALED = "http://u:p@proxy.example:8080"
BLOCKED = "ERROR: [youtube] x: Your IP is likely being blocked by YouTube"
UNAVAILABLE = (
    "ERROR: [youtube] x: Video unavailable. This video has been removed by the uploader"
)


@pytest.fixture
def run(monkeypatch):
    # Stands in for generic.attempt: records each exit and the host checks in order, raises the
    # error queued for that attempt (None succeeds). Nothing is fetched.
    events, outcomes, notices = [], [], []

    def fake_attempt(url, site, exit, opts, tmpdir, on_cookies_expired=None, choose=None):
        events.append(("attempt", exit))
        error = outcomes.pop(0)
        (Path(tmpdir) / ("x.mp4.part" if error else "x.mp4")).write_bytes(b"x")
        if error:
            raise error
        return {"id": "x"}

    real_check = netcheck.check_url

    def recording_check(url, own_ips, *args, **kwargs):
        events.append(("check", url))
        return real_check(url, own_ips, *args, **kwargs)

    def setup(exits, pins=None, url="https://www.youtube.com/watch?v=x"):
        monkeypatch.setattr(generic, "PROXY_EXITS", exits)
        monkeypatch.setattr(generic, "PROXY_PIN", pins or {})
        monkeypatch.setattr(config.config, "PROXY_EXITS", exits)
        downloader, edits = fake_downloader(url)
        # after the downloader exists: its __init__ runs the host check once on its own
        monkeypatch.setattr(netcheck, "check_url", recording_check)
        return downloader, edits

    monkeypatch.setattr(generic, "attempt", fake_attempt)
    monkeypatch.setattr(
        errors,
        "notify_owners",
        lambda client, owners, site, kind, details, **kwargs: notices.append(
            (site, kind, list(kwargs["exits"]))
        ),
    )
    return setup, events, outcomes, notices


def attempts(events):
    return [exit for name, exit in events if name == "attempt"]


def test_parse_exits_default():
    assert parse_exits(None) == ["direct"]
    assert parse_exits("") == ["direct"]
    assert parse_exits(f"direct,{PROXY}") == ["direct", PROXY]
    assert parse_exits(f" {PROXY} , direct ") == [PROXY, "direct"]
    assert parse_exits(f"https://proxy.example:8443,{CREDENTIALED}") == [
        "https://proxy.example:8443",
        CREDENTIALED,
    ]


@pytest.mark.parametrize(
    "raw",
    [
        "socks5://proxy.example:1080",
        f"direct,socks5h://u:p@proxy.example:1080",
        "proxy.example:8080",
        "http://",
        "http://proxy.example:notaport",
        "Direct",
    ],
)
def test_parse_exits_rejects_socks(raw):
    with pytest.raises(ConfigError, match="PROXY_EXITS") as excinfo:
        parse_exits(raw)
    # proxy URLs are secrets: the message never repeats one
    assert "proxy.example" not in str(excinfo.value) and "u:p" not in str(excinfo.value)


def test_pin_must_exist():
    with pytest.raises(ConfigError, match="PROXY_PIN") as excinfo:
        parse_pins("instagram=http://other.example:1", ["direct"])
    assert "other.example" not in str(excinfo.value)
    for raw in ("instagram", "=direct", "instagram="):
        with pytest.raises(ConfigError, match="PROXY_PIN"):
            parse_pins(raw, ["direct"])
    assert parse_pins(None, ["direct"]) == {}
    assert parse_pins(f" Instagram=direct , tiktok={PROXY} ", ["direct", PROXY]) == {
        "instagram": "direct",
        "tiktok": PROXY,
    }


def test_exits_for():
    exits = ["direct", PROXY]
    assert exits_for("youtube", exits, {"instagram": "direct"}) == exits
    assert exits_for("instagram", exits, {"instagram": "direct"}) == ["direct"]


def test_fallback_only_on_blocked(run):
    setup, events, outcomes, _ = run
    downloader, _ = setup(["direct", PROXY])
    outcomes[:] = [DownloadError(BLOCKED), None]
    files = downloader._download(downloader._setup_formats())
    assert attempts(events) == ["direct", PROXY]
    # the blocked attempt's leftovers are gone; only the successful attempt's file is sent
    assert [f.name for f in files] == ["x.mp4"]

    events.clear()
    downloader, edits = setup(["direct", PROXY])
    outcomes[:] = [DownloadError(UNAVAILABLE)]
    downloader.start()
    assert attempts(events) == ["direct"]
    assert edits == [BotText.unavailable]


def test_blocked_on_every_exit(run):
    setup, events, outcomes, notices = run
    downloader, edits = setup(["direct", PROXY])
    outcomes[:] = [DownloadError(BLOCKED), ProxyError("tunnel failed")]
    downloader.start()
    assert attempts(events) == ["direct", PROXY]
    assert edits == [BotText.blocked.format(site="YouTube")]
    # the notice names the exits by position, never by URL
    assert notices == [("youtube", "blocked", ["direct", "exit 2"])]


def test_pinned_site_never_falls_back(run):
    setup, events, outcomes, notices = run
    downloader, edits = setup(
        ["direct", PROXY],
        {"instagram": "direct"},
        url="https://www.instagram.com/reel/C0abcdefghi/",
    )
    outcomes[:] = [
        DownloadError("ERROR: [Instagram] x: HTTP Error 429: Too Many Requests")
    ]
    downloader.start()
    assert attempts(events) == ["direct"]
    assert edits == [BotText.blocked.format(site="Instagram")]
    assert notices == [("instagram", "blocked", ["direct"])]


def test_host_check_before_each_attempt(run):
    setup, events, outcomes, _ = run
    url = "https://www.youtube.com/watch?v=x"
    downloader, _ = setup(["direct", PROXY, "https://proxy.example:8443"], url=url)
    outcomes[:] = [DownloadError(BLOCKED), DownloadError(BLOCKED), None]
    downloader._download(downloader._setup_formats())
    assert events == [
        ("check", url),
        ("attempt", "direct"),
        ("check", url),
        ("attempt", PROXY),
        ("check", url),
        ("attempt", "https://proxy.example:8443"),
    ]


def test_host_check_refusal_stops_fallback(run, monkeypatch):
    setup, events, outcomes, _ = run
    downloader, edits = setup(["direct", PROXY])

    def refuse_second(url, own_ips, *args, **kwargs):
        events.append(("check", url))
        if len(events) > 1:
            raise netcheck.BlockedHost("resolves to a refused address")

    monkeypatch.setattr(netcheck, "check_url", refuse_second)
    outcomes[:] = [DownloadError(BLOCKED)]
    downloader.start()
    assert attempts(events) == ["direct"]
    assert edits == [BotText.unavailable]


def test_proxy_value_never_logged(run, caplog):
    setup, events, outcomes, _ = run
    caplog.set_level(logging.DEBUG)
    # a proxy exit that is blocked and followed by another: the fallback is logged for it
    downloader, _ = setup(["direct", CREDENTIALED, PROXY])
    # yt-dlp's real proxy errors name the host, not the URL (urllib3 form); the traceback is logged
    outcomes[:] = [
        DownloadError(BLOCKED),
        DownloadError(BLOCKED),
        ProxyError(
            "('Unable to connect to proxy', NewConnectionError(\"HTTPConnection("
            "host='proxy.example', port=8080): Failed to establish a new connection\"))"
        ),
    ]
    downloader.start()
    assert attempts(events) == ["direct", CREDENTIALED, PROXY]
    # the bot's own messages name the exit by position only
    assert not any("proxy.example" in r.getMessage() for r in caplog.records)
    # and what the root handler writes, tracebacks included, carries no part of the proxy URL
    formatter = RedactingFormatter("%(message)s")
    written = "\n".join(formatter.format(r) for r in caplog.records)
    assert "Traceback" in written
    assert "u:p@" not in written and "proxy.example" not in written
