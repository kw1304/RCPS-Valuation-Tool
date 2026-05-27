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
    """테이블 없을 시 생성 + Week 5 v2 컬럼 마이그레이션."""
    Base.metadata.create_all(engine)
    _migrate_v2_columns()


def _migrate_v2_columns() -> None:
    """Week 5 v2 신규 컬럼을 기존 DB에 ADD COLUMN (idempotent).

    SQLite는 ALTER TABLE ADD COLUMN만 지원 (rename/drop 불가).
    이미 존재하는 컬럼이면 에러를 무시.
    """
    new_columns = [
        ("confirmation_replies", "declared_match",        "BOOLEAN"),
        ("confirmation_replies", "per_account_findings",  "TEXT"),
        ("confirmation_replies", "original_currency",     "VARCHAR(10) DEFAULT 'KRW'"),
        ("confirmation_replies", "decision_basis",        "VARCHAR(20)"),
        ("confirmation_replies", "top3_candidates",       "TEXT"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in new_columns:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                # 이미 존재하는 컬럼 — 무시
                conn.rollback()


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
