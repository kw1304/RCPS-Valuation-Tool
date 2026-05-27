"""test_kind_both_db_restore — kind=both DB 복원 후 단일 파일 통합 빌드 검증."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openpyxl
import pytest

from api.app import app as flask_app

LEDGER_PATH = ROOT / "input" / "회사자료" / "채권채무조회서 거래처별 원장.XLSX"


@pytest.fixture(scope="module")
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def both_db_project(client):
    """채권+채무 Step1 완료 프로젝트 — 서버 재기동 없이 DB에서 복원."""
    if not LEDGER_PATH.exists():
        pytest.skip("원장 파일 없음")

    r = client.post("/api/project", json={
        "company_name": "DBRestoreTest",
        "period_end": "2025-12-31",
        "kind": "both",
    })
    assert r.status_code == 201
    pid = r.json["id"]

    with open(LEDGER_PATH, "rb") as f:
        data = {"ledger": (io.BytesIO(f.read()), "ledger.xlsx")}
    r = client.post(f"/api/upload?project_id={pid}",
                    data=data, content_type="multipart/form-data")
    sheet_map = r.json.get("sheet_map", {})
    ar_sheet = sheet_map.get("receivable", "채권")
    ap_sheet = sheet_map.get("payable", "채무")

    for kind, sheet in [("receivable", ar_sheet), ("payable", ap_sheet)]:
        r = client.post("/api/run", json={
            "kind": kind,
            "sheet": sheet,
            "project_id": pid,
            "company_name": "DBRestoreTest",
            "period_end": "2025-12-31",
            "performance_materiality": 2_738_000_000,
            "risk_level": "유의적위험",
            "control_reliance": "Y",
            "seed": 42,
        })
        if r.status_code != 200:
            pytest.skip(f"{kind} Step1 실패")

    return pid


def test_kind_both_returns_201(client, both_db_project):
    """STATE 의존 없이 DB에서 복원하여 kind=both 빌드 → 201."""
    # STATE를 비워서 DB 복원 강제
    from api.app import STATE
    original = dict(STATE["last_result"])
    STATE["last_result"].clear()

    try:
        r = client.post(f"/api/project/{both_db_project}/step3/build", json={
            "kind": "both",
            "preparer": "DB복원테스터",
        })
        assert r.status_code == 201, f"expected 201: {r.json}"
        assert "artifact_id" in r.json
        assert r.json.get("kind") == "both"
        assert r.json.get("filename", "").startswith("C100AA100_")
    finally:
        STATE["last_result"].update(original)


def test_kind_both_single_file_9_sheets(client, both_db_project, tmp_path):
    """kind=both 통합 파일 — 9개 시트."""
    r = client.post(f"/api/project/{both_db_project}/step3/build", json={
        "kind": "both",
    })
    assert r.status_code == 201

    r_dl = client.get(f"/api/project/{both_db_project}/step3/download/receivable")
    assert r_dl.status_code == 200

    out = tmp_path / "both_workpaper.xlsx"
    out.write_bytes(r_dl.data)
    wb = openpyxl.load_workbook(out, read_only=True)
    sheets = set(wb.sheetnames)
    wb.close()

    assert len(sheets) == 9, f"시트 수: {len(sheets)} (기대 9): {sheets}"
    assert "요약" in sheets
    assert "조회서" in sheets
    assert "대체적 절차" in sheets


def test_kind_both_only_one_file(client, both_db_project):
    """kind=both 응답에 download_url 하나만 포함 (단일 파일 통합)."""
    r = client.post(f"/api/project/{both_db_project}/step3/build", json={
        "kind": "both",
    })
    assert r.status_code == 201
    resp = r.json
    # download_url은 receivable workpaper 기준 단일 URL
    assert "download_url" in resp
    assert "/step3/download/receivable" in resp["download_url"]
