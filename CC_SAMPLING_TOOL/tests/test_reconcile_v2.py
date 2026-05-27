"""test_reconcile_v2 — declared 우선, per_account 비교, tolerance_pct 검증."""
from __future__ import annotations

import pytest
from src.domain.reconciliation import reconcile, reconcile_v2, ReconResult
from src.domain.currency import CurrencyResolver
from src.infrastructure.pdf.parser import ParsedReply, AccountRow
from src.infrastructure.loaders import UploadGuideData, PartyContact


def _make_parsed(
    balance=1_000_000.0,
    declared=None,
    per_rows=None,
    currency="KRW",
) -> ParsedReply:
    r = ParsedReply(
        extracted_party_name="테스트",
        period_end=None,
        reply_date=None,
        audit_firm=None,
        receivable_by_account={},
        payable_by_account={},
        receivable_total=balance,
        payable_total=None,
        is_match_declared=None,
        has_signature=False,
        extraction_confidence=0.9,
    )
    r.declared_match = declared
    r.per_account_rows = per_rows or []
    r.original_currency = currency
    return r


# ── 기존 reconcile() 하위 호환 ────────────────────────────────────────────────

def test_reconcile_legacy_matched():
    result = reconcile(1_000_000, 1_000_000)
    assert result.status == "matched"


def test_reconcile_legacy_mismatch():
    result = reconcile(1_000_000, 900_000)
    assert result.status == "mismatch"


def test_reconcile_legacy_extraction_failed():
    result = reconcile(1_000_000, None)
    assert result.status == "extraction_failed"


def test_reconcile_legacy_tolerance():
    result = reconcile(1_000_000, 999_000, tolerance=5_000)
    assert result.status == "matched"


# ── reconcile_v2: declared 우선 ───────────────────────────────────────────────

def test_v2_declared_true_matched():
    parsed = _make_parsed(declared=True)
    result = reconcile_v2(1_000_000, parsed)
    assert result.status == "matched"
    assert result.decision_basis == "declared"


def test_v2_declared_false_mismatch():
    parsed = _make_parsed(declared=False)
    result = reconcile_v2(1_000_000, parsed)
    assert result.status == "mismatch"
    assert result.decision_basis == "declared"


def test_v2_declared_true_but_large_diff_downgraded():
    """declared=일치 이지만 차이 5% 초과 → needs_review 강등."""
    parsed = _make_parsed(balance=500_000, declared=True)  # 50% 차이
    result = reconcile_v2(1_000_000, parsed)
    assert result.status == "needs_review"
    assert result.decision_basis == "declared"


def test_v2_declared_true_small_diff_stays_matched():
    """declared=일치, 차이 4% → needs_review 강등 없음."""
    parsed = _make_parsed(balance=960_000, declared=True)  # 4% 차이
    result = reconcile_v2(1_000_000, parsed)
    assert result.status == "matched"


# ── reconcile_v2: per_account 비교 ───────────────────────────────────────────

def _make_ug_row(party_name: str, acct: str, amt: float, cur: str = "KRW") -> PartyContact:
    return PartyContact(name=party_name, accounts=[(acct, cur, amt)])


def test_v2_per_account_matched():
    row = AccountRow(
        section="receivable",
        account_name="외상매출금",
        sent_amount=1_000_000,
        declared_match=None,
        reply_amount=1_000_000,
        currency="KRW",
    )
    parsed = _make_parsed(per_rows=[row])
    ug_row = _make_ug_row("테스트", "외상매출금", 1_000_000, "KRW")
    result = reconcile_v2(1_000_000, parsed, upload_guide_row=ug_row)
    assert result.status == "matched"
    assert result.decision_basis == "per_account"


def test_v2_per_account_mismatch():
    row = AccountRow(
        section="receivable",
        account_name="외상매출금",
        sent_amount=1_000_000,
        declared_match=None,
        reply_amount=900_000,
        currency="KRW",
    )
    parsed = _make_parsed(per_rows=[row])
    ug_row = _make_ug_row("테스트", "외상매출금", 1_000_000, "KRW")
    result = reconcile_v2(1_000_000, parsed, upload_guide_row=ug_row, tolerance=0)
    assert result.status == "mismatch"
    assert result.decision_basis == "per_account"
    assert len(result.per_account_findings) == 1


# ── reconcile_v2: 합계 비교 (total) ─────────────────────────────────────────

def test_v2_total_matched_krw():
    parsed = _make_parsed(balance=1_000_000, declared=None)
    result = reconcile_v2(1_000_000, parsed)
    assert result.status == "matched"
    assert result.decision_basis == "total"


def test_v2_total_mismatch_krw():
    parsed = _make_parsed(balance=800_000, declared=None)
    result = reconcile_v2(1_000_000, parsed, tolerance=0)
    assert result.status == "mismatch"


def test_v2_total_usd_with_resolver():
    """USD 100,000 + implicit rate 1300 → 130,000,000 KRW → matched."""
    from src.infrastructure.loaders import UploadGuideData, PartyContact
    contact = PartyContact(
        name="COSMAX USA",
        accounts=[("외상매출금", "USD", 100_000), ("외상매출금", "KRW", 130_000_000)]
    )
    ug = UploadGuideData(send_targets=[contact])
    resolver = CurrencyResolver(ug)

    parsed = _make_parsed(balance=100_000, declared=None, currency="USD")
    ug_row = contact
    result = reconcile_v2(130_000_000, parsed, upload_guide_row=ug_row,
                          currency_resolver=resolver, tolerance=10_000)
    assert result.status in ("matched", "needs_review")


# ── tolerance_pct ────────────────────────────────────────────────────────────

def test_v2_tolerance_pct_matched():
    """tolerance_pct=0.01 (1%) → 차이 0.5% → matched."""
    parsed = _make_parsed(balance=995_000)
    result = reconcile_v2(1_000_000, parsed, tolerance=0, tolerance_pct=0.01)
    assert result.status == "matched"


def test_v2_tolerance_pct_mismatch():
    """tolerance_pct=0.01 (1%) → 차이 2% → mismatch."""
    parsed = _make_parsed(balance=980_000)
    result = reconcile_v2(1_000_000, parsed, tolerance=0, tolerance_pct=0.01)
    assert result.status == "mismatch"


# ── extraction_failed ────────────────────────────────────────────────────────

def test_v2_extraction_failed_none_parsed():
    result = reconcile_v2(1_000_000, None)
    assert result.status == "extraction_failed"


def test_v2_extraction_failed_no_balance():
    parsed = _make_parsed(balance=None)
    result = reconcile_v2(1_000_000, parsed)
    assert result.status == "extraction_failed"


# ── notes 기록 ────────────────────────────────────────────────────────────────

def test_v2_notes_populated_on_declared():
    parsed = _make_parsed(declared=True, balance=960_000)
    result = reconcile_v2(1_000_000, parsed)
    assert isinstance(result.notes, list)
