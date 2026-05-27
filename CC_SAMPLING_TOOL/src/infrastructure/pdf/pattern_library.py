"""조회서 양식별 파싱 패턴 레지스트리.

FormPatterns 는 form_id 별 정규식·키워드 모음이다.
parser_v2.parse_confirmation_v2() 가 이 패턴을 참조해 동적 컬럼 매핑을 수행한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FormPatterns:
    """단일 양식 폼에 대한 파싱 패턴 집합."""

    form_id: str

    # ── 거래처명 ──────────────────────────────────────────────────────────
    party_name_patterns: list[str] = field(default_factory=list)
    # 각 항목은 정규식 문자열; group(1) 이 거래처명

    # ── 표 헤더 키워드 ────────────────────────────────────────────────────
    table_header_keywords: list[str] = field(default_factory=list)
    # 이 중 하나라도 포함된 행이 있으면 계정과목 표로 인식

    # ── 일치여부 컬럼 키워드 ─────────────────────────────────────────────
    match_column_keywords: list[str] = field(default_factory=list)
    # 헤더에서 이 키워드를 가진 컬럼 → declared_match 추출

    # ── 회신금액 컬럼 키워드 ─────────────────────────────────────────────
    reply_amount_column_keywords: list[str] = field(default_factory=list)
    # 헤더에서 이 키워드를 가진 컬럼 → reply_amount 추출

    # ── 발송금액 컬럼 키워드 ─────────────────────────────────────────────
    sent_amount_column_keywords: list[str] = field(default_factory=list)

    # ── 회신 날짜 패턴 ───────────────────────────────────────────────────
    reply_date_patterns: list[str] = field(default_factory=list)

    # ── 감사인명 패턴 ────────────────────────────────────────────────────
    audit_firm_patterns: list[str] = field(default_factory=list)

    # ── 섹션 구분 키워드 ─────────────────────────────────────────────────
    receivable_section_keywords: list[str] = field(default_factory=list)
    payable_section_keywords: list[str] = field(default_factory=list)

    # ── 일치/불일치 셀값 판정 ─────────────────────────────────────────────
    match_positive_values: list[str] = field(default_factory=list)   # "일치" 판정 텍스트
    match_negative_values: list[str] = field(default_factory=list)   # "불일치" 판정 텍스트


# ── 삼덕 한국어 표준 ────────────────────────────────────────────────────────────
_SAMDUK_KR = FormPatterns(
    form_id="samduk_kr_standard",
    party_name_patterns=[
        r"귀사\[([^\]]+)\]",                                     # 귀사[거래처명]
        r"^(.+?)\s+(?:귀중|귀하|貴下|貴中)",                    # {이름} 귀중
        r"회사\s*또는\s*기관명\s*[:：]\s*(.+?)$",               # 회사 또는 기관명:
    ],
    table_header_keywords=["계정과목", "발송금액", "일치여부", "회신금액", "비고"],
    match_column_keywords=["일치여부", "확인"],
    reply_amount_column_keywords=["회신금액", "회신 금액"],
    sent_amount_column_keywords=["발송금액", "발송 금액"],
    reply_date_patterns=[
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
        r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})",
    ],
    audit_firm_patterns=[
        r"감사인명\s+(.+?)(?:\s*\n|\s*$)",
        r"회계법인\s*[:：]\s*(.+?)(?:\s*\n|\s*$)",
    ],
    receivable_section_keywords=[r"받을\s*금액", "채권"],
    payable_section_keywords=[r"지급할\s*금액", "채무"],
    match_positive_values=["일치", "○", "O", "✓"],
    match_negative_values=["불일치", "×", "X", "✗"],
)

# ── 삼덕 영문 표준 ──────────────────────────────────────────────────────────────
_SAMDUK_EN = FormPatterns(
    form_id="samduk_en_standard",
    party_name_patterns=[
        r"^TO\s*:\s*(.+?)\s+\d{4}",
        r"^TO\s*:\s*(.+?)$",
        r"Dear\s+(.+?)(?:\s*,|\s*:)",
    ],
    table_header_keywords=["Account", "Our Amount", "Your Amount", "Description",
                           "Receivable", "Payable"],
    match_column_keywords=["Match", "Status", "Agree", "Confirm"],
    reply_amount_column_keywords=["Your Amount", "Confirmed Amount", "Reply Amount"],
    sent_amount_column_keywords=["Our Amount", "Sent Amount", "Book Amount"],
    reply_date_patterns=[
        r"(\d{4})-\s*(\d{1,2})-\s*(\d{1,2})",    # 2026- 02- 04
        r"(\d{1,2})[./](\d{1,2})[./](\d{4})",     # MM.DD.YYYY
    ],
    audit_firm_patterns=[
        r"Accounting\s+Firm\s*:\s*(.+?)(?:\s*\n|\s*$)",
        r"Auditor\s*:\s*(.+?)(?:\s*\n|\s*$)",
    ],
    receivable_section_keywords=["Receivable", "Trade Receivable", "Amount Receivable"],
    payable_section_keywords=["Payable", "Trade Payable", "Amount Payable"],
    match_positive_values=["agree", "match", "confirmed", "yes", "✓"],
    match_negative_values=["disagree", "mismatch", "discrepancy", "no", "×"],
)

# ── 이메일 자유 양식 ────────────────────────────────────────────────────────────
_EMAIL_FREEFORM = FormPatterns(
    form_id="email_freeform",
    party_name_patterns=[
        r"^From\s*:\s*(.+?)(?:\s*<|\s*\n)",
        r"^From\s*:\s*(.+?)$",
    ],
    table_header_keywords=["계정과목", "Account", "금액", "Amount"],
    match_column_keywords=["일치여부", "Match", "Status"],
    reply_amount_column_keywords=["회신금액", "Your Amount", "Amount"],
    sent_amount_column_keywords=["발송금액", "Our Amount"],
    reply_date_patterns=[
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일",
        r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})",
    ],
    audit_firm_patterns=[],
    receivable_section_keywords=[r"받을\s*금액", "Receivable"],
    payable_section_keywords=[r"지급할\s*금액", "Payable"],
    match_positive_values=["일치", "agree", "match"],
    match_negative_values=["불일치", "disagree", "mismatch"],
)

# ── 레지스트리 ─────────────────────────────────────────────────────────────────
PATTERN_REGISTRY: dict[str, FormPatterns] = {
    "samduk_kr_standard": _SAMDUK_KR,
    "samduk_en_standard": _SAMDUK_EN,
    "email_freeform":     _EMAIL_FREEFORM,
    # "ocr_required"와 "unknown"은 패턴 없음 — 기존 parse_confirmation() fallback 사용
}


def get_patterns(form_id: str) -> Optional[FormPatterns]:
    """form_id에 해당하는 FormPatterns 반환. 없으면 None."""
    return PATTERN_REGISTRY.get(form_id)
