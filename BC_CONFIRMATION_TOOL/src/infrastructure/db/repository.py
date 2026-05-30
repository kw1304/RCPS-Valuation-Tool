from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine, select, delete
from sqlalchemy import text
from .models import Project, Counterparty, FileAsset, ExtractedRecord

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "projects.db"

# create_all 은 누락된 테이블만 만들 뿐 기존 테이블의 신규 컬럼은 추가하지 않는다.
# 모델에 추가된 컬럼을 기존 SQLite DB에 idempotent 하게 반영하기 위한 경량 마이그레이션.
_MIGRATIONS = {
    "extractedrecord": {
        "needs_manual_review": "BOOLEAN NOT NULL DEFAULT 0",
        "form_family": "VARCHAR",
    },
}


def _apply_migrations(eng) -> None:
    with eng.connect() as conn:
        for table, cols in _MIGRATIONS.items():
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue  # 테이블 자체가 없으면 create_all 이 최신 스키마로 생성함
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        conn.commit()


def get_engine(db_path: Path | None = None):
    p = db_path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{p}")
    SQLModel.metadata.create_all(eng)
    _apply_migrations(eng)
    return eng


def create_project(session: Session, name: str, fiscal_date: str) -> Project:
    p = Project(name=name, fiscal_date=fiscal_date)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def list_counterparties(session: Session, project_id: int) -> list[Counterparty]:
    return session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id).order_by(Counterparty.bc_no)
    ).all()


def delete_counterparty(session: Session, project_id: int, cp_id: int) -> bool:
    """샘플링된 거래처 1건 제거 (감사인 판단으로 조회대상 제외).

    해당 거래처의 ExtractedRecord(회신 추출분)도 함께 삭제. 없으면 False.
    bc_no 연번은 이후 crosscheck 재실행 시 재부여되므로 여기서 재정렬 안 함.
    """
    from src.infrastructure.db.models import ExtractedRecord
    cp = session.get(Counterparty, cp_id)
    if cp is None or cp.project_id != project_id:
        return False
    session.exec(
        delete(ExtractedRecord).where(
            ExtractedRecord.project_id == project_id,
            ExtractedRecord.counterparty_id == cp_id,
        )
    )
    session.delete(cp)
    session.commit()
    return True


def upsert_counterparty(session: Session, project_id: int, canonical_name: str,
                        branch: str | None = None, is_foreign: bool = False) -> Counterparty:
    stmt = select(Counterparty).where(
        Counterparty.project_id == project_id,
        Counterparty.canonical_name == canonical_name,
        Counterparty.branch == branch,
    )
    existing = session.exec(stmt).first()
    if existing:
        return existing
    # auto BC-N
    n = len(list_counterparties(session, project_id)) + 1
    c = Counterparty(
        project_id=project_id,
        bc_no=f"BC-{n}",
        canonical_name=canonical_name,
        branch=branch,
        is_foreign=is_foreign,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c
