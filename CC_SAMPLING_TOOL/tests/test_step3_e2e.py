"""Step 3 End-to-End 테스트 (v1.1.0 — generic_reporter 7시트 기준)."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openpyxl
import pytest

from api.app import app as flask_app
from src.infrastructure.persistence import get_session, WorkpaperRepository


LEDGER_PATH = ROOT / "input" / "회사자료" / "채권채무조회서 거래처별 원장.XLSX"
TEMPLATE_PATH = ROOT / "input" / "조서" / "7620_코스맥스비티아이_C100_AA100 채권 채무 조회_FY25.xlsx"
# generic_reporter 가 생성하는 9개 시트 (Toss 디자인 generic reporter)
EXPECTED_GENERIC_SHEETS = {
    "요약",
    "조회서",
    "표본규모 산출",
    "모집단 완전성",
    "Key item 매트릭스",
    "MUS 추출 내역",
    "주소 적정성",
    "회신 추적",
    "대체적 절차",
}


@pytest.fixture(scope="module")
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def sampled_project(client):
    """프로젝트 생성 → 업로드 → Step 1 실행."""
    if not LEDGER_PATH.exists():
        pytest.skip("원장 파일 없음")

    r = client.post("/api/project", json={
        "company_name": "S3E2ETest",
        "period_end": "2025-12-31",
        "kind": "receivable",
    })
    assert r.status_code == 201
    pid = r.json["id"]

    with open(LEDGER_PATH, "rb") as f:
        data = {"ledger": (io.BytesIO(f.read()), "ledger.xlsx")}
    r = client.post(f"/api/upload?project_id={pid}",
                    data=data, content_type="multipart/form-data")
    sheet_map = r.json.get("sheet_map", {})
    sheet = sheet_map.get("receivable", "채권")

    r = client.post("/api/run", json={
        "kind": "receivable",
        "sheet": sheet,
        "project_id": pid,
        "company_name": "S3E2ETest",
        "period_end": "2025-12-31",
        "performance_materiality": 2_738_000_000,
        "risk_level": "유의적위험",
        "control_reliance": "Y",
        "key_item_ratio": 0.75,
        "confidence_factor": 1.4,
        "excluded_parties": {"helloBiome safe": "제외"},
        "seed": 42,
        "preparer": "이슬기",
        "reviewer": "이병기",
    })
    assert r.status_code == 200
    return pid


def test_step3_build_returns_artifact(client, sampled_project):
    """Step 3 build → artifact_id + download_url 반환."""
    pid = sampled_project
    r = client.post(f"/api/project/{pid}/step3/build", json={
        "kind": "receivable",
        "template_id": "woongkye_standard",
        "preparer": "이슬기",
        "reviewer": "이병기",
    })
    assert r.status_code == 201, r.json
    data = r.json
    assert "artifact_id" in data
    assert "download_url" in data
    assert "filename" in data


def test_step3_download_returns_excel(client, sampled_project):
    """Step 3 download → xlsx 응답."""
    pid = sampled_project
    r = client.get(f"/api/project/{pid}/step3/download/receivable")
    assert r.status_code == 200
    assert any(ct in r.content_type for ct in ["spreadsheetml", "application/octet-stream", "zip"])


def test_step3_downloaded_xlsx_has_7_generic_sheets(client, sampled_project, tmp_path):
    """다운로드된 조서 xlsx에 generic_reporter 9개 시트가 모두 존재함.

    v1.2.0: Toss 디자인 generic reporter — 9시트 구성.
    """
    pid = sampled_project
    # build 재실행 (artifact 갱신)
    r_build = client.post(f"/api/project/{pid}/step3/build", json={
        "kind": "receivable",
        "template_id": "woongkye_standard",
        "preparer": "이슬기",
        "reviewer": "이병기",
    })
    assert r_build.status_code == 201

    r = client.get(f"/api/project/{pid}/step3/download/receivable")
    assert r.status_code == 200

    out = tmp_path / "workpaper.xlsx"
    out.write_bytes(r.data)
    wb = openpyxl.load_workbook(out, read_only=True)
    actual_sheets = set(wb.sheetnames)
    wb.close()

    missing = EXPECTED_GENERIC_SHEETS - actual_sheets
    assert not missing, f"누락 시트: {missing} | 실제: {actual_sheets}"
    assert len(actual_sheets) == 9, f"시트 수 불일치: {len(actual_sheets)} (기대 9)"


def test_step3_mark_done_sets_completed_at(client, sampled_project):
    """Step 3 mark-done → workpaper.step3_completed_at not None."""
    pid = sampled_project
    r = client.post(f"/api/project/{pid}/step3/mark-done", json={"kind": "receivable"})
    assert r.status_code == 200
    assert r.json.get("ok") is True
    assert r.json.get("step3_completed_at") is not None

    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        assert wp.step3_completed_at is not None, "step3_completed_at DB에 미기록"


def test_api_templates_endpoint(client):
    """GET /api/templates → woongkye_standard 포함."""
    r = client.get("/api/templates")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json]
    assert "woongkye_standard" in ids


def test_audit_trail_accumulates(client, sampled_project):
    """audit-trail API → step1_sampling, step3_export_workpaper 등 기록 존재."""
    pid = sampled_project
    r = client.get(f"/api/project/{pid}/audit-trail")
    assert r.status_code == 200
    actions = [t["action"] for t in r.json]
    assert "step1_sampling" in actions, f"step1_sampling 미기록 — 현재: {actions}"
    assert "step3_export_workpaper" in actions, f"step3_export_workpaper 미기록"
