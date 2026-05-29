import re
from datetime import date
from decimal import Decimal
from src.domain.ac_models import (
    FinancialAsset,
    SecurityDetail,
)

AMOUNT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*원?")
ACCT_RE = re.compile(r"계좌(?:번호)?\s*([0-9\-]+)")
CCY_RE = re.compile(r"\b(KRW|USD|EUR|JPY|CNY|HKD|GBP|AUD|SGD)\b")
RATE_RE = re.compile(r"([\d.]+)\s*%")
DATE_RE = re.compile(r"(\d{4})[-./]?\s*(\d{1,2})[-./]?\s*(\d{1,2})")

# 회신서 보일러플레이트 — record 만들면 안 되는 안내 문구
_NOISE_PATTERNS = [
    "조회기준일",          # "4. 조회기준일 현재 조회대상회사..."
    "당사의",
    "다음과 같습니다",
    "다음과같음",
    "참고 목적으로",
    "정확성",
    "표시되어",
    "이는 참고",
    "조회대상회사",
    "당 금융회사",
    "당 은행",
    "해당 거래 없음",
    "해당사항 없음",
    "(주)",                # 보통 헤더 텍스트 "코스맥스비티아이(주)" 등
    "유의사항",
    "면책",
    "비고",
    "기재 사항",
    "기재사항",
]


def _is_noise(line: str) -> bool:
    """회신서 안내·면책·헤더 문구 skip 판정. 짧은 문구·번호로 시작하는 절 제외."""
    s = line.strip()
    if not s or len(s) < 6:
        return True
    if len(s) > 200:    # 너무 긴 줄 — 한 record 아닌 paragraph
        return True
    # 번호 절 ("1.", "1)", "①", "가.", "(1)", "4. 조회기준일") → noise
    if re.match(r"^\s*[\d①②③④⑤⑥⑦⑧⑨⑩가-힣]\s*[.)]\s", s):
        # 단 숫자 다음 금융상품 키워드는 record (e.g. "1. 보통예금")
        pass
    # 보일러플레이트 키워드 포함
    for p in _NOISE_PATTERNS:
        if p in s:
            return True
    return False


def _amount(text: str, anchor: str) -> Decimal | None:
    """Extract amount following anchor keyword."""
    m = re.search(rf"{anchor}\s*[:：]?\s*([\d,]+)", text)
    if not m:
        return None
    return Decimal(m.group(1).replace(",", ""))


def _date(text: str, anchor: str) -> date | None:
    """Extract date following anchor keyword."""
    m = re.search(
        rf"{anchor}\s*[:：]?\s*(\d{{4}}[-./]\d{{1,2}}[-./]\d{{1,2}})", text
    )
    if not m:
        return None
    parts = re.split(r"[-./]", m.group(1))
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


_AC1_KEYWORDS = [
    "보통예금", "정기예금", "당좌예금", "외화예금", "기업자유", "MMDA",
    "MMF", "CMA", "RP", "수익증권", "ETF",
    "주식", "채권", "신탁",
    "퇴직연금", "발행어음", "랩", "위탁자상품", "펀드상품", "종합투자",
]
_CCY_SET = {"KRW","USD","EUR","JPY","CNY","HKD","GBP","AUD","SGD","CNH"}
_DATE_8 = re.compile(r"^\d{8}$")
_RATE_PATTERN = re.compile(r"^\d+\.\d{2,5}$")
_NUM_TOKEN = re.compile(r"^[\d,]+(?:\.\d+)?$")
_ACCT_TOKEN = re.compile(r"^[0-9\-]{8,22}$")
_PAREN = re.compile(r"^\([\d,.\-]+\)$")


def _classify(s: str) -> tuple[str, str]:
    """(asset_type, category)."""
    if any(k in s for k in ["주식", "ETF"]):
        return "stock", "securities"
    if "채권" in s:
        return "bond", "securities"
    if any(k in s for k in ["수익증권", "신탁", "랩", "펀드", "위탁자상품", "종합투자", "발행어음", "MMF", "RP"]):
        return "fund", "securities"
    if any(k in s for k in ["예금", "CMA", "MMDA", "기업자유", "퇴직연금"]):
        return "deposit", "bank"
    return "other", "bank"


