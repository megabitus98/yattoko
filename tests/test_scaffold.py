import importlib
import os
import socket
import sys

import pytest


def test_imports():
    import curl_cffi  # noqa: F401
    import pyrogram
    import yt_dlp  # noqa: F401

    assert pyrogram.__version__ == "2.2.27"


def test_selfcheck_reports_versions():
    from selfcheck import run_selfcheck

    result = run_selfcheck()
    assert {"yt_dlp", "curl_cffi", "kurigram", "impersonation", "data_writable", "tmp_writable", "ok"} <= result.keys()
    assert result["kurigram"] == "2.2.27"
    assert result["impersonation"] is True
    assert result["ok"] is True


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a 0500 directory")
def test_selfcheck_flags_unwritable_dir(tmp_path, monkeypatch):
    from selfcheck import run_selfcheck

    read_only = tmp_path / "ro"
    read_only.mkdir()
    read_only.chmod(0o500)  # needs a non-root user; the image's test target runs as `app`
    monkeypatch.setenv("DATA_DIR", str(read_only))
    try:
        result = run_selfcheck()
    finally:
        read_only.chmod(0o700)
    assert result["data_writable"] is False
    assert result["ok"] is False


def test_import_main_creates_no_client(monkeypatch):
    import pyrogram

    def refuse(*args, **kwargs):
        raise AssertionError("no client or network at import time")

    monkeypatch.setattr(pyrogram.Client, "__init__", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.delitem(sys.modules, "main", raising=False)

    main = importlib.import_module("main")
    table = main.handler_table()
    assert table
    for handler_cls, callback, _filters, group in table:
        assert isinstance(handler_cls, type) and callable(callback) and isinstance(group, int)


def test_upload_tries_methods_in_order():
    from types import SimpleNamespace

    import pytest

    from engine.base import BaseDownloader

    class Fake(BaseDownloader):
        def _setup_formats(self):
            pass

        def _download(self, formats):
            pass

        def _start(self):
            pass

    dl = object.__new__(Fake)  # skip __init__: no Telegram message, no temp dir
    dl._tempdir = SimpleNamespace(cleanup=lambda: None)
    dl._format, dl._chat_id, dl._url, dl._quality, dl._vcodec = "video", 1, "u", "q", "v"
    dl._video_key = "test-upload-order"  # the file_id goes into the shared in-process cache
    dl._bot_msg = SimpleNamespace(edit_text=lambda text: None)
    calls = []

    def send(**kwargs):
        calls.append(kwargs["_type"])
        if kwargs["_type"] == "video":
            raise RuntimeError("save_file failed")
        if kwargs["_type"] == "animation":
            return None
        return SimpleNamespace(audio=SimpleNamespace(file_id="x"), document=None, video=None, animation=None, photo=None)

    dl.send_something = send
    dl._upload(files=["f"], meta={"caption": "c"})
    assert calls == ["video", "animation", "audio"]

    def always_fail(**kwargs):
        raise RuntimeError("save_file failed")

    dl.send_something = always_fail
    with pytest.raises(RuntimeError) as excinfo:
        dl._upload(files=["f"], meta={"caption": "c"})
    assert "/direct" not in str(excinfo.value)


def test_reply_calls_match_installed_kurigram():
    # kurigram 2.2.27 dropped `quote=` from Message.reply_*; fakes in handler tests accept any keyword,
    # so check the real signatures against every reply call in the source.
    import ast
    import inspect
    import pathlib

    from pyrogram import types

    import selfcheck

    src_root = pathlib.Path(selfcheck.__file__).parent
    bad = []
    for path in src_root.rglob("*.py"):
        if "tests" in path.relative_to(src_root).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            method = getattr(types.Message, node.func.attr, None) if node.func.attr.startswith("reply") else None
            if method is None:
                continue
            params = inspect.signature(method).parameters
            bad += [f"{path.name}:{node.lineno} {node.func.attr}({kw.arg}=)" for kw in node.keywords if kw.arg and kw.arg not in params]
    assert not bad, bad
