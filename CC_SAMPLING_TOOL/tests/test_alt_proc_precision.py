"""대체적 절차 placeholder 정밀화 테스트.

PDF 회신이 DB에 존재할 때:
  - party_name_matched 있음 → skip (회신 성공)
  - party_name_matched 없지만 raw_name normalize가 sampled party와 일치 → skip (PDF 존재 확인)
  - 위 두 조건 모두 아닐 때만 placeholder 생성

목표: 실제 미회신 거래처만 placeholder (중복 제거).
"""
from __future__ import annotations

import json
import sys
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


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _setup_project(client, parties: list[tuple[str, float]]) -> str:
    """채권 sampling_result 주입 — parties: [(name, balance), ...]"""
    r = client.post("/api/project", json={
        "company_name": "AltProcPrecision테스트",
        "period_end": "2025-12-31",
        "kind": "receivable",
    })
    assert r.status_code == 201
    pid = r.json["id"]

    decisions = [
        {"name": n, "balance": b, "final_sampled": True}
        for n, b in parties
    ]
    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        wp.sampling_result = json.dumps({"decisions": decisions})
    return pid


def test_matched_reply_prevents_placeholder(client):
    """matched 회신이 있는 거래처 → placeholder 생성 금지."""
    pid = _setup_project(client, [("거래처A", 10_000_000), ("거래처B", 5_000_000)])

    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        ConfirmationReplyRepository(s).create(
            workpaper_id=wp.id,
            party_name_raw="거래처A",
            party_name_matched="거래처A",
            status="matched",
        )

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json
    names = [p["party_name"] for p in data["pending_parties"]]
    assert "거래처A" not in names, "matched 회신 있는 거래처A가 placeholder 생성됨"
    assert "거래처B" in names, "미회신 거래처B는 placeholder 생성 필요"


def test_mismatch_reply_prevents_placeholder(client):
    """mismatch 회신도 PDF가 존재 → placeholder 생성 금지 (대체절차 별도 필요)."""
    pid = _setup_project(client, [("거래처X", 20_000_000)])

    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        ConfirmationReplyRepository(s).create(
            workpaper_id=wp.id,
            party_name_raw="거래처X",
            party_name_matched="거래처X",
            status="mismatch",
            extracted_balance=18_000_000,
        )

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json
    names = [p["party_name"] for p in data["pending_parties"]]
    assert "거래처X" not in names, "mismatch 회신 있는 거래처X가 placeholder 생성됨"


def test_raw_name_normalize_prevents_duplicate_placeholder(client):
    """매칭 실패(party_name_matched=None)이더라도 raw_name normalize가
    sampled party normalize와 일치하면 placeholder 생성 금지.

    실제 케이스: "(주)거래처Y" 로 등록, PDF party_name_raw="거래처Y(주)"
    → 두 이름 모두 normalize("거래처y") → placeholder 중복 방지.
    """
    pid = _setup_project(client, [("(주)거래처Y", 8_000_000)])

    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        # 매칭 실패 회신 — raw_name만 존재, matched=None
        ConfirmationReplyRepository(s).create(
            workpaper_id=wp.id,
            party_name_raw="거래처Y(주)",    # raw 표기 다르지만 normalize 동일
            party_name_matched=None,         # 매칭 실패
            status="needs_review",
        )

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json
    names = [p["party_name"] for p in data["pending_parties"]]
    assert "(주)거래처Y" not in names, (
        "raw_name normalize 일치 거래처가 placeholder 중복 생성됨"
    )


def test_truly_unreplied_party_gets_placeholder(client):
    """PDF 회신이 전혀 없는 거래처 → placeholder 반드시 생성."""
    pid = _setup_project(client, [("진짜미회신거래처", 3_000_000)])

    # 회신 전혀 없음
    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json
    names = [p["party_name"] for p in data["pending_parties"]]
    assert "진짜미회신거래처" in names, "실제 미회신 거래처에 placeholder 미생성"


def test_evidence_registered_skips_placeholder(client):
    """사용자가 이미 증빙 등록한 AlternativeProcedure → placeholder 재생성 금지."""
    pid = _setup_project(client, [("증빙등록거래처", 12_000_000)])

    with get_session() as s:
        wp = WorkpaperRepository(s).get_or_create(pid, "receivable")
        AlternativeProcedureRepository(s).create(
            workpaper_id=wp.id,
            party_name="증빙등록거래처",
            reason="미회신",
            ledger_balance=12_000_000,
            procedure_type="후속입금",
            status="completed",
            conclusion="충분",
            evidence_artifact_ids=json.dumps(["artifact-001"]),
        )

    r = client.post(f"/api/project/{pid}/step5/auto-identify-pending")
    assert r.status_code == 201
    data = r.json
    names = [p["party_name"] for p in data["pending_parties"]]
    assert "증빙등록거래처" not in names, "증빙 등록된 거래처 placeholder 재생성됨"
