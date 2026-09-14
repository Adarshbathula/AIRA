"""Database engine/session management (SQLAlchemy 2.0).

PostgreSQL is the production database (see docker-compose.yml); SQLite is
supported automatically as a zero-config dev/test fallback. The ORM layer is
the same for both.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_connect_args = {}
_engine_kwargs: dict = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
    _engine_kwargs = {"pool_pre_ping": True}
else:
    _engine_kwargs.update({"pool_size": 10, "max_overflow": 20})

engine = create_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_session() -> Session:
    """Direct session for scripts (not request-scoped)."""
    return SessionLocal()


def ensure_columns() -> list[str]:
    """Add columns introduced after a database was first created.

    The app intentionally has no migration framework (single-process, small
    schema); this keeps an existing dev/demo SQLite or Postgres database usable
    after an upgrade instead of requiring a wipe.
    """
    from sqlalchemy import inspect, text

    added: list[str] = []
    try:
        insp = inspect(engine)
        tables = set(insp.get_table_names())
    except Exception:  # pragma: no cover
        return added
    wanted = {
        "documents": {"content_hash": "VARCHAR(64)"},
    }
    for table, cols in wanted.items():
        if table not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for col, sqltype in cols.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {sqltype}"))
                    added.append(f"{table}.{col}")
    return added
