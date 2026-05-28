from fastapi.testclient import TestClient
from pathlib import Path
import pytest
from api.app import app

INPUT_DIR = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT")

@pytest.mark.skipif(not INPUT_DIR.exists(), reason="INPUT 없음")
def test_end_to_end_with_real_inputs():
    c = TestClient(app)
    # 1. project create
    pid = c.post("/api/projects", json={"name":"코스맥스비티아이","fiscal_date":"2025-12-31"}).json()["id"]

    # 2. upload G/L
    gl = INPUT_DIR / "FY2025_보조부원장_BTI.XLSX"
    with open(gl, "rb") as f:
        c.post(f"/api/projects/{pid}/upload/gl", files={"file":(gl.name, f.read())})

    # 3. upload current CS + prior CS + collateral + guarantee
    cs_cur = INPUT_DIR / "4150_AC 금융기관 조회_코스맥스비티아이_FY2025_V1.xlsx"
    cs_prior = INPUT_DIR / "코스맥스비티아이_금융기관 조회서1_Control Sheet_FY2024.xlsx"
    coll = INPUT_DIR / "비티아이 제공 담보현황 251231_ok.xlsx"
    guar = INPUT_DIR / "비티아이 제공 연대보증현황 251231.xlsx"
    for kind, p in [("cs", cs_cur), ("prior_cs", cs_prior), ("collateral", coll), ("guarantee", guar)]:
        if p.exists():
            with open(p, "rb") as f:
                c.post(f"/api/projects/{pid}/upload/{kind}", files={"file":(p.name, f.read())})

    # 4. sampling — G/L 거래처 컬럼에서 발견된 은행 (SAP 특성상 상대계정명 섞임, alias-matched만 추출)
    r = c.post(f"/api/projects/{pid}/sampling/run").json()
    assert len(r["parties"]) >= 5  # 주요 거래은행 (국민·신한·우리·하나·기업 등)

    # 5. crosscheck — CS auto-upsert로 나머지 증권사·보험사·해외지점 추가됨
    r = c.post(f"/api/projects/{pid}/crosscheck/run").json()
    assert "bidirectional" in r
    # CS 전체 BC-N (30+) 모두 counterparty로 등록되어야 함
    from sqlmodel import Session, select
    from src.infrastructure.db.models import Counterparty
    from src.infrastructure.db.repository import get_engine
    with Session(get_engine()) as s:
        cps = s.exec(select(Counterparty).where(Counterparty.project_id == pid)).all()
        assert len(cps) >= 25  # CS 30개 + G/L 8개 (대부분 겹침) → 약 30+

    # 6. upload 회신본 (모두)
    for sub in ["온라인", "우편"]:
        d = INPUT_DIR / sub
        if not d.exists(): continue
        for pdf in d.glob("*.pdf"):
            with open(pdf, "rb") as f:
                c.post(f"/api/projects/{pid}/upload/response", files={"file":(pdf.name, f.read())})

    # 7. parse responses
    r = c.post(f"/api/projects/{pid}/response/parse").json()
    assert "records" in r

    # 8. export 4150
    r = c.post(f"/api/projects/{pid}/workpaper/export")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "spreadsheetml" in ct or "xlsx" in ct
