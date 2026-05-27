"""Task 6: step5_auto_identify_pending — normalize 매칭으로 미회신 중복 제거."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from api.app import app as flask_app
from src.infrastructure.persistence import (
    get_session,
    WorkpaperRepository,
    ConfirmationReplyRepository,
    AlternativeProcedureRepository,
)


@pytest.fixture(scope="module")
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _create_project_with_sampling(client) -> str:
    """샘플링 완료된 프로젝트 생성 (채권)."""
    r = client.post("/api/project", json={
        "company_name": "normalize테스트",
        "period_end": "2025-12-31",
        "kind": "both",
    })
    assert r.status_code == 201
    pid = r.json["id"]

    # 채권·채무 결과 직접 DB 삽입
    sampling_result = {
        "decisions": [
            {"name": "(주)알파상사", "balance": 500_000, "is_key_item": True,
             "is_representative": False, "is_related_party": False,
             "is_excluded": False, "final_sampled": True},
            {"name": "베타코퍼레이션주식회사", "balance": 200_000, "is_key_item": False,
             "is_representative": True, "is_related_party": False,
             "is_excluded": False, "final_sampled": True},
        ],
        "size": {
            "key_item_threshold": 100_000, "key_item_ratio": 0.5,
            "confidence_factor": 1.6, "base_sample_size": 5.0,
            "final_sample_size": 2, "sample_interval": 120_000,
            "remaining_population": 700_000,
        },
        "completeness": {
            "rows": [{"group": "외상매출금", "ledger": 500_000, "fs": 500_000, "diff": 0}],
            "total_ledger": 500_000, "total_fs": 500_000, "total_diff": 0,
        },
        "mus": {
            "sample_interval": 120_000, "random_start": 60_000,
            "selections": [
                {"name": "(주)알파상사", "balance": 500_000, "cumulative": 500_000,
                 "selections": 4, "remainder_after": 60_000, "hit": True},
            ],
            "sampled_names": ["(주)알파상사"],
        },
        "population_amount": 700_000,
    }
    sampling_params = {
        "company_name": "normalize테스트", "period_end": "2025-12-31",
        "kind": "receivable", "performance_materiality": 200_000,
        "risk_level": "유의적위험", "control_reliance": "Y",
        "preparer": "", "reviewer": "",
    }

    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, "receivable")
        wp.sampling_result = json.dumps(sampling_result, ensure_ascii=False)
        wp.sampling_params = json.dumps(sampling_params, ensure_ascii=False)

    return pid


def test_normalize_match_removes_duplicate_pending(client):
    """(주)알파상사로 회신 등록 → auto_identify에서 '알파상사'(법인접미사 제거) 매칭 후 skip."""
    pid = _create_project_with_sampling(client)

    # ConfirmationReply에 party_name_matched = "(주)알파상사" 등록
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, "receivable")
        reply_repo = ConfirmationReplyRepository(s)
        reply_repo.create(
            workpaper_id=wp.id,
            party_name_raw="(주)알파상사",
            party_name_matched="(주)알파상사",
            status="matched",
            extracted_balance=500_000,
        )

    # auto_identify 실행
    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json

    # (주)알파상사는 회신 있으므로 skipped → pending에 없어야 함
    pending_names = [p["party_name"] for p in data.get("pending_parties", [])]
    assert "(주)알파상사" not in pending_names, (
        f"(주)알파상사가 미회신으로 잘못 등록됨: {pending_names}"
    )


def test_normalize_match_removes_suffix_variant(client):
    """'베타코퍼레이션주식회사'로 회신 등록 → '베타코퍼레이션주식회사'도 skip."""
    pid = _create_project_with_sampling(client)

    # ConfirmationReply에 법인접미사 포함 이름으로 등록
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, "receivable")
        reply_repo = ConfirmationReplyRepository(s)
        reply_repo.create(
            workpaper_id=wp.id,
            party_name_raw="베타코퍼레이션주식회사",
            party_name_matched="베타코퍼레이션주식회사",
            status="matched",
            extracted_balance=200_000,
        )

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json

    # sampled_parties에 "베타코퍼레이션주식회사" 있으므로 직접 매칭
    pending_names = [p["party_name"] for p in data.get("pending_parties", [])]
    assert "베타코퍼레이션주식회사" not in pending_names, (
        f"베타코퍼레이션주식회사가 미회신으로 잘못 등록됨"
    )


def test_no_reply_party_appears_as_pending(client):
    """회신 없는 거래처는 auto_identify 이후 pending에 나타나야 한다."""
    pid = _create_project_with_sampling(client)
    # 회신 없는 상태로 auto_identify 실행

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json

    # 둘 다 회신 없음 → 2건 created 또는 updated
    assert data["created"] + data["updated"] >= 1, (
        "회신 없는 거래처가 pending으로 생성되지 않음"
    )
    pending_names = [p["party_name"] for p in data.get("pending_parties", [])]
    assert len(pending_names) >= 1, "pending_parties 비어있음"
