import importlib.util

import pytest

from config import config as cfg


def test_parse_id_list_basic():
    assert cfg.parse_id_list(" 1, 2 ,,3,", "X") == frozenset({1, 2, 3})


def test_parse_id_list_empty_is_empty():
    assert cfg.parse_id_list("", "X") == frozenset()
    assert cfg.parse_id_list(None, "X") == frozenset()


def test_parse_id_list_rejects_names():
    with pytest.raises(cfg.ConfigError, match="AUTHORIZED_USER"):
        cfg.parse_id_list("1,@bob", "AUTHORIZED_USER")


def test_parse_bool():
    assert cfg.parse_bool("TRUE", False) is True
    assert cfg.parse_bool(None, True) is True
    with pytest.raises(cfg.ConfigError):
        cfg.parse_bool("maybe", False)


def test_tg_max_size_from_mib(monkeypatch):
    # Load a separate copy of the module instead of importlib.reload(): an in-place reload would
    # replace ConfigError with a new class under every module that already imported the old one.
    monkeypatch.setenv("TG_NORMAL_MAX_SIZE", "10")
    spec = importlib.util.spec_from_file_location("config_fresh_copy", cfg.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.TG_NORMAL_MAX_SIZE == 10 * 1024 * 1024
