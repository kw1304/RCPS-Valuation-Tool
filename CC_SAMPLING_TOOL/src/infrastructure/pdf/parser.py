"""조회서 회신 텍스트 파싱 — 거래처명·금액·날짜·서명 추출.

지원 통화: KRW(원), USD($), JPY(￥/¥), CNY(RMB/元/¥)
날짜 포맷: YYYY-MM-DD, YYYY.MM.DD, YYYY년 M월 D일, M월 D일 (연도 생략 시 None)
금액 표기: 쉼표 구분, 괄호 음수 (1,234,567) → -1234567
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedReply:
    extracted_name: Optional[str]        # 추출된 거래처명
    extracted_balance: Optional[float]   # 추출된 잔액
    balance_currency: str                # "KRW" | "USD" | "JPY" | "CNY"
    reply_date: Optional[str]            # YYYY-MM-DD 정규화, 없으면 None
    has_signature: bool                  # 서명/도장 키워드 존재 여부
    confidence: float                    # 0.0 ~ 1.0


# ── 통화 패턴 ──────────────────────────────────────────────────
_CURRENCY_PATTERNS: list[tuple[str, str]] = [
    (r"\$\s*[\d,]+(?:\.\d+)?", "USD"),
    (r"USD\s*[\d,]+(?:\.\d+)?", "USD"),
    (r"￥\s*[\d,]+(?:\.\d+)?", "JPY"),
    (r"¥\s*[\d,]+(?:\.\d+)?", "JPY"),
    (r"JPY\s*[\d,]+(?:\.\d+)?", "JPY"),
    (r"RMB\s*[\d,]+(?:\.\d+)?", "CNY"),
    (r"CNY\s*[\d,]+(?:\.\d+)?", "CNY"),
    (r"元\s*[\d,]+(?:\.\d+)?", "CNY"),
]

# 채권·채무 공통 잔액 키워드
_BALANCE_KEYWORDS = [
    "잔액", "확인금액", "Balance", "balance",
    "외상매출금", "외상매입금", "미지급금", "미수금",
    "금액", "합계",
]
_BALANCE_KW_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(k) for k in _BALANCE_KEYWORDS) + r")"
    r"[\s:：]*"
    r"([\(（]?\s*[\d,]+(?:\.[0-9]{1,2})?\s*[\)）]?)",
    re.IGNORECASE,
)

# 날짜 패턴 (우선순위 순)
_DATE_PATTERNS = [
    # YYYY-MM-DD / YYYY.MM.DD
    (re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})"), "ymd"),
    # YYYY년 M월 D일
    (re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"), "ymd"),
    # M월 D일 (연도 없음 — 연도는 None)
    (re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일"), "md"),
]

_SIGNATURE_KEYWORDS = re.compile(r"확인|인\)|（인）|\(인\)|서명|sign|signature", re.IGNORECASE)

# 거래처명: "귀하" / "귀중" 바로 앞 단어 또는 상단부 첫 번째 회사명
_COMPANY_NAME_PATTERN = re.compile(
    r"([\w가-힣\(\)（）㈜\s\.&,-]{2,40}?)\s*(?:귀하|귀중|貴下|貴中)",
    re.IGNORECASE,
)
# (주), ㈜, 주식회사, Co., Ltd. 포함 회사명
_STANDALONE_COMPANY_PATTERN = re.compile(
    r"(?:주식회사\s*|㈜\s*|\(주\)\s*)?[\w가-힣]{2,20}(?:\s*(?:주식회사|㈜|\(주\)|Co\.|Ltd\.|Inc\.|Corp\.))?"
)


def _normalize_amount(raw: str) -> Optional[float]:
    """쉼표 제거, 괄호 음수 처리 → float."""
    raw = raw.strip()
    negative = raw.startswith("(") or raw.startswith("（")
    raw = re.sub(r"[（）()，,\s]", "", raw)
    raw = raw.replace(",", "").replace("，", "")
    try:
        val = float(raw)
        return -val if negative else val
    except ValueError:
        return None


def _extract_balance_and_currency(text: str) -> tuple[Optional[float], str]:
    """잔액과 통화를 추출한다.

    먼저 외화($, ￥ 등) 패턴 탐지, 없으면 키워드 인근 숫자를 KRW로 간주.
    """
    # 외화 우선
    for pattern, currency in _CURRENCY_PATTERNS:
        m = re.search(pattern, text)
        if m:
            # 앞 기호 제거 후 숫자만 추출
            num_raw = re.sub(r"[^\d,.]", "", m.group(0))
            val = _normalize_amount(num_raw)
            if val is not None:
                return val, currency

    # KRW: 키워드 인근 숫자
    for m in _BALANCE_KW_PATTERN.finditer(text):
        val = _normalize_amount(m.group(1))
        if val is not None:
            return val, "KRW"

    # 키워드 없이 큰 숫자 (5자리 이상) 탐색 — fallback
    nums = re.findall(r"[\(（]?\s*[\d,]{5,}\s*[\)）]?", text)
    for raw in nums:
        val = _normalize_amount(raw)
        if val is not None:
            return val, "KRW"

    return None, "KRW"


def _extract_date(text: str) -> Optional[str]:
    """날짜를 YYYY-MM-DD 형식으로 반환. 연도 없으면 None.

    회신 일자 우선 전략:
    - "현재", "기준", "기준일", "as of" 뒤에 오는 날짜는 기준일(보고일)로 판단 → skip
    - 텍스트 후반부(하단) 날짜를 우선: 마지막 날짜 패턴을 반환
    """
    # "현재"/"기준"/"as of" 등 기준일 키워드 바로 뒤 날짜를 제외하기 위해 제거
    _REFERENCE_DATE_KW = re.compile(
        r"(\d{4}[-./년]\s*\d{1,2}[-./월]\s*\d{1,2}일?)\s*(?:현재|기준|기준일|as of|이하|이전)",
        re.IGNORECASE,
    )
    cleaned = _REFERENCE_DATE_KW.sub("[REFDATE]", text)

    candidates: list[str] = []

    for pattern, kind in _DATE_PATTERNS:
        for m in pattern.finditer(cleaned):
            if kind == "ymd":
                y, mo, d = m.group(1), m.group(2), m.group(3)
                try:
                    candidates.append((m.start(), f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"))
                except ValueError:
                    continue
            elif kind == "md":
                candidates.append((m.start(), None))

    if not candidates:
        return None

    # 후반부(가장 뒤쪽) 날짜 우선 — 조회서 특성상 날인 날짜가 하단에 위치
    candidates.sort(key=lambda x: x[0], reverse=True)
    for _, date_str in candidates:
        if date_str is not None:
            return date_str

    return None


def _extract_name(text: str) -> Optional[str]:
    """거래처명 추출.

    우선순위:
    1. "귀하"/"귀중" 바로 앞 단어
    2. 텍스트 첫 30행 내 ㈜/주식회사 포함 줄
    """
    m = _COMPANY_NAME_PATTERN.search(text)
    if m:
        name = m.group(1).strip()
        if len(name) >= 2:
            return name

    # 상단부 탐색
    for line in text.splitlines()[:30]:
        line = line.strip()
        if any(kw in line for kw in ("㈜", "(주)", "주식회사", "Co.", "Ltd.", "Inc.", "Corp.")):
            # 너무 긴 줄은 제목일 가능성 → skip
            if 2 <= len(line) <= 60:
                return line

    return None


def parse_confirmation(text: str, kind: str = "receivable") -> ParsedReply:
    """추출된 텍스트에서 회신 핵심 정보를 파싱한다.

    Args:
        text: ExtractResult.full_text
        kind: "receivable" | "payable" (현재는 동일 로직, 향후 키워드 분기 가능)
    """
    name = _extract_name(text)
    balance, currency = _extract_balance_and_currency(text)
    date_str = _extract_date(text)
    has_sig = bool(_SIGNATURE_KEYWORDS.search(text))

    # 신뢰도 — 추출된 항목 수 기반
    extracted_count = sum([
        name is not None,
        balance is not None,
        date_str is not None,
        has_sig,
    ])
    confidence = extracted_count / 4.0

    return ParsedReply(
        extracted_name=name,
        extracted_balance=balance,
        balance_currency=currency,
        reply_date=date_str,
        has_signature=has_sig,
        confidence=confidence,
    )
