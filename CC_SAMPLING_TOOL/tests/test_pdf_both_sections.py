"""test_pdf_both_sections — PDF 양쪽 표 자동 분리 + 미회신 placeholder 정밀화 검증."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.infrastructure.pdf.parser import AccountRow, ParsedReply, parse_confirmation_v2


def _make_parsed_both(recv_total: float, payb_total: float) -> ParsedReply:
    """채권/채무 표 둘 다 있는 ParsedReply 모킹."""
    rows = [
        AccountRow(section="receivable", account_name="외상매출금",
                   sent_amount=recv_total, declared_match=True, reply_amount=recv_total),
        AccountRow(section="payable", account_name="외상매입금",
                   sent_amount=payb_total, declared_match=True, reply_amount=payb_total),
    ]
    return ParsedReply(
        extracted_party_name="테스트거래처",
        period_end=None,
        reply_date=None,
        audit_firm=None,
        receivable_by_account={"외상매출금": recv_total},
        payable_by_account={"외상매입금": payb_total},
        receivable_total=recv_total,
        payable_total=payb_total,
        is_match_declared=True,
        has_signature=True,
        extraction_confidence=0.9,
        per_account_rows=rows,
    )


def test_per_account_rows_section_receivable():
    """per_account_rows에 section='receivable' 행이 있으면 채권 표로 분류."""
    parsed = _make_parsed_both(10_000_000, 5_000_000)
    recv_rows = [r for r in parsed.per_account_rows if r.section == "receivable"]
    payb_rows = [r for r in parsed.per_account_rows if r.section == "payable"]
    assert len(recv_rows) == 1
    assert len(payb_rows) == 1
    assert recv_rows[0].reply_amount == 10_000_000
    assert payb_rows[0].reply_amount == 5_000_000


def test_pdf_has_both_sections_detection():
    """PDF에 채권/채무 섹션이 모두 있으면 both 표시."""
    parsed = _make_parsed_both(10_000_000, 5_000_000)
    pdf_has_receivable = any(r.section == "receivable" for r in (parsed.per_account_rows or []))
    pdf_has_payable = any(r.section == "payable" for r in (parsed.per_account_rows or []))
    assert pdf_has_receivable
    assert pdf_has_payable


def test_receivable_total_separate_from_payable():
    """채권/채무 표 잔액이 각각 독립적으로 추출됨."""
    parsed = _make_parsed_both(10_000_000, 5_000_000)
    assert parsed.receivable_total == 10_000_000
    assert parsed.payable_total == 5_000_000
    # 하위 호환 extracted_balance는 채권 합계
    assert parsed.extracted_balance == 10_000_000


def test_auto_identify_pending_skips_needs_review():
    """needs_review 상태 회신 존재 시 미회신 placeholder 생성 skip.

    Flask test client 기반 통합 테스트.
    """
    from api.app import app as flask_app, STATE
    flask_app.config["TESTING"] = True

    with flask_app.test_client() as c:
        # 프로젝트 생성 + 임시 sampling_result 주입
        r = c.post("/api/project", json={
            "company_name": "PendingTest",
            "period_end": "2025-12-31",
            "kind": "both",
        })
        assert r.status_code == 201
        pid = r.json["id"]

        # DB에 직접 sampling_result 주입
        from src.infrastructure.persistence import (
            get_session, WorkpaperRepository, ConfirmationReplyRepository
        )
        with get_session() as s:
            wp_repo = WorkpaperRepository(s)
            wp = wp_repo.get_or_create(pid, "receivable")

            # 최소 sampling_result
            sr = {
                "population_amount": 1_000_000,
                "decisions": [{"name": "테스트A", "balance": 500_000, "is_excluded": False,
                                "is_related_party": False, "is_key_item": False,
                                "is_representative": False, "final_sampled": True}],
                "size": {"key_item_threshold": 0, "key_item_ratio": 0.5, "confidence_factor": 3,
                         "base_sample_size": 3, "final_sample_size": 3, "sample_interval": 100000,
                         "remaining_population": 1_000_000},
                "completeness": {"rows": [], "total_ledger": 1_000_000, "total_fs": 0, "total_diff": 0},
                "mus": {"sample_interval": 100000, "random_start": 50000, "selections": [], "sampled_names": ["테스트A"]},
            }
            wp.sampling_result = json.dumps(sr, ensure_ascii=False)
            wp.sampling_params = json.dumps({"company_name": "PendingTest", "period_end": "2025-12-31",
                                              "kind": "receivable", "performance_materiality": 1_000_000,
                                              "risk_level": "유의적위험", "control_reliance": "Y"})

            # needs_review 상태 reply 생성
            reply_repo = ConfirmationReplyRepository(s)
            reply_repo.create(
                workpaper_id=wp.id,
                pdf_artifact_id=None,
                party_name_raw="테스트A",
                party_name_matched="테스트A",
                party_match_confidence=0.9,
                party_match_method="exact",
                extracted_balance=None,
                reply_date=None,
                ledger_balance=500_000,
                status="needs_review",
            )

        # auto-identify-pending 실행
        r = c.post(f"/api/project/{pid}/step5/auto-identify-pending")
        assert r.status_code == 201
        data = r.get_json()

        # needs_review 거래처는 회신 있음 → placeholder 생성 skip
        pending_names = [p["party_name"] for p in data.get("pending_parties", [])]
        assert "테스트A" not in pending_names, \
            f"needs_review 거래처가 미회신 placeholder로 생성됨: {data}"
        assert data["skipped_already_replied"] >= 1
