# Features restored from upstream (VIP quota and payments, rclone, ffmpeg extras): unreachable while switched off.

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

import config
import main
from config import BotText
from database import model
from engine import base
from fakes import FakeClient, fake_callback, fake_downloader, fake_message

VIP_CALLBACKS = {"buy", "send_invoice", "pre_checkout", "successful_payment"}


def callback_names(table):
    return {callback.__name__ for _cls, callback, _filters, _group in table}


def test_restored_switches_off_by_default():
    assert config.ENABLE_VIP is False
    assert config.ENABLE_FFMPEG is False
    assert config.RCLONE_PATH is None
    assert config.PROVIDER_TOKEN is None
    assert (config.FREE_DOWNLOAD, config.TOKEN_PRICE) == (3, 10)


def test_buy_not_registered_by_default():
    assert VIP_CALLBACKS & callback_names(main.handler_table()) == set()


@pytest.fixture
def quota_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(base, "check_quota", lambda uid: calls.append(("check", uid)))
    monkeypatch.setattr(base, "use_quota", lambda uid: calls.append(("use", uid)))
    return calls


def _download(monkeypatch, url="https://www.youtube.com/watch?v=quota"):
    downloader, edits = fake_downloader(url, user_id=2)
    monkeypatch.setattr(downloader, "_start", lambda: None)
    downloader.start()
    return edits


def test_no_quota_checks_by_default(monkeypatch, quota_calls):
    _download(monkeypatch)
    assert quota_calls == []


def test_quota_checked_and_used_when_vip_on(monkeypatch, quota_calls):
    monkeypatch.setattr(base, "ENABLE_VIP", True)
    _download(monkeypatch)
    assert quota_calls == [("check", 2), ("use", 2)]


def test_quota_exhausted_reply(monkeypatch):
    # the user gets the quota text, not the generic error, and nothing is charged
    used = []

    def exhausted(uid):
        raise model.QuotaExhausted()

    monkeypatch.setattr(base, "ENABLE_VIP", True)
    monkeypatch.setattr(base, "check_quota", exhausted)
    monkeypatch.setattr(base, "use_quota", used.append)
    assert _download(monkeypatch) == [BotText.quota_exhausted]
    assert used == []


def test_no_scheduler_by_default(monkeypatch):
    started = []
    monkeypatch.setattr(main, "BackgroundScheduler", lambda *a, **k: started.append(a))
    monkeypatch.setattr(main, "scheduler", None)
    main.create_app()
    assert started == []
    assert main.scheduler is None


def test_vip_on_registers_buy(monkeypatch):
    monkeypatch.setattr(main, "ENABLE_VIP", True)
    monkeypatch.setattr(main, "scheduler", None)
    assert VIP_CALLBACKS <= callback_names(main.handler_table())
    main.create_app()
    try:
        assert [job.func for job in main.scheduler.get_jobs()] == [model.reset_free]
    finally:
        main.scheduler.shutdown(wait=False)


def test_buy_callback_prices_from_table(monkeypatch):
    # count and price come from BUY_CHOICES, never from the callback data
    invoices = []

    class InvoiceClient(FakeClient):
        def send_invoice(self, *args, **kwargs):
            invoices.append((args, kwargs))

    monkeypatch.setattr(main, "PROVIDER_TOKEN", "provider-test")
    query, _answers = fake_callback("buy-40-3.5")
    main.send_invoice(InvoiceClient(), query)
    (chat_id, _title, _description, payload, currency, prices), kwargs = invoices[0]
    assert (chat_id, payload, currency) == (2, "40", "USD")
    assert [p.amount for p in prices] == [350]
    assert kwargs["provider_token"] == "provider-test"


def test_successful_payment_credits_quota(monkeypatch):
    monkeypatch.setattr(model, "ENABLE_VIP", True)
    model.init_user(31)
    before = model.get_paid_quota(31)
    message, replies = fake_message("", user_id=31)
    message.successful_payment = SimpleNamespace(
        total_amount=100, invoice_payload="10", provider_payment_charge_id="ch_test"
    )
    message.delete = lambda: None
    main.successful_payment(FakeClient(), message)
    assert model.get_paid_quota(31) == before + 10
    assert replies == [BotText.payment_done.format(free=model.FREE_DOWNLOAD, paid=before + 10)]


