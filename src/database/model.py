#!/usr/bin/env python3
# coding: utf-8
# Modified 2026 by megabitus98 (fork): engine from config.DB_DSN, SQLite WAL with busy timeout, insert-or-ignore init_user, default codec vcodec-auto (H.264 first)

from contextlib import contextmanager
from typing import Literal

from sqlalchemy import (
    BigInteger,
    Column,
    Enum,
    ForeignKey,
    Integer,
    create_engine,
    event,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from config import DB_DSN

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)  # telegram user id

    settings = relationship("Setting", back_populates="user", cascade="all, delete-orphan", uselist=False)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    quality = Column(Enum("1440p", "1080p", "720p", "480p", "240p"), nullable=False, default="1080p")
    format = Column(Enum("video", "audio", "document"), nullable=False, default="video")
    vcodec = Column(
        Enum("vcodec-auto", "vcodec-vp9", "vcodec-avc1", "vcodec-av01"),
        nullable=False,
        default="vcodec-auto",
    )
    sponsorblock = Column(Enum("disabled", "remove"), nullable=False, default="disabled")

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    user = relationship("User", back_populates="settings")


def make_engine(dsn: str) -> Engine:
    url = make_url(dsn)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return create_engine(dsn)
    # timeout: wait up to 30 s for another writer instead of failing with "database is locked"
    engine = create_engine(dsn, pool_size=5, connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def _enable_wal(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")

    return engine


engine = make_engine(DB_DSN)
# create_all adds missing tables only; columns added later go through database.migrate.ensure_columns
Base.metadata.create_all(engine)
SessionFactory = sessionmaker(bind=engine)


@contextmanager
def session_manager():
    s = SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_quality_settings(tgid) -> Literal["1440p", "1080p", "720p", "480p", "240p"]:
    with session_manager() as session:
        user = session.query(User).filter(User.user_id == tgid).first()
        if user and user.settings:
            return user.settings.quality

        return "1080p"


def get_format_settings(tgid) -> Literal["video", "audio", "document"]:
    with session_manager() as session:
        user = session.query(User).filter(User.user_id == tgid).first()
        if user and user.settings:
            return user.settings.format

        return "video"


def get_vcodec_settings(
    tgid,
) -> Literal["vcodec-auto", "vcodec-vp9", "vcodec-avc1", "vcodec-av01"]:
    with session_manager() as session:
        user = session.query(User).filter(User.user_id == tgid).first()
        if user and user.settings:
            return user.settings.vcodec

        return "vcodec-auto"


def get_sponsorblock_settings(tgid) -> Literal["disabled", "remove"]:
    with session_manager() as session:
        user = session.query(User).filter(User.user_id == tgid).first()
        if user and user.settings:
            return user.settings.sponsorblock
        return "disabled"


def set_user_settings(tgid: int, key: str, value: str):
    # set quality or format settings
    with session_manager() as session:
        # find user first
        user = session.query(User).filter(User.user_id == tgid).first()
        # upsert
        setting = session.query(Setting).filter(Setting.user_id == user.id).first()
        if setting:
            setattr(setting, key, value)
        else:
            session.add(Setting(user_id=user.id, **{key: value}))


def init_user(uid: int) -> None:
    # one INSERT OR IGNORE: a select-then-insert lets two parallel first messages both insert
    with session_manager() as session:
        session.execute(sqlite_insert(User).values(user_id=uid).on_conflict_do_nothing())
