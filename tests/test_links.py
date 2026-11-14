import main
from config import BotText
from fakes import FakeClient, fake_message
from utils import extract_first_url


def test_extract_first_url(monkeypatch):
    assert extract_first_url("look https://youtu.be/abc, ok") == "https://youtu.be/abc"
    assert (
        extract_first_url("Title\nhttps://www.instagram.com/reel/X/?igsh=1")
        == "https://www.instagram.com/reel/X/?igsh=1"
    )
    assert extract_first_url("no link") is None
    assert extract_first_url(None) is None
    assert extract_first_url("(see https://youtu.be/abc).") == "https://youtu.be/abc"

    # the download handler sends that first URL, not the whole message, to the downloader
    urls = []
    monkeypatch.setattr(
        main, "youtube_entrance", lambda client, bot_msg, url: urls.append(url)
    )
    message, _ = fake_message(
        "look at this https://youtu.be/abc lol https://youtu.be/other"
    )
    main.download_handler(FakeClient(), message)
    assert urls == ["https://youtu.be/abc"]


def test_text_without_link_gets_hint(downloads):
    message, replies = fake_message("funny cats")
    main.download_handler(FakeClient(), message)
    assert replies == [BotText.no_link]
    assert downloads == []
