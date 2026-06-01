"""AC별 RowParser 공통 토큰 추출. generic_parser._parse_line 일반화."""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# 일부 보험사는 원화를 'WON' 으로 표기한다. 통화 토큰으로 인식하되 KRW 로 정규화한다.
_CCY_SET = {"KRW", "WON", "USD", "EUR", "JPY", "CNY", "HKD", "GBP", "AUD", "SGD", "CNH"}
# 통화 표기 정규화 (WON → KRW). 인식되지 않으면 원문 유지.
_CCY_NORMALIZE = {"WON": "KRW"}
_DATE_8 = re.compile(r"^\d{8}$")
# 이자율은 회신서에서 소수 3~5자리로 표기(4.5000, 0.0000)되고 1000 미만이다.
# 소수 2자리(0.00, 18,720,900.00)는 금액이므로 rate 로 오인하면 안 된다.
_RATE = re.compile(r"^\d{1,3}\.\d{3,5}$")
_NUM = re.compile(r"^[\d,]+(?:\.\d+)?$")
_ACCT = re.compile(r"^[0-9\-]{8,22}$")
_PAREN = re.compile(r"^\([\d,.\-]+\)$")

_NOISE = [
    "조회기준일", "다음과 같", "참고 목적", "정확성", "해당 거래 없음",
    "해당사항 없음", "확인자", "당 은행", "당사", "면책", "유의사항",
]

# 합계/소계/총계 등 합산행 마커. substring 매칭하면 종합계약보증(="합계" 포함) 같은
# 실제 상품명을 오탐하므로, 줄의 FIRST 토큰이 정확히 이 집합에 속할 때만 noise 로 본다.
_TOTAL_TOKENS = {"합계", "소계", "총계", "합", "계", "총"}


def is_noise(line: str) -> bool:
    s = line.strip()
    if not s or len(s) < 4:
        return True
    if any(p in s for p in _NOISE):
        return True
    # 합산행은 anchored(선행 토큰) 매칭으로만 판정
    toks = s.split()
    if toks and toks[0] in _TOTAL_TOKENS:
        return True
    return False


def _ymd(s: str) -> date | None:
    if not s or s == "00000000" or len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except Exception:
        return None


_OCR_THOUSAND_TOK = re.compile(r"^\d[\d.,]*\d$")


def _ocr_thousand(tok: str) -> Decimal | None:
    """OCR 천단위 점·콤마 혼용 토큰(20.215.243.773 · 5.135.784,000)을 정수로 복원.

    _NUM(단일 구분자)이 못 잡는 다중 구분자 토큰만 대상. 첫 그룹 1~3자리 +
    이후 그룹이 전부 정확히 3자리일 때만 천단위 정수로 본다 — 날짜(24.11.07,
    마지막 2자리)·이자율(0.0000)·일반 소수(.00)는 복원하지 않는다."""
    if not _OCR_THOUSAND_TOK.match(tok):
        return None
    groups = re.split(r"[.,]", tok)
    if len(groups) < 2:
        return None
    first, rest = groups[0], groups[1:]
    if not (1 <= len(first) <= 3) or not first.isdigit():
        return None
    if not all(len(g) == 3 and g.isdigit() for g in rest):
        return None
    return _dec("".join(groups))


@dataclass
class RowTokens:
    account: str | None = None
    currency: str | None = None
    amounts: list[Decimal] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    rate: Decimal | None = None
    text_tokens: list[str] = field(default_factory=list)


def tokenize_row(row: str) -> RowTokens:
    t = RowTokens()
    for tok in row.split():
        if tok in _CCY_SET:
            t.currency = _CCY_NORMALIZE.get(tok, tok)
        elif _DATE_8.match(tok):
            d = _ymd(tok)
            if d:
                t.dates.append(d)
        elif _RATE.match(tok) and t.rate is None:
            t.rate = _dec(tok)
        elif _PAREN.match(tok):
            # 괄호 = 음수(평가손실·차감). 이전엔 폐기 → 부호·금액 손실. 복원해 음수로 보존.
            inner = tok[1:-1]
            v = _dec(inner)
            if v is None:
                v = _ocr_thousand(inner)
            if v is not None:
                t.amounts.append(-v)
        elif _ACCT.match(tok) and "," not in tok and t.account is None:
            t.account = tok
        elif _NUM.match(tok):
            v = _dec(tok)
            if v is not None:
                t.amounts.append(v)
        else:
            # _NUM 이 못 잡는 OCR 다중구분자 천단위 토큰(20.215.243.773) 복원 시도.
            v = _ocr_thousand(tok)
            if v is not None:
                t.amounts.append(v)
            else:
                t.text_tokens.append(tok)
    return t
