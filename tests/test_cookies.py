import io
import logging
import os

import pytest
from yt_dlp import YoutubeDL

from engine import DOWNLOADER_MAP
from engine.cookies import cookie_options, instagram_session_present
from engine.sites import display_name, site_for_url


def netscape(*names: str) -> str:
    # the header is required by the stdlib loader; fields: domain, subdomains, path, secure, expires, name, value
    lines = ["# Netscape HTTP Cookie File", "# test file, not written by yt-dlp"]
    lines += [
        f".instagram.com\tTRUE\t/\tTRUE\t4102444800\t{name}\tvalue-{name}"
        for name in names
    ]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "url, site",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
        # no extractor matches these (an ID too short for yt-dlp's YouTube pattern, short and share links),
        # the host still picks the site so its cookies are used
        ("https://youtu.be/x", "youtube"),
        ("https://instagr.am/p/C0abcdefghi/", "instagram"),
        ("https://www.instagram.com/share/reel/BAabcdef/", "instagram"),
        ("https://www.instagram.com/share/BAabcdef/", "instagram"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
        ("https://www.instagram.com/reel/C0abcdefghi/", "instagram"),
        ("https://www.tiktok.com/@a/video/1234567890", "tiktok"),
        ("https://vm.tiktok.com/ZMabcdef/", "tiktok"),
        ("https://example.com/page", "generic"),
        ("https://notinstagram.com/x", "generic"),
        ("http://[::1/x", "generic"),
    ],
)
def test_site_for_url(url, site):
    assert site_for_url(url) == site


def test_display_name():
    assert [display_name(s) for s in ("youtube", "instagram", "tiktok", "vimeo")] == [
        "YouTube",
        "Instagram",
        "TikTok",
        "Vimeo",
    ]


def test_cookie_options_present(tmp_path):
    text = netscape("sessionid")
    (tmp_path / "instagram.txt").write_text(text)
    cookiefile = cookie_options(tmp_path, "instagram")["cookiefile"]
    assert isinstance(cookiefile, io.StringIO)
    assert cookiefile.getvalue() == text


def test_cookie_options_missing(tmp_path):
    assert cookie_options(tmp_path, "instagram") == {}
    assert cookie_options(tmp_path / "absent", "instagram") == {}
    assert list(tmp_path.iterdir()) == []  # nothing created
    (tmp_path / "youtube.txt").write_text("\n")
    assert cookie_options(tmp_path, "youtube") == {}


@pytest.mark.parametrize(
    "bad",
    [
        ".instagram.com TRUE / TRUE 4102444800 sessionid FAKE-SECRET-VALUE",  # tabs turned into spaces
        ".instagram.com\tTRUE\t/\tTRUE\tsoon\tsessionid\tFAKE-SECRET-VALUE",  # expires not a number
        ".instagram.com\tFALSE\t/\tTRUE\t4102444800\tsessionid\tFAKE-SECRET-VALUE",  # flag disagrees with the dot
    ],
)
def test_malformed_line_never_printed(tmp_path, capsys, caplog, bad):
    # yt-dlp prints a rejected line, cookie value included, straight to stderr
    (tmp_path / "instagram.txt").write_text(netscape("csrftoken") + bad + "\n")
    caplog.set_level(logging.DEBUG)
    opts = {"quiet": True, "logger": logging.getLogger("yt_dlp")}
    with YoutubeDL(opts | cookie_options(tmp_path, "instagram")) as ydl:
        names = [c.name for c in ydl.cookiejar]
    assert names == ["csrftoken"]  # the good line still loads
    out, err = capsys.readouterr()
    assert "FAKE-SECRET" not in out + err + caplog.text
    assert "instagram.txt: skipped 1 malformed line" in caplog.text


def test_mounted_file_never_written(tmp_path):
    path = tmp_path / "instagram.txt"
    path.write_text(netscape("sessionid", "csrftoken"))
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    before = path.read_bytes(), path.stat().st_mtime_ns
    with YoutubeDL({"quiet": True, **cookie_options(tmp_path, "instagram")}) as ydl:
        # loaded from the copy; close() then writes the jar back to that copy
        assert instagram_session_present(ydl)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    "names, present", [(("sessionid", "csrftoken"), True), (("csrftoken",), False)]
)
def test_instagram_session_detection(names, present):
    with YoutubeDL({"quiet": True, "cookiefile": io.StringIO(netscape(*names))}) as ydl:
        assert instagram_session_present(ydl) is present


def test_instagram_not_in_spdl_map():
    assert "instagram.com" not in DOWNLOADER_MAP
