import threading
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from config import DATA_DIR, ConfigError, check_paths
from database import model
from database.migrate import ensure_columns
from database.model import make_engine


def test_wal_enabled(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_init_user_concurrent(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path}/u.db")
    model.Base.metadata.create_all(engine)
    monkeypatch.setattr(model, "SessionFactory", sessionmaker(bind=engine))

    barrier = threading.Barrier(8)
    errors = []

    def worker():
        barrier.wait()
        try:
            model.init_user(42)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with model.session_manager() as session:
        assert session.query(model.User).filter(model.User.user_id == 42).count() == 1


def test_ensure_columns_adds_missing(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/m.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE settings (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO settings (id) VALUES (1)"))
    columns = {"sponsorblock": "VARCHAR(8) NOT NULL DEFAULT 'disabled'"}

    assert ensure_columns(engine, "settings", columns) == ["sponsorblock"]
    assert "sponsorblock" in {
        c["name"] for c in inspect(engine).get_columns("settings")
    }
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT sponsorblock FROM settings")).scalar()
            == "disabled"
        )
    assert ensure_columns(engine, "settings", columns) == []


def test_tmp_inside_data_refused():
    with pytest.raises(ConfigError):
        check_paths("/data", "/data/tmp")
    assert check_paths("/data", "/tmp/ytdlbot") is None


def test_tmp_and_data_overlap_refused():
    # the startup purge empties the temp dir, so the database must not sit inside it either
    with pytest.raises(ConfigError):
        check_paths("/data", "/data")
    with pytest.raises(ConfigError):
        check_paths("/tmp/data", "/tmp")
    assert check_paths("/data", "/data2") is None


def test_client_workdir_is_data_dir():
    import main

    app = main.create_app()
    assert app.workdir == Path(DATA_DIR)
