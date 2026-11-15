#!/usr/bin/env python3
# coding: utf-8
# Modified 2026 by megabitus98 (fork): engine from config.DB_DSN, SQLite WAL with busy timeout, insert-or-ignore init_user, default codec vcodec-auto (H.264 first), OwnerNotice table and claim_notice (one owner notice per site and kind a day), upstream's Payment table, quota columns and quota functions restored (used only with ENABLE_VIP), create_schema() adds the quota columns to an existing users table

import logging
import math
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import (
    BigInteger,
    Column,
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from config import DB_DSN, ENABLE_VIP, FREE_DOWNLOAD
from database.migrate import ensure_columns


class PaymentStatus:
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class QuotaExhausted(Exception):
    pass


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False)  # telegram user id
    free = Column(Integer, default=FREE_DOWNLOAD)
    paid = Column(Integer, default=0)
    config = Column(JSON)

    settings = relationship("Setting", back_populates="user", cascade="all, delete-orphan", uselist=False)
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")


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


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    method = Column(String(50), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(
        Enum(
            PaymentStatus.PENDING,
            PaymentStatus.COMPLETED,
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
        ),
        nullable=False,
    )
    transaction_id = Column(String(100))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    user = relationship("User", back_populates="payments")


class OwnerNotice(Base):
    # when the owners were last told about a kind of failure on a site (utils/notify.py)
    __tablename__ = "owner_notices"
    __table_args__ = (UniqueConstraint("site", "kind"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    site = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    last_sent = Column(DateTime, nullable=False)


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


# Columns added to tables a released version already created. create_all adds missing tables only.
# Every User query selects these columns, so they are added whether or not ENABLE_VIP is on.
ADDED_COLUMNS = {
    "users": {
        "free": f"INTEGER DEFAULT {FREE_DOWNLOAD}",
        "paid": "INTEGER DEFAULT 0",
        "config": "JSON",
    },
}


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    for table, columns in ADDED_COLUMNS.items():
        ensure_columns(engine, table, columns)


engine = make_engine(DB_DSN)
create_schema(engine)
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


def claim_notice(site: str, kind: str, now: datetime) -> bool:
    # True (and now recorded) when nothing went out for this pair in the last 24 h. One statement, so two
    # jobs failing at once cannot both claim: insert, or move last_sent on only if it is a day old.
    # Callers pass UTC; SQLite stores the time without its zone.
    statement = (
        sqlite_insert(OwnerNotice)
        .values(site=site, kind=kind, last_sent=now)
        .on_conflict_do_update(
            index_elements=["site", "kind"],
            set_={"last_sent": now},
            where=OwnerNotice.last_sent <= now - timedelta(days=1),
        )
    )
    with session_manager() as session:
        return session.execute(statement).rowcount == 1


# Quota, restored from upstream. The callers (engine/base.py, main.py) call these only with ENABLE_VIP on.


def get_free_quota(uid: int):
    if not ENABLE_VIP:
        return math.inf

    with session_manager() as session:
        data = session.query(User).filter(User.user_id == uid).first()
        if data:
            return data.free
        return FREE_DOWNLOAD


def get_paid_quota(uid: int):
    if ENABLE_VIP:
        with session_manager() as session:
            data = session.query(User).filter(User.user_id == uid).first()
            if data:
                return data.paid

            return 0

    return math.inf


def check_quota(uid: int):
    if not ENABLE_VIP:
        return

    with session_manager() as session:
        data = session.query(User).filter(User.user_id == uid).first()
        if data and (data.free + data.paid) <= 0:
            raise QuotaExhausted()


def use_quota(uid: int):
    # use free first, then paid
    if not ENABLE_VIP:
        return

    with session_manager() as session:
        user = session.query(User).filter(User.user_id == uid).first()
        if user:
            if user.free > 0:
                user.free -= 1
            elif user.paid > 0:
                user.paid -= 1
            else:
                raise QuotaExhausted()


def reset_free():
    # the daily job main.create_app() schedules with ENABLE_VIP
    with session_manager() as session:
        session.query(User).update({User.free: FREE_DOWNLOAD})


def credit_account(who, total_amount: int, quota: int, transaction, method="stripe"):
    with session_manager() as session:
        user = session.query(User).filter(User.user_id == who).first()
        if user:
            dollar = total_amount / 100
            user.paid += quota
            logging.info("user %d credited with %d tokens, payment:$%.2f", who, user.paid, dollar)
            session.add(
                Payment(
                    method=method,
                    amount=total_amount,
                    status=PaymentStatus.COMPLETED,
                    transaction_id=transaction,
                    user_id=user.id,
                )
            )
            session.commit()
            return user.free, user.paid

        return None, None
