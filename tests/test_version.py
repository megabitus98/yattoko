# The running version: /about shows it, and the owners hear once about each new one (spec: releases design).

from types import SimpleNamespace

import pytest

import main
from config import BotText
from database.model import AppState, get_state, session_manager, set_state
from fakes import RecordingClient, fake_message
from utils.notify import announce_version


@pytest.fixture(autouse=True)
def empty_state():
    with session_manager() as session:
        session.query(AppState).delete()


def test_state_roundtrip():
    assert get_state("test-key") is None
    set_state("test-key", "a")
    set_state("test-key", "b")
    assert get_state("test-key") == "b"


def test_first_start_stores_silently():
    client = RecordingClient()
    assert announce_version(client, {1}, "v1.0.0", "feat: x", "https://example/r") == 0
    assert client.sent == []
    assert get_state("announced_version") == "v1.0.0"


def test_new_version_announced_once():
    set_state("announced_version", "v1.0.0")
    client = RecordingClient()
    assert (
        announce_version(
            client, {1, 2}, "v1.0.1", "deps: bump yt-dlp", "https://example/r"
        )
        == 2
    )
    text = client.sent[0][1]
    assert (
        "v1.0.1" in text
        and "v1.0.0" in text
        and "deps: bump yt-dlp" in text
        and "https://example/r" in text
    )
    assert (
        announce_version(
            client, {1, 2}, "v1.0.1", "deps: bump yt-dlp", "https://example/r"
        )
        == 0
    )
    assert len(client.sent) == 2


def test_dev_never_announces():
    set_state("announced_version", "v1.0.0")
    assert announce_version(RecordingClient(), {1}, "dev", "", "") == 0
    assert get_state("announced_version") == "v1.0.0"


def test_unreachable_owner_does_not_repeat(monkeypatch):
    # stored before sending: a restart after a failed send does not message the others again
    set_state("announced_version", "v1.0.0")
    client = RecordingClient(failing={1})
    assert announce_version(client, {1, 2}, "v1.0.1", "fix: x", "u") == 1
    assert announce_version(client, {1, 2}, "v1.0.1", "fix: x", "u") == 0
    assert [chat_id for chat_id, _ in client.sent] == [2]


def test_announce_survives_db_error(monkeypatch, caplog):
    def broken(key):
        raise RuntimeError("db down")

    monkeypatch.setattr("utils.notify.get_state", broken)
    assert announce_version(RecordingClient(), {1}, "v1.0.1", "fix: x", "u") == 0
    assert "Could not announce the version" in caplog.text


def test_about_shows_version(monkeypatch):
    monkeypatch.setattr(main, "APP_VERSION", "v1.2.3")
    sent = []
    client = SimpleNamespace(
        send_chat_action=lambda *args, **kwargs: None,
        send_message=lambda chat_id, text, **kwargs: sent.append(text),
    )
    main.about_handler(client, fake_message("/about")[0])
    assert sent == [f"{BotText.about.rstrip()}\n\nVersion: v1.2.3"]
