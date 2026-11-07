# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Martin Levi Ketta
"""Database engine and declarative base.

Plugins that add tables should subclass ``Base`` from this module; the tables
are created at startup after all plugins have been loaded.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        # Requests run in a thread pool; each request gets its own session.
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
