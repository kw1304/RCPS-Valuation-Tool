import re
from datetime import date
from decimal import Decimal
from src.domain.ac_models import (
    FinancialAsset,
    Borrowing,
    Derivative,
    Guarantee,
    Collateral,
    BillCheck,
    Insurance,
    GeneralDeal,
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


def parse_ac1_deposit(text: str, bc_no: str, bank: str) -> list[FinancialAsset]:
    """Parse AC1 (Financial Assets) from PDF section text."""
    out: list[FinancialAsset] = []
    keywords = [
        "보통예금",
        "정기예금",
        "당좌예금",
        "외화예금",
        "MMDA",
        "MMF",
        "CMA",
        "RP",
        "주식",
        "채권",
        "수익증권",
        "ETF",
        "신탁",
    ]

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(kw in s for kw in keywords):
            continue

        balance = _amount(s, "잔액") or _amount(s, "금액") or Decimal("0")
        acct = (ACCT_RE.search(s).group(1) if ACCT_RE.search(s) else None)
        ccy = (CCY_RE.search(s).group(1) if CCY_RE.search(s) else "KRW")
        rate_m = RATE_RE.search(s)
        rate = Decimal(rate_m.group(1)) if rate_m else None

        if any(k in s for k in ["주식", "ETF"]):
            atype = "stock"
        elif any(k in s for k in ["채권"]):
            atype = "bond"
        elif any(k in s for k in ["MMF", "RP", "수익증권", "신탁"]):
            atype = "fund"
        elif any(k in s for k in ["예금", "CMA", "MMDA"]):
            atype = "deposit"
        else:
            atype = "other"

        out.append(
            FinancialAsset(
                bc_no=bc_no,
                bank=bank,
                asset_type=atype,
                product=s[:60],
                account_no=acct,
                currency=ccy,
                balance=balance,
                interest_rate=rate,
            )
        )

    return out


def parse_ac2_borrowing(text: str, bc_no: str, bank: str) -> list[Borrowing]:
    """Parse AC2 (Borrowings) from PDF section text."""
    out: list[Borrowing] = []
    keywords = ["대출", "차입", "사채", "약정"]

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(kw in s for kw in keywords):
            continue

        limit = _amount(s, "한도") or Decimal("0")
        bal = _amount(s, "잔액") or Decimal("0")
        cdate = _date(s, "계약일") or _date(s, "약정일") or date(2000, 1, 1)
        mat = _date(s, "만기")

        out.append(
            Borrowing(
                bc_no=bc_no,
                bank=bank,
                contract_type=s[:40],
                limit_amt=limit,
                limit_ccy="KRW",
                balance=bal,
                balance_ccy="KRW",
                contract_date=cdate,
                maturity=mat,
            )
        )

    return out


def parse_ac3_derivative(text: str, bc_no: str, bank: str) -> list[Derivative]:
    """Parse AC3 (Derivatives) from PDF section text."""
    out: list[Derivative] = []

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(k in s for k in ["선도", "스왑", "옵션", "FX"]):
            continue

        d = _date(s, "계약일") or date(2000, 1, 1)
        out.append(
            Derivative(
                bc_no=bc_no,
                bank=bank,
                instrument=s[:40],
                contract_date=d,
                buy_ccy="KRW",
                buy_amt=Decimal("0"),
                sell_ccy="USD",
                sell_amt=Decimal("0"),
            )
        )

    return out


def parse_ac4_guarantee(text: str, bc_no: str, bank: str) -> list[Guarantee]:
    """Parse AC4 (Guarantees) from PDF section text."""
    out: list[Guarantee] = []

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(k in s for k in ["지급보증", "보증", "L/C", "신용장"]):
            continue

        limit = _amount(s, "한도") or Decimal("0")
        bal = _amount(s, "잔액") or Decimal("0")
        out.append(
            Guarantee(
                bc_no=bc_no,
                bank=bank,
                guarantee_type=s[:40],
                limit_amt=limit,
                balance=bal,
            )
        )

    return out


def parse_ac5_collateral(text: str, bc_no: str, bank: str) -> list[Collateral]:
    """Parse AC5 (Collateral) from PDF section text."""
    out: list[Collateral] = []

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(k in s for k in ["담보", "근저당", "질권"]):
            continue

        amt = _amount(s, "장부") or _amount(s, "평가") or Decimal("0")
        out.append(
            Collateral(bc_no=bc_no, bank=bank, collateral_type=s[:40], book_amount=amt)
        )

    return out


def parse_ac6_bills(text: str, bc_no: str, bank: str) -> list[BillCheck]:
    """Parse AC6 (Bills & Checks) from PDF section text."""
    out: list[BillCheck] = []

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(k in s for k in ["어음", "수표"]):
            continue

        out.append(BillCheck(bc_no=bc_no, bank=bank, kind=s[:40]))

    return out


def parse_ac7_insurance(text: str, bc_no: str, bank: str) -> list[Insurance]:
    """Parse AC7 (Insurance) from PDF section text."""
    out: list[Insurance] = []

    for line in text.splitlines():
        s = line.strip()
        if _is_noise(s): continue
        if not any(
            k in s for k in ["보험증권", "보험상품", "보험계약", "가입"]
        ):
            continue

        out.append(Insurance(bc_no=bc_no, bank=bank, product=s[:60]))

    return out


def parse_ac8_general(text: str, bc_no: str, bank: str) -> list[GeneralDeal]:
    """Parse AC8 (General Deals) from PDF section text."""
    return (
        [GeneralDeal(bc_no=bc_no, bank=bank, asset_type="기타")]
        if text.strip()
        else []
    )
