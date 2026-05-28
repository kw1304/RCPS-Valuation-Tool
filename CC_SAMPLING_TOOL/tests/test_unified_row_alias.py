"""샘플링 거래처 내역 — alias/normalize 기반 한 행 통합 테스트.

_merge_decisions 가 채권·채무 양쪽에 동일 거래처가
다른 표기로 존재할 때 한 _UnifiedPartyRow 로 통합하는지 검증.

예: 채권 "COSMAX INC" + 채무 "COSMAX. INC" → 한 행 통합
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass, field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.infrastructure.report.generic_reporter import (
    _merge_decisions,
    _UnifiedPartyRow,
    ConfirmationReplyInfo,
    PartyContactInfo,
)
from src.domain.population import PartyDecision


# ── 테스트용 KindData 헬퍼 ─────────────────────────────────────────────────

def _make_decision(name: str, balance: float, final_sampled: bool = True) -> PartyDecision:
    return PartyDecision(
        name=name,
        balance=balance,
        by_account={},
        is_key_item=False,
        is_representative=False,
        is_related_party=False,
        is_excluded=False,
        final_sampled=final_sampled,
    )


class _FakeKindData:
    """_merge_decisions 시그니처에 맞는 경량 KindData."""
    def __init__(self, decisions):
        self.decisions = decisions


# ── 테스트 ─────────────────────────────────────────────────────────────────

def test_exact_same_name_merges_to_one_row():
    """완전히 같은 이름 — 채권·채무 각 1건 → 통합 1행."""
    ar = _FakeKindData([_make_decision("삼성전자", 100_000)])
    ap = _FakeKindData([_make_decision("삼성전자", 80_000)])

    rows = _merge_decisions(ar, ap, contacts=[], replies=[])
    samsung = [r for r in rows if r.name == "삼성전자"]
    assert len(samsung) == 1, "같은 이름인데 2행으로 분리됨"
    assert samsung[0].ar_total == 100_000
    assert samsung[0].ap_total == 80_000


def test_normalize_variant_merges_to_one_row():
    """법인 접미사 차이 — 'COSMAX INC' vs 'COSMAX. INC' → 한 행 통합."""
    ar = _FakeKindData([_make_decision("COSMAX INC", 500_000)])
    ap = _FakeKindData([_make_decision("COSMAX. INC", 300_000)])

    rows = _merge_decisions(ar, ap, contacts=[], replies=[])
    cosmax_rows = [r for r in rows if "cosmax" in r.name.lower()]
    assert len(cosmax_rows) == 1, (
        f"COSMAX INC / COSMAX. INC 가 {len(cosmax_rows)}행으로 분리됨"
    )
    row = cosmax_rows[0]
    assert row.ar_total == 500_000
    assert row.ap_total == 300_000


def test_korean_corp_suffix_variant_merges():
    """'(주)알파' vs '알파주식회사' normalize 동일 → 한 행 통합."""
    ar = _FakeKindData([_make_decision("(주)알파", 200_000)])
    ap = _FakeKindData([_make_decision("알파주식회사", 150_000)])

    rows = _merge_decisions(ar, ap, contacts=[], replies=[])
    alpha_rows = [r for r in rows if "알파" in r.name]
    assert len(alpha_rows) == 1, (
        f"(주)알파 / 알파주식회사 가 {len(alpha_rows)}행으로 분리됨"
    )


def test_different_parties_stay_separate():
    """완전히 다른 거래처 — 채권 '삼성전자', 채무 'LG전자' → 각각 별행."""
    ar = _FakeKindData([_make_decision("삼성전자", 100_000)])
    ap = _FakeKindData([_make_decision("LG전자", 80_000)])

    rows = _merge_decisions(ar, ap, contacts=[], replies=[])
    names = {r.name for r in rows}
    assert "삼성전자" in names
    assert "LG전자" in names
    assert len(names) == 2


def test_reply_status_carried_to_unified_row():
    """통합 행에 회신 상태 올바르게 반영."""
    ar = _FakeKindData([_make_decision("COSMAX INC", 500_000)])
    ap = _FakeKindData([_make_decision("COSMAX. INC", 300_000)])

    replies = [
        ConfirmationReplyInfo(
            party_name="COSMAX INC",
            status="matched",
            extracted_balance=500_000,
            reply_date=None,
        )
    ]

    rows = _merge_decisions(ar, ap, contacts=[], replies=replies)
    cosmax_rows = [r for r in rows if "cosmax" in r.name.lower()]
    assert len(cosmax_rows) == 1
    assert cosmax_rows[0].reply_status == "matched", (
        f"회신 상태 미반영: {cosmax_rows[0].reply_status}"
    )


def test_ar_only_no_ap_stays_separate():
    """채권만 있는 거래처 — ap=None일 때 정상 동작."""
    ar = _FakeKindData([
        _make_decision("채권전용거래처", 100_000),
        _make_decision("공통거래처", 200_000),
    ])

    rows = _merge_decisions(ar, None, contacts=[], replies=[])
    assert len(rows) == 2
    names = {r.name for r in rows}
    assert "채권전용거래처" in names
    assert "공통거래처" in names
