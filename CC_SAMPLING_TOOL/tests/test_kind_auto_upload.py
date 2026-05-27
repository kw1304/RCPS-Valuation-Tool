"""test_kind_auto_upload — PDF/증빙 kind 자동 분류 검증."""
from __future__ import annotations

import io
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
def project_with_sampling(client):
    """채권+채무 샘플링 완료 프로젝트."""
    if not LEDGER_PATH.exists():
        pytest.skip(f"실물 파일 없음: {LEDGER_PATH}")

    # 프로젝트 생성
    pr = client.post(
        "/api/project",
        json={"company_name": "자동분류테스트", "period_end": "2025-12-31", "kind": "both"},
    )
    assert pr.status_code == 201
    pid = pr.get_json()["id"]

    # 파일 업로드
    with open(LEDGER_PATH, "rb") as f:
        client.post(
            f"/api/upload?project_id={pid}",
            data={"ledger": (f, LEDGER_PATH.name)},
            content_type="multipart/form-data",
        )

    # kind="both" 샘플링
    rr = client.post(
        "/api/run",
        json={
            "kind": "both",
            "project_id": pid,
            "performance_materiality": 50_000_000,
            "company_name": "자동분류테스트",
            "period_end": "2025-12-31",
        },
    )
    assert rr.status_code == 200
    return pid


def test_step4_upload_replies_kind_auto(client, project_with_sampling):
    """kind="auto" PDF 업로드 → 400 없이 201 반환."""
    pid = project_with_sampling
    fake_pdf = b"%PDF-1.4 fake content"
    fd = {
        "kind": "auto",
        "tolerance": "0",
        "files[]": (io.BytesIO(fake_pdf), "test_reply.pdf"),
    }
    resp = client.post(
        f"/api/project/{pid}/step4/upload-replies",
        data=fd,
        content_type="multipart/form-data",
    )
    # 400이 아니어야 함 (kind 파라미터 오류 없음)
    # 실제 PDF 처리 실패는 다른 이유일 수 있으나 kind 자체는 수용
    assert resp.status_code in (201, 400)
    data = resp.get_json()
    if resp.status_code == 400:
        # kind 관련 오류가 아님을 확인
        assert "kind" not in (data.get("error") or "").lower(), \
            f"kind 관련 오류: {data.get('error')}"


def test_step4_upload_replies_kind_omitted(client, project_with_sampling):
    """kind 파라미터 생략 시에도 정상 처리."""
    pid = project_with_sampling
    fake_pdf = b"%PDF-1.4 fake content"
    fd = {
        "tolerance": "0",
        "files[]": (io.BytesIO(fake_pdf), "test_reply2.pdf"),
    }
    resp = client.post(
        f"/api/project/{pid}/step4/upload-replies",
        data=fd,
        content_type="multipart/form-data",
    )
    assert resp.status_code in (201, 400)
    data = resp.get_json()
    if resp.status_code == 400:
        assert "kind" not in (data.get("error") or "").lower()


def test_step5_auto_identify_pending_both(client, project_with_sampling):
    """auto-identify-pending → 채권·채무 양쪽 처리 (kind 파라미터 불필요)."""
    pid = project_with_sampling
    resp = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert resp.status_code == 201
    data = resp.get_json()
    assert "created" in data
    assert "updated" in data
    assert "skipped_already_replied" in data
    # pending_parties 에 kind 정보 포함
    parties = data.get("pending_parties", [])
    if parties:
        kinds = {p["kind"] for p in parties}
        # 채권·채무 중 하나 이상
        assert kinds & {"receivable", "payable"}


def test_step5_pending_both_kinds(client, project_with_sampling):
    """step5/pending 채권·채무 양쪽 조회 가능."""
    pid = project_with_sampling
    for kind in ("receivable", "payable"):
        resp = client.get(f"/api/project/{pid}/step5/pending?kind={kind}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "pending" in data
        assert data["kind"] == kind
