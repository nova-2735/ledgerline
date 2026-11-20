"""Database engine, sessions and schema creation."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.resolved_database_url
    connect_args: dict[str, object] = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args)
    if is_sqlite:
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


def init_db() -> None:
    from app.orm import Base

    Base.metadata.create_all(get_engine())


def reset_caches() -> None:
    """Drop cached engine and session factory (used when settings change, e.g. in tests)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


def ping() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
