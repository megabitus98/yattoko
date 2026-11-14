# Repository-level checks; they need a full git checkout, so the image's test target leaves them out.

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_BASE = "0d5bfcd"  # Katze-942/ytdlbot master this fork starts from

REMOVED = [
    ".github/FUNDING.yml",
    "assets/USD.png",
    "assets/CNY.png",
    "assets/tron.png",
    "assets/1.jpeg",
    "assets/instagram.png",
    ".github/workflows/upgrade.yml",
    ".github/workflows/builder.yaml",
    ".github/workflows/codeql-analysis.yml",
    ".github/dependabot.yml",
]


def test_no_funding_or_payment_assets():
    assert [path for path in REMOVED if (ROOT / path).exists()] == []


def test_notice_names_both_upstreams():
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "tgbot-collection/ytdlbot" in notice
    assert "Katze-942/ytdlbot" in notice


def test_readme_credit_first():
    head = "\n".join((ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:15])
    assert "https://github.com/tgbot-collection/ytdlbot" in head
    assert "https://github.com/Katze-942/ytdlbot" in head
    assert "Not affiliated" in head


def test_env_example_has_no_dead_vars():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for dead in ("RATE_LIMIT", "CAPTION_URL_LENGTH_LIMIT", "REDIS_HOST=redis", "mysql"):
        assert dead not in example


def test_modified_files_carry_notice():
    # deleted files (--diff-filter=d) have nothing left to carry the notice
    changed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", UPSTREAM_BASE, "--", "src"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert changed, "git diff found no changed files under src/"
    missing = [
        path
        for path in changed
        if path.endswith(".py") and "Modified 2026 by megabitus98 (fork)" not in (ROOT / path).read_text(encoding="utf-8")
    ]
    assert missing == []
