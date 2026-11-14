import threading

from database.cache import get_cache
from database.model import init_user, set_user_settings
from fakes import fake_downloader


def test_shared_between_jobs():
    # jobs run in their own threads; every one must see what another stored
    get_cache().hset("test-shared-between-jobs", mapping={"file_id": '["x"]'})
    seen = []
    job = threading.Thread(
        target=lambda: seen.append(get_cache().hgetall("test-shared-between-jobs"))
    )
    job.start()
    job.join()
    assert seen == [{"file_id": '["x"]'}]


def test_key_includes_sponsorblock():
    url = "https://www.youtube.com/watch?v=x"
    for user_id in (821, 822, 823):
        init_user(user_id)
    set_user_settings(822, "sponsorblock", "remove")
    keys = [
        fake_downloader(url, user_id=u)[0]._calc_video_key() for u in (821, 822, 823)
    ]
    assert keys[0] != keys[1]  # only SponsorBlock differs
    assert keys[0] == keys[2]  # same settings, same file
