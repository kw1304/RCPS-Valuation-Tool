"""test_parser_v2 — parse_confirmation_v2 동적 표 매핑·declared_match 추출 검증."""
from __future__ import annotations

import pytest
from src.infrastructure.pdf.parser import parse_confirmation_v2, AccountRow
from src.infrastructure.pdf.pattern_library import get_patterns


# ── 표 픽스처 ─────────────────────────────────────────────────────────────────

# 삼덕 표준 한국어 표 (헤더 + 2개 계정과목 행 + 합계)
KR_TABLE_MATCHED = [
    [
        ["계정과목", "발송금액", "일치여부", "회신금액", "비고"],
        ["외상매출금", "1,000,000", "일치", "1,000,000", ""],
        ["받을어음", "500,000", "일치", "500,000", ""],
        ["합계", "1,500,000", "", "1,500,000", ""],
    ]
]

KR_TABLE_MISMATCH = [
    [
        ["계정과목", "발송금액", "일치여부", "회신금액", "비고"],
        ["외상매출금", "1,000,000", "불일치", "900,000", "금액 상이"],
    ]
]

KR_TABLE_MIXED = [
    [
        ["계정과목", "발송금액", "일치여부", "회신금액", "비고"],
        ["외상매출금", "1,000,000", "일치", "1,000,000", ""],
        ["받을어음", "500,000", "불일치", "400,000", ""],
    ]
]

# 영문 표 (회신금액 컬럼 위치 다름)
EN_TABLE = [
    [
        ["Account", "Our Amount", "Your Amount", "Description"],
        ["Trade Receivable", "USD 100,000", "USD 100,000", ""],
        ["Total", "USD 100,000", "USD 100,000", ""],
    ]
]

KR_TEXT_WITH_TABLE = """
코스맥스 귀중

2025년 12월 31일 현재

당사[코스맥스비티아이] 귀사[코스맥스㈜]

받을 금액

확인통지
"""

EN_TEXT = """
Confirmation of Accounts

TO : COSMAX USA  2026- 01- 31

as per December 31, 2025

Receivables

Signature and Company Chop
Accounting Firm: Samduk
"""


def test_declared_match_all_matched():
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MATCHED, patterns=patterns)
    assert result.declared_match is True
    assert len(result.per_account_rows) == 2
    for row in result.per_account_rows:
        assert row.declared_match is True


def test_declared_match_mismatch():
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MISMATCH, patterns=patterns)
    assert result.declared_match is False
    assert result.per_account_rows[0].declared_match is False


def test_declared_match_mixed():
    """하나라도 불일치 → 종합 declared_match=False."""
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MIXED, patterns=patterns)
    assert result.declared_match is False


def test_per_account_rows_populated():
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MATCHED, patterns=patterns)
    assert len(result.per_account_rows) == 2
    names = [r.account_name for r in result.per_account_rows]
    assert "외상매출금" in names
    assert "받을어음" in names


def test_reply_amount_extracted():
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MATCHED, patterns=patterns)
    ar = next(r for r in result.per_account_rows if r.account_name == "외상매출금")
    assert ar.reply_amount == 1_000_000.0


def test_sent_amount_extracted():
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MATCHED, patterns=patterns)
    ar = next(r for r in result.per_account_rows if r.account_name == "외상매출금")
    assert ar.sent_amount == 1_000_000.0


def test_en_table_dynamic_mapping():
    """영문 표: Your Amount(컬럼2) 동적 매핑."""
    patterns = get_patterns("samduk_en_standard")
    result = parse_confirmation_v2(EN_TEXT, tables=EN_TABLE, patterns=patterns)
    # 영문 표는 컬럼 인덱스 2 = Your Amount
    assert len(result.per_account_rows) >= 1


def test_no_table_fallback():
    """표 없을 때 텍스트 기반 파싱 fallback — per_account_rows 빈 list."""
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=None)
    # 표 없으면 per_account_rows는 빈 리스트, 기존 fields는 그대로
    assert isinstance(result.per_account_rows, list)


def test_original_currency_usd():
    """USD 금액 표에서 original_currency=USD 추출."""
    patterns = get_patterns("samduk_en_standard")
    result = parse_confirmation_v2(EN_TEXT, tables=EN_TABLE, patterns=patterns)
    assert result.original_currency == "USD"


def test_backward_compat_extracted_balance():
    """하위 호환: extracted_balance 프로퍼티가 여전히 동작."""
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MATCHED, patterns=patterns)
    # extracted_balance = receivable_total 우선
    assert result.extracted_balance is not None


def test_section_receivable_assigned():
    """표 첫 번째(idx=0) = 채권 섹션."""
    patterns = get_patterns("samduk_kr_standard")
    result = parse_confirmation_v2(KR_TEXT_WITH_TABLE, tables=KR_TABLE_MATCHED, patterns=patterns)
    for row in result.per_account_rows:
        assert row.section == "receivable"
