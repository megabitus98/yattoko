# Safe env for every test, set before any app module is imported.
# Plain assignment (not setdefault) so a real .env or shell token never reaches the tests;
# load_dotenv() does not override variables that are already set.

import atexit
import os
import shutil
import tempfile

_test_root = tempfile.mkdtemp(prefix="ytdlbot-tests-")
atexit.register(shutil.rmtree, _test_root, ignore_errors=True)

os.environ.update(
    {
        "APP_ID": "1",
        "APP_HASH": "test",
        "BOT_TOKEN": "1:test",
        "OWNER": "1",
        "AUTHORIZED_USER": "1,2",
        "DATA_DIR": os.path.join(_test_root, "data"),
        "TMPFILE_PATH": os.path.join(_test_root, "tmp"),
        "DB_DSN": "sqlite:///" + os.path.join(_test_root, "data", "ytdlbot.db"),
        "COOKIES_DIR": os.path.join(_test_root, "cookies"),
        # Blank means "use the code default" and keeps a local .env from switching features on.
        **dict.fromkeys(
            [
                "ENABLE_SEARCH",
                "ENABLE_DIRECT",
                "ENABLE_ARIA2",
                "ENABLE_SPDL",
                "ENABLE_STATS",
                "ENABLE_GROUPS",
                "M3U8_SUPPORT",
                "TG_NORMAL_MAX_SIZE",
            ],
            "",
        ),
    }
)
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)

import pytest  # noqa: E402  (after the env above on purpose)


@pytest.fixture
def downloads(monkeypatch):
    # Every way a handler can start work; a blocked or disabled path must reach none of them.
    import main

    calls = []
    for name in (
        "direct_entrance",
        "special_download_entrance",
        "youtube_entrance",
        "search_ytb",
    ):
        monkeypatch.setattr(
            main, name, lambda *args, _name=name, **kwargs: calls.append(_name)
        )
    return calls
