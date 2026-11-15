import importlib.util

import pytest

from config import config as cfg


def test_parse_id_list_basic():
    assert cfg.parse_id_list(" 1, 2 ,,3,", "X") == frozenset({1, 2, 3})


def test_parse_id_list_empty_is_empty():
    assert cfg.parse_id_list("", "X") == frozenset()
    assert cfg.parse_id_list(None, "X") == frozenset()


def test_parse_id_list_rejects_names():
    with pytest.raises(cfg.ConfigError, match="AUTHORIZED_USER") as excinfo:
        cfg.parse_id_list("1,@bob", "AUTHORIZED_USER")
    # the variable is named, the value never echoed
    assert "@bob" not in str(excinfo.value)


def test_parse_bool():
    assert cfg.parse_bool("TRUE", False) is True
    assert cfg.parse_bool(None, True) is True
    with pytest.raises(cfg.ConfigError) as excinfo:
        cfg.parse_bool("maybe", False)
    assert "maybe" not in str(excinfo.value)


def test_bool_env_names_variable(monkeypatch):
    monkeypatch.setenv("ENABLE_SEARCH", "maybe")
    with pytest.raises(cfg.ConfigError, match="ENABLE_SEARCH") as excinfo:
        cfg._bool_env("ENABLE_SEARCH")
    assert "maybe" not in str(excinfo.value)


def test_proxy_defaults():
    assert cfg.PROXY_EXITS == ["direct"]
    assert cfg.PROXY_PIN == {}
    assert not hasattr(cfg, "YT_DLP_PROXY")


def test_tg_max_size_from_mib(monkeypatch):
    # Load a separate copy of the module instead of importlib.reload(): an in-place reload would
    # replace ConfigError with a new class under every module that already imported the old one.
    monkeypatch.setenv("TG_NORMAL_MAX_SIZE", "10")
    spec = importlib.util.spec_from_file_location("config_fresh_copy", cfg.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.TG_NORMAL_MAX_SIZE == 10 * 1024 * 1024


def test_parse_ip_list():
    assert cfg.parse_ip_list(" 203.0.113.7, ,198.51.100.1", "X") == frozenset(
        {"203.0.113.7", "198.51.100.1"}
    )
    assert cfg.parse_ip_list(None, "X") == frozenset()
    with pytest.raises(cfg.ConfigError, match="OWN_PUBLIC_IPS") as excinfo:
        cfg.parse_ip_list("203.0.113.7,home.example", "OWN_PUBLIC_IPS")
    assert "home.example" not in str(excinfo.value)  # the list is a secret


def test_job_defaults():
    assert cfg.MAX_PARALLEL_JOBS == 2
    assert cfg.TMP_BUDGET == 2 * 4500 * 1024 * 1024
    assert cfg.JOB_TIMEOUT == 2700
    assert cfg.OWN_PUBLIC_IPS == frozenset()
