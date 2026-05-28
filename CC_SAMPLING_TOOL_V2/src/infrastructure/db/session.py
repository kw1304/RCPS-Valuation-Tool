"""SQLAlchemy engine + sessionmaker."""
from __future__ import annotations
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite: FK·CHECK constraint를 강제하기 위해 PRAGMA foreign_keys=ON.

    CHECK constraint는 SQLite에서 기본 활성화되어 있으나, FK는 PRAGMA 필요.
    다른 DB(PostgreSQL 등)에서는 무시됨 (sqlite3 모듈만 영향).
    """
    try:
        import sqlite3
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    except Exception:
        pass


def make_engine(url: str = "sqlite:///data/cc_v2.db"):
    return create_engine(url, future=True)


def make_session(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
