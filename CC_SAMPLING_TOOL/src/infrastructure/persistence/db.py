"""SQLAlchemy 엔진 + 세션 팩토리

WAL 모드 활성화 → 읽기/쓰기 동시성 향상.
DB 위치: 프로젝트 루트 data/projects.db
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

_ROOT = Path(__file__).resolve().parents[3]  # CC_SAMPLING_TOOL/
_DB_PATH = _ROOT / "data" / "projects.db"


def _get_db_url() -> str:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{_DB_PATH}"


engine = create_engine(
    _get_db_url(),
    echo=False,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_conn, _connection_record):
    """첫 연결 시 WAL 저널 모드 + Foreign Key 강제"""
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """테이블 없을 시 생성 (첫 실행용). 이미 있으면 no-op."""
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    """컨텍스트 매니저형 세션 — with get_session() as s: ..."""
    session: Session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
