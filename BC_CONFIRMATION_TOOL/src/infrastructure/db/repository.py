from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine, select, delete
from sqlalchemy import text, event
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


def _migrate_fk_nullable(conn) -> None:
    """기존 extractedrecord.counterparty_id 가 NOT NULL 이면 nullable 로 재구축.

    과거 sentinel(0, 존재하지 않는 counterparty)을 NULL 로 정정하며 복사한다.
    이래야 PRAGMA foreign_keys=ON 에서 미매칭 회신(counterparty 없음)을 무결성
    위반 없이 저장할 수 있다. notnull 이 이미 0(또는 테이블 없음)이면 no-op."""
    info = list(conn.execute(text("PRAGMA table_info(extractedrecord)")))
    if not info:
        return  # 테이블 없음 → create_all 이 최신(nullable) 스키마로 생성
    cp = next((r for r in info if r[1] == "counterparty_id"), None)
    if cp is None or cp[3] == 0:   # r[3] = notnull 플래그
        return  # 이미 nullable
    cols = [r[1] for r in info]
    collist = ", ".join(cols)
    selcols = ", ".join("NULLIF(counterparty_id, 0)" if c == "counterparty_id" else c
                        for c in cols)
    conn.execute(text("PRAGMA foreign_keys=OFF"))  # 재구축 중 FK 검사 비활성
    conn.execute(text("ALTER TABLE extractedrecord RENAME TO _er_old"))
    SQLModel.metadata.tables["extractedrecord"].create(bind=conn)  # nullable 신스키마
    conn.execute(text(
        f"INSERT INTO extractedrecord ({collist}) SELECT {selcols} FROM _er_old"))
    conn.execute(text("DROP TABLE _er_old"))


def _apply_migrations(eng) -> None:
    with eng.connect() as conn:
        for table, cols in _MIGRATIONS.items():
            existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue  # 테이블 자체가 없으면 create_all 이 최신 스키마로 생성함
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        # extractedrecord.counterparty_id NOT NULL → nullable 재구축(0→NULL 정정).
        _migrate_fk_nullable(conn)
        # Counterparty 중복 방지 unique index (기존 테이블엔 create_all 이 제약 추가 못함).
        # 기존 DB에 이미 중복이 있으면 인덱스 생성이 실패하므로 — 서버 기동을 막지 않도록
        # 보류(신규 DB·중복 없는 DB만 적용). upsert_counterparty 가 1차 방어.
        if {r[1] for r in conn.execute(text("PRAGMA table_info(counterparty)"))}:
            try:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cp_project_name_branch "
                    "ON counterparty(project_id, canonical_name, branch)"
                ))
            except Exception:
                pass  # 기존 중복 존재 → 인덱스 보류(기동 우선)
        conn.commit()


def _enable_sqlite_fk(eng) -> None:
    """연결마다 PRAGMA foreign_keys=ON — SQLite 는 기본 FK 미강제(고아행 방지)."""
    @event.listens_for(eng, "connect")
    def _set_fk(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def get_engine(db_path: Path | None = None):
    p = db_path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{p}")
    _enable_sqlite_fk(eng)
    SQLModel.metadata.create_all(eng)
    _apply_migrations(eng)
    return eng


def create_project(session: Session, name: str, fiscal_date: str) -> Project:
    p = Project(name=name, fiscal_date=fiscal_date)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def renumber_counterparties_alphabetical(session: Session, project_id: int) -> None:
    """모든 조회대상 금융기관을 가나다순으로 BC-1..N 재부여.

    BC-GL-N·BC-CS-N 같은 출처 코드를 쓰지 않고 깔끔히 BC-1 부터 가나다(이름·지점 순).
    회신 매칭은 BC-N 문자열이 아니라 (정규화명, 지점)·counterparty_id 로 하므로 안전."""
    cps = list(session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ))

    def _key(c):
        name = c.canonical_name or ""
        # 한글로 시작하면 가나다 먼저, 영문/기타(KEB·KB 등)는 그 뒤로.
        is_korean = bool(name) and "가" <= name[0] <= "힣"
        return (0 if is_korean else 1, name, c.branch or "")

    ordered = sorted(cps, key=_key)
    for i, c in enumerate(ordered, 1):
        c.bc_no = f"BC-{i:02d}"   # 한자리수 제로패딩 (BC-01·BC-02 … 정렬·표기 정합)
        session.add(c)
    session.commit()


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
