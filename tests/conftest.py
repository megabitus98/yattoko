# Safe env for every test, set before any app module is imported.
# Plain assignment (not setdefault) so a real .env or shell token never reaches the tests;
# load_dotenv() does not override variables that are already set.

import atexit
import ipaddress
import os
import shutil
import socket
import tempfile

_test_root = tempfile.mkdtemp(prefix="yattoko-tests-")
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
                "REDIS_HOST",
                "REDIS_PASSWORD",
                "REDIS_DB",
                "MAX_PARALLEL_JOBS",
                "TMP_BUDGET",
                "JOB_TIMEOUT",
                "OWN_PUBLIC_IPS",
                "PROXY_EXITS",
                "PROXY_PIN",
                "ENABLE_VIP",
                "PROVIDER_TOKEN",
                "FREE_DOWNLOAD",
                "TOKEN_PRICE",
                "RCLONE_PATH",
                "ENABLE_FFMPEG",
                "REENCODE_MAX_SECONDS",
                "APP_VERSION",
                "APP_RELEASE_TITLE",
                "APP_RELEASE_URL",
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


def _offline_resolver(host, port, family=0, type=0, proto=0, flags=0):
    # numeric IPv4 hosts resolve to themselves, every name to one public address; nothing is looked up
    try:
        address = str(ipaddress.IPv4Address(host))
    except ValueError:
        address = "142.250.0.1"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    # The host check runs for every download; its resolver default is bound when check_url is defined,
    # so patching socket.getaddrinfo would not reach it. Tests that need other answers pass a resolver.
    from utils import netcheck

    monkeypatch.setattr(netcheck.check_url, "__defaults__", (_offline_resolver,))


class InlineJobs:
    # a submitted job runs before submit() returns, so handler tests can check replies right after the call
    def submit(self, fn):
        fn()
        return 0


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch):
    import main

    monkeypatch.setattr(main, "JOBS", InlineJobs())
