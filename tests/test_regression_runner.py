import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yt_dlp

from engine import generic
from regression import run
from test_transcode import make_clip

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

LINK = {"name": "clip", "url": "https://www.youtube.com/watch?v=x", "vcodec": ["h264"], "audio": True, "duration_min": 1}


def h264(work: Path, size: str = "640x360") -> Path:
    return make_clip(work, codec="libx264", size=size)


def audio_only(work: Path) -> Path:
    # what TikTok once sent instead of its video
    out = work / "clip.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", out], check=True)
    return out


def raises(message):
    def fake(url, site, exit, opts, tmpdir, **kwargs):
        raise yt_dlp.utils.DownloadError(message)

    return fake


def writes(make):
    # stands in for yt-dlp: one finished file in the job's scratch directory
    def fake(url, site, exit, opts, tmpdir, **kwargs):
        work = tmpdir / "work"
        work.mkdir()
        shutil.move(make(work), tmpdir)
        shutil.rmtree(work)

    return fake


@pytest.mark.parametrize(
    "fake_attempt, link, status",
    [
        (raises("ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video"), LINK, "link_gone"),
        (raises("ERROR: [youtube] x: Video unavailable. This video has been removed by the uploader"), LINK, "link_gone"),
        (raises("ERROR: [youtube] x: Some new extractor breakage"), LINK, "downloader_broken"),
        pytest.param(writes(h264), LINK, "passed", marks=needs_ffmpeg),
        # without ENABLE_FFMPEG nothing is converted: VP9 shows one frame in Telegram for macOS
        pytest.param(writes(make_clip), LINK, "downloader_broken", marks=needs_ffmpeg),
        pytest.param(writes(audio_only), LINK, "downloader_broken", marks=needs_ffmpeg),
        # 640x360 where the source has 1080p (the Short that once came back 480x854)
        pytest.param(writes(h264), LINK | {"min_short_side": 1080}, "downloader_broken", marks=needs_ffmpeg),
    ],
)
def test_status_mapping(monkeypatch, fake_attempt, link, status):
    # the bot's own path from _download_fitting() down; only yt-dlp's attempt is faked
    monkeypatch.setattr(generic, "attempt", fake_attempt)
    result, downloader = run.run_link(link)
    downloader._tempdir.cleanup()
    assert result["name"] == "clip"
    assert result["status"] == status
    if status == "passed":
        assert (result["vcodec"], result["acodec"], result["width"], result["height"]) == ("h264", "aac", 640, 360)
        assert result["duration"] >= 1 and result["size"] > 0


def test_hevc_needs_hvc1_tag():
    tiktok = {"vcodec": ["hevc", "h264"], "audio": True}
    probe = {"vcodec": "hevc", "vtag": "hvc1", "acodec": "aac", "width": 1080, "height": 1920, "duration": 10.0, "size": 1}
    assert run.evaluate(probe, tiktok) == "passed"
    # hev1 does not play in Telegram on iPhones and Macs
    assert run.evaluate(probe | {"vtag": "hev1"}, tiktok) == "downloader_broken"


def test_exit_codes():
    assert run.exit_code(["passed", "passed"]) == 0
    assert run.exit_code(["passed", "link_gone"]) == 3
    assert run.exit_code(["link_gone", "downloader_broken", "passed"]) == 2


@needs_ffmpeg
def test_upload_sends_smallest_through_test_bot(monkeypatch, tmp_path, capsys):
    sizes = iter(["640x360", "320x180"])
    monkeypatch.setattr(generic, "attempt", writes(lambda work: h264(work, next(sizes))))
    links = tmp_path / "links.json"
    links.write_text(json.dumps([LINK | {"name": "big"}, LINK | {"name": "small", "url": "https://www.youtube.com/watch?v=y"}]))
    sent = []

    class FakeClient:
        # BaseDownloader._methods lists every send method; only send_video may be called
        send_document = send_audio = send_animation = send_photo = None

        def __init__(self, name, **kwargs):
            sent.append(("client", kwargs["bot_token"], kwargs["in_memory"]))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send_chat_action(self, *args, **kwargs):
            pass

        def send_video(self, chat_id, video, **kwargs):
            sent.append(("video", chat_id, Path(video).stat().st_size))
            return SimpleNamespace(video=SimpleNamespace(file_id="x"), document=None, audio=None, animation=None, photo=None)

    monkeypatch.setattr(run, "Client", FakeClient)
    monkeypatch.setenv("TEST_BOT_TOKEN", "9:regression")
    monkeypatch.setenv("TEST_CHAT_ID", "-100123")
    assert run.main(["--links", str(links), "--upload"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(line["name"], line["status"]) for line in lines] == [("big", "passed"), ("small", "passed"), ("upload", "passed")]
    small = next(line for line in lines if line["name"] == "small")
    assert sent == [("client", "9:regression", True), ("video", -100123, small["size"])]


def test_upload_needs_test_bot(monkeypatch, tmp_path):
    # checked before anything is downloaded; exit codes 2 and 3 mean something about the links
    monkeypatch.delenv("TEST_BOT_TOKEN", raising=False)
    monkeypatch.setattr(generic, "attempt", raises("must not be reached"))
    with pytest.raises(SystemExit) as stopped:
        run.main(["--links", str(tmp_path / "missing.json"), "--upload"])
    assert stopped.value.code not in (0, 2, 3)