def _to_dec(v: str | None) -> Decimal | None:
    if v is None or v in {"-", "", "0"}:
        return Decimal("0") if v == "0" else None
    try:
        return Decimal(v.replace(",", ""))
    except Exception:
        return None


def parse_ac1_security_details(text: str, bc_no: str, bank: str) -> list[SecurityDetail]:
    """유가증권 상세명세 추출. PDF의 '상세명세' 헤더 다음 lines 파싱.

    표준 패턴: '계좌(11~16) 종목명(한글) 수량 액면 [기준가] 평가액 [만기] [담보수량 담보종류]'
    예: '25628241101 코스맥스 190,000 163,000.00 30,970,000,000 0'
        '25628241101 코스맥스엔비티 2,500,000 3,500.00 8,750,000,000 0 2,500,000 질권설정'
    """
    out: list[SecurityDetail] = []
    # 새 파이프라인의 SectionSplitter가 '상세명세…다음' 헤더 line을 제거한 뒤
    # 단일 섹션 블록만 넘기므로, 헤더 트리거에 의존하지 않고
    # 첫 token이 계좌번호인 모든 row를 파싱한다. (헤더 line은 계좌번호가 없어 자연히 skip)
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # 헤더 line (계좌번호 종목명 수량 ...) skip
        if "종목명" in s or ("수량" in s and "액면" in s):
            continue
        tokens = s.split()
        if len(tokens) < 4:
            continue
        # 첫 token이 계좌(긴 숫자)인지
        acct = tokens[0]
        if not re.match(r"^[0-9\-]{8,18}$", acct):
            continue
        # 종목명: 한글 (2~3 token일 수 있음 — 끝 까지 숫자 아닌 부분 흡수)
        # 끝쪽 숫자/금액 tokens 추출
        i = 1
        ticker_parts = []
        while i < len(tokens) and not _NUM_TOKEN.match(tokens[i]):
            ticker_parts.append(tokens[i])
            i += 1
        ticker = " ".join(ticker_parts) or "?"
        nums = []
        last_text = []
        for t in tokens[i:]:
            if _NUM_TOKEN.match(t) or t in {"0","-"}:
                nums.append(_to_dec(t))
            else:
                last_text.append(t)
        # heuristic: 평가액 = 가장 큰 숫자, 수량 = 가장 첫 숫자, 액면·기준가 = 단가 (천~십만)
        qty = nums[0] if nums else None
        # largest 추정 평가액
        non_null = [n for n in nums if n and n > 0]
        val = max(non_null) if non_null else None
        # 단가 후보 (1,000 ~ 10,000,000) — 기준가/액면
        unit_prices = [n for n in nums[1:] if n and 100 <= n <= 10_000_000]
        base = unit_prices[0] if unit_prices else None
        face = None  # 회신서 보통 액면금액 빠짐
        # collateral: 마지막 숫자 (담보수량) + 텍스트
        coll_qty = None
        coll_type = None
        if last_text:
            coll_type = " ".join(last_text)[:30]
            # text 앞에 숫자 있으면 담보수량
            for n in reversed(nums):
                if n and n != val and n != qty and n != base:
                    coll_qty = n; break
        out.append(SecurityDetail(
            bc_no=bc_no, bank=bank,
            account_no=acct, ticker_name=ticker,
            quantity=qty, face_value=face,
            base_price=base, valuation=val,
            collateral_qty=coll_qty, collateral_type=coll_type,
        ))
    return out


