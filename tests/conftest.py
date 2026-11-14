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