def _engine(tmp_path):
    return model.make_engine(f"sqlite:///{tmp_path}/vip.db")


def test_payment_tables_on_sqlite(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    model.create_schema(engine)
    schema = inspect(engine)
    assert "payments" in schema.get_table_names()
    assert {"free", "paid", "config"} <= {c["name"] for c in schema.get_columns("users")}

    monkeypatch.setattr(model, "SessionFactory", sessionmaker(bind=engine))
    monkeypatch.setattr(model, "ENABLE_VIP", True)
    model.init_user(5)
    model.use_quota(5)
    assert model.get_free_quota(5) == model.FREE_DOWNLOAD - 1


def test_slice1_database_upgraded(tmp_path, monkeypatch):
    # a users table from before the quota columns: every User query would fail without the upgrade
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id BIGINT NOT NULL UNIQUE)")
        )
        conn.execute(text("INSERT INTO users (user_id) VALUES (7)"))
    model.create_schema(engine)
    monkeypatch.setattr(model, "SessionFactory", sessionmaker(bind=engine))
    assert model.get_quality_settings(7) == "1440p"  # the default (2K) for a row without settings
    monkeypatch.setattr(model, "ENABLE_VIP", True)
    assert (model.get_free_quota(7), model.get_paid_quota(7)) == (model.FREE_DOWNLOAD, 0)


def test_rclone_skipped_when_unset(monkeypatch):
    # a whole download and upload, with every way to run rclone or copy the file out recorded
    assert config.RCLONE_PATH is None
    ran, copied = [], []
    monkeypatch.setattr(subprocess, "run", lambda args, *a, **k: ran.append(args))
    monkeypatch.setattr(subprocess, "Popen", lambda args, *a, **k: ran.append(args))
    for name in ("copy", "copy2", "copyfile", "move"):
        monkeypatch.setattr(shutil, name, lambda *a, **k: copied.append(a))

    sent = SimpleNamespace(video=SimpleNamespace(file_id="x"), document=None, audio=None, animation=None, photo=None)

    class SendingClient(FakeClient):
        def send_video(self, *args, **kwargs):
            return sent

    downloader, edits = fake_downloader("https://www.youtube.com/watch?v=rclone", user_id=2)
    downloader._client = SendingClient()

    def fake_download(formats):
        path = Path(downloader._tempdir.name, "video.mp4")
        path.write_bytes(b"x")
        return [path]

    monkeypatch.setattr(downloader, "_download", fake_download)
    downloader.start()
    assert edits[-1] == BotText.done
    assert not any("rclone" in str(args) for args in ran)
    assert copied == []


def test_provider_token_redacted(monkeypatch):
    from utils.redact import redact

    monkeypatch.setattr(config.config, "PROVIDER_TOKEN", "999999999:TEST:FakeProviderToken")
    assert "FakeProviderToken" not in redact("invoice with 999999999:TEST:FakeProviderToken failed")


def test_buy_menu_pre_checkout_and_start_quota(monkeypatch):
    sent, answered = [], []
    message, _replies = fake_message("/buy")
    message.reply_text = lambda text, reply_markup=None, **kwargs: sent.append(reply_markup)
    main.buy(FakeClient(), message)
    data = [button.callback_data for row in sent[0].inline_keyboard for button in row]
    assert data == list(main.BUY_CHOICES)

    class AnsweringClient(FakeClient):
        def answer_pre_checkout_query(self, query_id, **kwargs):
            answered.append((query_id, kwargs))

        def send_message(self, chat_id, text, **kwargs):
            sent.append(text)

    main.pre_checkout(AnsweringClient(), SimpleNamespace(id="q1"))
    assert answered == [("q1", {"ok": True})]

    monkeypatch.setattr(main, "ENABLE_VIP", True)
    monkeypatch.setattr(model, "ENABLE_VIP", True)
    message, _replies = fake_message("/start", user_id=32)
    main.start_handler(AnsweringClient(), message)
    assert sent[-1].endswith(BotText.quota.format(free=model.FREE_DOWNLOAD, paid=0))
