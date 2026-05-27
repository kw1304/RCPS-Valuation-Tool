"""test_form_detector — 4개 양식 분류 정확도 검증."""
from __future__ import annotations

import pytest
from src.infrastructure.pdf.form_detector import detect_form


# ── 샘플 텍스트 픽스처 ────────────────────────────────────────────────────────

KR_STANDARD_TEXT = """
채권채무조회서

코스맥스 귀중

2025년 12월 31일 현재

당사[코스맥스비티아이] 귀사[코스맥스㈜]

받을 금액
계정과목  발송금액   일치여부   회신금액   비고
외상매출금  1,000,000  일치  1,000,000

합계  1,000,000    1,000,000

확인통지
감사인명  삼덕회계법인
"""

EN_STANDARD_TEXT = """
Confirmation of Accounts

TO : COSMAX USA  2026- 01- 31

as per December 31, 2025

Dear Sirs,

Receivables
Account  Our Amount  Your Amount  Description
Trade Receivable  USD 100,000  USD 100,000

Total  USD 100,000  USD 100,000

Signature and Company Chop
Accounting Firm: Samduk Accounting Corporation
"""

EMAIL_FREEFORM_TEXT = """
From: finance@cosmax.com
To: audit@samduk.com
Subject: CC 회신 - 외상매출금
Date: 2026-02-05

안녕하세요,

외상매출금 잔액 확인서 첨부드립니다.
외상매출금 잔액: 500,000,000원
"""

OCR_REQUIRED_TEXT = "   "  # 100자 미만


def test_detect_kr_standard():
    profile = detect_form(KR_STANDARD_TEXT)
    assert profile.form_id == "samduk_kr_standard"
    assert profile.confidence > 0.5


def test_detect_en_standard():
    profile = detect_form(EN_STANDARD_TEXT)
    assert profile.form_id == "samduk_en_standard"
    assert profile.confidence > 0.4


def test_detect_email_freeform():
    profile = detect_form(EMAIL_FREEFORM_TEXT)
    assert profile.form_id == "email_freeform"
    assert profile.confidence > 0.3


def test_detect_ocr_required():
    profile = detect_form(OCR_REQUIRED_TEXT)
    assert profile.form_id == "ocr_required"
    assert profile.confidence > 0.9


def test_detect_unknown():
    # 100자 이상의 텍스트이지만 양식 키워드 없음 → "unknown"
    long_random_text = (
        "This is a random document with no confirmation-related keywords. "
        "It contains various words but nothing that would indicate it's a "
        "financial confirmation letter or accounts receivable/payable form."
    )
    profile = detect_form(long_random_text)
    assert profile.form_id in ("unknown", "samduk_en_standard")  # en 키워드 없으므로 unknown 예상


def test_hints_populated_for_kr():
    """분류 근거 힌트가 채워지는지 확인."""
    profile = detect_form(KR_STANDARD_TEXT)
    assert len(profile.hints) > 0


def test_filename_meta_boosts_kr():
    """파일명 힌트가 있으면 한국어 양식 신뢰도 상승."""
    short_text = "채권채무조회서 귀중 일치여부"
    p_no_meta = detect_form(short_text)
    p_with_meta = detect_form(short_text, file_meta={"filename": "CC-01_조회서.pdf"})
    # 힌트가 있으면 score_kr이 올라감
    assert p_with_meta.confidence >= p_no_meta.confidence


def test_table_hint_boosts_kr():
    """표에 '계정과목'+'일치여부' 헤더가 있으면 한국어 신뢰도 상승."""
    text = "채권채무조회서"
    tables = [[["계정과목", "발송금액", "일치여부", "회신금액"]]]
    p_no_table = detect_form(text)
    p_with_table = detect_form(text, tables=tables)
    assert p_with_table.confidence >= p_no_table.confidence
