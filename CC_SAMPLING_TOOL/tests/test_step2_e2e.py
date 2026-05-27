"""Step 2 End-to-End 테스트 (Week 2)."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from api.app import app as flask_app
from src.infrastructure.persistence import get_session, WorkpaperRepository


LEDGER_PATH = ROOT / "input" / "회사자료" / "채권채무조회서 거래처별 원장.XLSX"


@pytest.fixture(scope="module")
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def project_and_sampled(client):
    """프로젝트 생성 → 업로드 → Step 1 샘플링까지 실행."""
    if not LEDGER_PATH.exists():
        pytest.skip("원장 파일 없음")

    # 프로젝트 생성
    r = client.post("/api/project", json={
        "company_name": "S2E2ETest",
        "period_end": "2025-12-31",
        "kind": "receivable",
    })
    assert r.status_code == 201
    pid = r.json["id"]

    # 파일 업로드
    with open(LEDGER_PATH, "rb") as f:
        data = {"ledger": (io.BytesIO(f.read()), "ledger.xlsx")}
    r = client.post(f"/api/upload?project_id={pid}",
                    data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    sheet_map = r.json.get("sheet_map", {})
    sheet = sheet_map.get("receivable", "채권")

    # Step 1 샘플링
    r = client.post("/api/run", json={
        "kind": "receivable",
        "sheet": sheet,
        "project_id": pid,
        "company_name": "S2E2ETest",
        "period_end": "2025-12-31",
        "performance_materiality": 2_738_000_000,
        "risk_level": "유의적위험",
        "control_reliance": "Y",
        "key_item_ratio": 0.75,
        "confidence_factor": 1.4,
        "excluded_parties": {"helloBiome safe": "제외"},
        "seed": 42,
    })
    assert r.status_code == 200
    return pid, r.json


def test_step2_build_returns_artifact(client, project_and_sampled):
    """Step 2 build → artifact_id + download_url 반환."""
    pid, _ = project_and_sampled
    r = client.post(f"/api/project/{pid}/step2/build", json={
        "kind": "receivable",
        "reply_deadline": "2026-02-28",
        "contact_info": {"email": "audit@wc.com", "phone": "02-0000-0000"},
        "party_contacts": {},
    })
    assert r.status_code == 201, r.json
    data = r.json
    assert "artifact_id" in data
    assert "download_url" in data
    assert data["party_count"] > 0


def test_step2_download_returns_excel(client, project_and_sampled):
    """Step 2 download → xlsx 파일 응답."""
    pid, _ = project_and_sampled
    # build 먼저 실행 (이미 fixture에서 됐을 수도 있으나 재실행)
    client.post(f"/api/project/{pid}/step2/build", json={
        "kind": "receivable",
        "reply_deadline": "2026-02-28",
        "contact_info": {},
        "party_contacts": {},
    })
    r = client.get(f"/api/project/{pid}/step2/download/receivable")
    assert r.status_code == 200
    assert "spreadsheetml" in r.content_type or "application/octet-stream" in r.content_type or "zip" in r.content_type


def test_step2_mark_sent_sets_completed_at(client, project_and_sampled):
    """Step 2 mark-sent → workpaper.step2_completed_at not None."""
    pid, _ = project_and_sampled
    r = client.post(f"/api/project/{pid}/step2/mark-sent", json={"kind": "receivable"})
    assert r.status_code == 200
    assert r.json.get("ok") is True
    assert r.json.get("step2_completed_at") is not None

    # DB 직접 확인
    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        assert wp.step2_completed_at is not None, "step2_completed_at DB에 미기록"


def test_step2_build_missing_step1_returns_400():
    """Step 1 미실행 프로젝트에 build 요청 시 400.

    STATE 오염 방지를 위해 별도 test_client 인스턴스 사용.
    """
    from api.app import STATE as APP_STATE
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as isolated_client:
        r = isolated_client.post("/api/project", json={
            "company_name": "NullSamplingTest",
            "period_end": "2025-12-31",
            "kind": "receivable",
        })
        pid = r.json["id"]
        # STATE 초기화: 이전 테스트의 last_result 및 current_project_id 격리
        APP_STATE["current_project_id"] = pid
        APP_STATE["last_result"] = {}

        r = isolated_client.post(f"/api/project/{pid}/step2/build", json={
            "kind": "receivable",
            "reply_deadline": None,
            "contact_info": {},
            "party_contacts": {},
        })
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.json}"
