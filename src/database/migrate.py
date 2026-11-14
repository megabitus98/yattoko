#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - migrate.py
# Modified 2026 by megabitus98 (fork): new file, startup check-and-ALTER for columns added after the first release

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_columns(engine: Engine, table: str, columns: dict[str, str]) -> list[str]:
    # create_all never adds columns to an existing table. `columns` maps name -> SQL type and default,
    # e.g. {"sponsorblock": "VARCHAR(8) NOT NULL DEFAULT 'disabled'"}; names come from code, never from users.
    existing = {column["name"] for column in inspect(engine).get_columns(table)}
    added = [name for name in columns if name not in existing]
    with engine.begin() as conn:
        for name in added:
            conn.execute(
                text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {columns[name]}')
            )
    return added
