"""미회신 자동 식별 테스트 — step5/auto-identify-pending endpoint."""
from __future__ import annotations

import json
import pytest
from pathlib import Path


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from api.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def project_with_sampling(client):
    """프로젝트 생성 + 채권/채무 sampling_result 직접 주입."""
    r = client.post("/api/project", json={
        "company_name": "Auto-Identify-Test",
        "period_end": "2025-12-31",
        "kind": "both",
        "audit_firm": "테스트감사법인",
    })
    assert r.status_code == 201
    proj = r.get_json()
    pid = proj["id"]

    # DB에 sampling_result 직접 주입
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.infrastructure.persistence import get_session, WorkpaperRepository
    import json as _json

    receivable_decisions = [
        {"name": "거래처A", "balance": 10000000, "final_sampled": True},
        {"name": "거래처B", "balance": 5000000, "final_sampled": True},
        {"name": "거래처C", "balance": 3000000, "final_sampled": False},  # 미선택
    ]
    payable_decisions = [
        {"name": "거래처D", "balance": 8000000, "final_sampled": True},
        {"name": "거래처E", "balance": 2000000, "final_sampled": True},
    ]

    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp_r = wp_repo.get_or_create(pid, "receivable")
        wp_r.sampling_result = _json.dumps({"decisions": receivable_decisions})
        wp_p = wp_repo.get_or_create(pid, "payable")
        wp_p.sampling_result = _json.dumps({"decisions": payable_decisions})

    return pid


# ── 기본 자동 식별 ────────────────────────────────────────────────────────────

def test_auto_identify_creates_pending_for_all_sampled(client, project_with_sampling):
    """final_sampled 4건 → 전부 미회신 placeholder 생성."""
    pid = project_with_sampling
    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201, r.get_json()
    data = r.get_json()

    # 채권 2 + 채무 2 = 4건 생성
    assert data["created"] == 4
    assert data["updated"] == 0
    assert data["skipped_already_replied"] == 0
    assert len(data["pending_parties"]) == 4


def test_auto_identify_skips_already_replied(client, project_with_sampling):
    """이미 matched 회신 있는 거래처 → skipped."""
    pid = project_with_sampling

    from src.infrastructure.persistence import get_session, WorkpaperRepository, ConfirmationReplyRepository
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp_r = wp_repo.get_or_create(pid, "receivable")
        reply_repo = ConfirmationReplyRepository(s)
        reply_repo.create(
            workpaper_id=wp_r.id,
            party_name_raw="거래처A",
            party_name_matched="거래처A",
            status="matched",
        )

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.get_json()

    # 거래처A는 matched → skip, 나머지 3건 생성
    assert data["created"] == 3
    assert data["skipped_already_replied"] == 1


def test_auto_identify_idempotent(client, project_with_sampling):
    """두 번 호출해도 중복 생성 없음 — 두 번째는 updated."""
    pid = project_with_sampling

    r1 = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r1.status_code == 201
    d1 = r1.get_json()
    assert d1["created"] == 4

    r2 = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r2.status_code == 201
    d2 = r2.get_json()
    # 두 번째: 생성 0, 갱신 4
    assert d2["created"] == 0
    assert d2["updated"] == 4


def test_auto_identify_procedure_has_correct_reason(client, project_with_sampling):
    """생성된 AlternativeProcedure reason == '미회신', procedure_type == '미정'."""
    pid = project_with_sampling
    client.post(f"/api/project/{pid}/step5/auto-identify-pending")

    from src.infrastructure.persistence import get_session, WorkpaperRepository, AlternativeProcedureRepository
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        proc_repo = AlternativeProcedureRepository(s)
        wp_r = wp_repo.get_or_create(pid, "receivable")
        procs = proc_repo.list_by_workpaper(wp_r.id)
        assert len(procs) == 2
        for proc in procs:
            assert proc.reason == "미회신"
            assert proc.procedure_type == "미정"
            assert proc.conclusion == "needs_review"
            assert proc.status == "pending"


def test_auto_identify_missing_project(client):
    """존재하지 않는 프로젝트 → 404."""
    r = client.post("/api/project/nonexistent-pid/step5/auto-identify-pending")
    assert r.status_code == 404
