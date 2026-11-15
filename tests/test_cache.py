import logging
import threading

import fakeredis
import redis

import database.cache as cache_module
from database.cache import get_cache
from database.model import init_user, set_user_settings
from engine.base import CACHE_TTL
from fakes import fake_downloader

PASSWORD = "hunter2-redis-secret"


class _FakeRedis:
    def __init__(self, fail=False, **kwargs):
        self.kwargs = kwargs
        self.fail = fail

    def ping(self):
        if self.fail:
            raise redis.AuthenticationError("invalid username-password pair")
        return True


def test_redis_settings_reach_the_client(monkeypatch):
    monkeypatch.setattr(cache_module, "REDIS_HOST", "redis.example")
    monkeypatch.setattr(cache_module, "REDIS_PASSWORD", PASSWORD)
    monkeypatch.setattr(cache_module, "REDIS_DB", 7)
    monkeypatch.setattr(
        cache_module.redis, "Redis", lambda **kwargs: _FakeRedis(**kwargs)
    )
    client = cache_module._connect()
    assert isinstance(client, _FakeRedis)
    assert client.kwargs["host"] == "redis.example"
    assert client.kwargs["password"] == PASSWORD
    assert client.kwargs["db"] == 7
    # a Redis that stops answering must not hang a job
    assert client.kwargs["socket_timeout"] and client.kwargs["socket_connect_timeout"]


def test_failed_login_falls_back_without_the_password(monkeypatch, caplog):
    monkeypatch.setattr(cache_module, "REDIS_HOST", "redis.example")
    monkeypatch.setattr(cache_module, "REDIS_PASSWORD", PASSWORD)
    monkeypatch.setattr(
        cache_module.redis, "Redis", lambda **kwargs: _FakeRedis(fail=True, **kwargs)
    )
    with caplog.at_level(logging.WARNING):
        client = cache_module._connect()
    assert isinstance(client, fakeredis.FakeStrictRedis)
    assert "AuthenticationError" in caplog.text
    assert PASSWORD not in caplog.text


def test_cache_entries_expire():
    # the shared Redis never evicts, so every entry needs a TTL
    downloader = fake_downloader("https://www.youtube.com/watch?v=ttl")[0]
    downloader._set_video_cache({"file_id": '["x"]'})
    assert 0 < get_cache().ttl(downloader._video_key) <= CACHE_TTL
    assert downloader._get_video_cache() == {"file_id": '["x"]'}


def test_cache_errors_are_a_miss(monkeypatch):
    class _Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise redis.ConnectionError("Connection refused")

            return fail

    downloader = fake_downloader("https://www.youtube.com/watch?v=down")[0]
    monkeypatch.setattr("engine.base.get_cache", lambda: _Down())
    assert downloader._get_video_cache() == {}
    downloader._set_video_cache({"file_id": '["x"]'})  # logged, not raised


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
