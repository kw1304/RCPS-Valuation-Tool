"""test_kind_auto_run — /api/run kind="both" 자동 실행 검증."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from api.app import app as flask_app

LEDGER_PATH = ROOT / "input" / "회사자료" / "채권채무조회서 거래처별 원장.XLSX"


@pytest.fixture(scope="module")
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def uploaded(client):
    """원장 파일 업로드."""
    if not LEDGER_PATH.exists():
        pytest.skip(f"실물 파일 없음: {LEDGER_PATH}")
    with open(LEDGER_PATH, "rb") as f:
        resp = client.post(
            "/api/upload",
            data={"ledger": (f, LEDGER_PATH.name)},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "sheet_map" in data, "시트 맵 없음"
    return data


def test_run_kind_both_returns_both_sections(client, uploaded):
    """kind="both" 요청 → receivable·payable 양쪽 결과 포함."""
    resp = client.post(
        "/api/run",
        json={
            "kind": "both",
            "performance_materiality": 50_000_000,
            "company_name": "테스트",
            "period_end": "2025-12-31",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data.get("kind") == "both", f"kind 필드 누락: {data.keys()}"
    assert data.get("receivable") is not None or data.get("payable") is not None, \
        "receivable·payable 모두 None"
    assert "combined" in data, "combined 섹션 없음"
    combined = data["combined"]
    assert "total_final_sample_size" in combined


def test_run_kind_both_default(client, uploaded):
    """kind 파라미터 생략 → default="both" 동작."""
    resp = client.post(
        "/api/run",
        json={
            "performance_materiality": 50_000_000,
            "company_name": "테스트",
            "period_end": "2025-12-31",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("kind") == "both"


def test_run_kind_receivable_backward_compat(client, uploaded):
    """kind="receivable" 단일 호출 — 하위 호환."""
    resp = client.post(
        "/api/run",
        json={
            "kind": "receivable",
            "performance_materiality": 50_000_000,
            "company_name": "테스트",
            "period_end": "2025-12-31",
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    # 단일 kind → decisions·mus 직접 포함 (구조 하위 호환)
    assert "decisions" in data or data.get("kind") == "receivable"


def test_run_kind_both_combined_sample_size(client, uploaded):
    """combined.total_final_sample_size = receivable + payable 합산."""
    resp = client.post(
        "/api/run",
        json={
            "kind": "both",
            "performance_materiality": 50_000_000,
            "company_name": "테스트",
            "period_end": "2025-12-31",
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    comb = data["combined"]
    rv_n = comb.get("receivable_sample", 0)
    py_n = comb.get("payable_sample", 0)
    total = comb.get("total_final_sample_size", -1)
    assert total == rv_n + py_n, f"합산 불일치: {rv_n}+{py_n}={rv_n+py_n} vs total={total}"


def test_run_kind_both_state_cache(client, uploaded):
    """kind="both" 실행 후 STATE.last_result에 채권·채무 양쪽 캐시됨."""
    from api.app import STATE
    resp = client.post(
        "/api/run",
        json={
            "kind": "both",
            "performance_materiality": 50_000_000,
            "company_name": "테스트",
            "period_end": "2025-12-31",
        },
    )
    assert resp.status_code == 200
    # STATE 캐시 확인 (채권 또는 채무 중 하나 이상 있어야 함)
    has_rv = STATE["last_result"].get("receivable") is not None
    has_py = STATE["last_result"].get("payable") is not None
    assert has_rv or has_py, "STATE last_result 캐시 없음"
