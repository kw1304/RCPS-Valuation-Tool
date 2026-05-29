from fastapi.testclient import TestClient
from pathlib import Path
from api.app import app


def test_parse_response_returns_records():
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name": "X", "fiscal_date": "2025-12-31"}).json()["id"]
    src = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT/온라인")
    if not src.exists():
        import pytest
        pytest.skip("샘플 PDF 없음")
    # 일부 회신본은 '해당 거래 없음'(무거래)이라 record 0건이 정상이다.
    # glob 순서 의존을 피하기 위해 여러 건 업로드해 데이터 보유 회신본을 포함시킨다.
    pdfs = list(src.glob("*.pdf"))[:8]
    if not pdfs:
        import pytest
        pytest.skip("샘플 PDF 없음")
    for p in pdfs:
        with open(p, "rb") as f:
            c.post(f"/api/projects/{pid}/upload/response", files={"file": (p.name, f.read())})
    r = c.post(f"/api/projects/{pid}/response/parse")
    assert r.status_code == 200
    body = r.json()
    assert "records" in body
    # 최소 AC1 또는 AC2 record 1건
    assert any(rec.get("section") in {"AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "AC7", "AC8"} for rec in body["records"])