def parse_ac1_deposit(text: str, bc_no: str, bank: str) -> list[FinancialAsset]:
    """AC1 token-based parser. 은행 예금 + 증권사 자산 모두 처리.

    Strategy:
      1. tokenize by whitespace
      2. acct: 10~18 digit (no comma)
      3. ccy: KRW/USD/...
      4. dates: 8-digit at end (last 1~2)
      5. rate: 0.NNNN
      6. balance: largest numeric token (with comma)
      7. parens: 누적이자 etc — skip
      8. rest = product
    """
    out: list[FinancialAsset] = []
    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s):
            continue
        # 예금 행 판정: 상품명 키워드가 매칭되거나(빠른 경로), 키워드가
        # 줄바꿈으로 쪼개져(ONE KB ...-보통 / 예금) 못 잡힌 경우에도
        # '계좌번호 토큰(10~18자리 무콤마)'이 있으면 진짜 데이터 행으로 본다.
        # 헤더("금융상품의 종류 ...")·footer·괄호 누적이자 줄은 계좌번호가
        # 없어 자연히 제외된다(당좌개설보증금·ONE KB 행 복구).
        if not (any(kw in s for kw in _AC1_KEYWORDS) or _has_acct_token(s)):
            continue
        rec = _parse_line(s, bc_no, bank)
        if rec:
            out.append(rec)
    return out


def _has_acct_token(s: str) -> bool:
    """줄에 계좌번호 형태(콤마 없는 10~18자리 숫자) 토큰이 있는지."""
    for t in s.split():
        if "," not in t and re.fullmatch(r"\d{10,18}", t):
            return True
    return False


def _parse_line(s: str, bc_no: str, bank: str) -> FinancialAsset | None:
    tokens = s.split()
    if len(tokens) < 2:
        return None
    atype, cat = _classify(s)

    # extract dates from right (up to 2 trailing 8-digit numbers)
    dates: list[date | None] = []
    while tokens and _DATE_8.match(tokens[-1]):
        dates.insert(0, _parse_yyyymmdd(tokens.pop()))
        if len(dates) >= 2:
            break
    maturity = dates[-1] if len(dates) >= 1 else None
    last_interest = dates[-2] if len(dates) >= 2 else None
    if len(dates) == 1:
        last_interest, maturity = dates[0], None

    # extract rate
    rate = None
    if tokens and _RATE_PATTERN.match(tokens[-1]):
        rate = Decimal(tokens.pop())

    # remove "()" or "(0.00)" interest token
    while tokens and (_PAREN.match(tokens[-1]) or tokens[-1] in {"()","(0.00)"}):
        tokens.pop()

    # extract ccy + numeric tokens from remaining
    ccy = None
    numeric_tokens = []
    other_tokens = []
    acct = None
    for t in tokens:
        if t in _CCY_SET:
            ccy = t
        elif _ACCT_TOKEN.match(t) and "," not in t and acct is None:
            acct = t
        elif _NUM_TOKEN.match(t) or t == "-":
            numeric_tokens.append(t)
        else:
            other_tokens.append(t)

    if not ccy:
        ccy = "USD" if "외화" in s else "KRW"

    # balance: largest numeric (assume the first non-zero, or just first)
    balance = Decimal("0")
    deposit_money = margin = receivable = None
    if cat == "bank":
        if numeric_tokens:
            balance = _to_dec(numeric_tokens[0]) or Decimal("0")
    else:
        # securities: balance, deposit, margin, receivable (in order)
        nums = [_to_dec(t) for t in numeric_tokens]
        if len(nums) >= 1: balance = nums[0] or Decimal("0")
        if len(nums) >= 2: deposit_money = nums[1]
        if len(nums) >= 3: margin = nums[2]
        if len(nums) >= 4: receivable = nums[3]

    product = " ".join(other_tokens).strip()[:60] or s.split()[0][:60]
    restriction = None
    if cat == "securities":
        # last non-numeric tokens after numbers may be "담보제공·처분제한 / 해당사항없음"
        restriction_tokens = [t for t in other_tokens if any(k in t for k in ["담보","처분","상세","해당"])]
        if restriction_tokens:
            restriction = " ".join(restriction_tokens)[:40]

    return FinancialAsset(
        bc_no=bc_no, bank=bank, asset_type=atype, category=cat,
        product=product, account_no=acct, currency=ccy,
        balance=balance, interest_rate=rate,
        last_interest_date=last_interest, maturity=maturity,
        deposit_money=deposit_money, margin_deposit=margin, receivable=receivable,
        collateral_restriction=restriction,
    )


def _parse_yyyymmdd(s: str) -> date | None:
    """8자리 YYYYMMDD → date. 00000000 또는 invalid → None."""
    if not s or s == "00000000" or len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None
