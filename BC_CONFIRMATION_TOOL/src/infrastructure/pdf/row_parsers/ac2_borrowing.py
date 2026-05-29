"""AC2 차입금(대출) 파서. 한도금액·잔액·대출일·만기·이자율·상환방법·담보.

실제 회신서는 컬럼이 물리적 줄로 wrap 된다:
  14,500,000,000.0                                  <- 약정한도액 (단독 줄, 위)
  운영일반운전자금대출 0.00 20250610 ... 일시상환 ...  <- 대출종류+대출금액+날짜+이자율 (loan row)
또는 대출종류가 단독 줄로 위에 오기도 한다:
  단기수출채권매입자대출                               <- 종류 (단독 줄, 위)
  1,000,000,000.00 18,720,900.00 20200612 ...        <- 한도+잔액+날짜 (loan row)
따라서 loan row(날짜/이자율 보유) 바로 위의 '순수 숫자' 또는 '순수 텍스트' 줄을
loan row 앞에 병합(prepend)한 뒤 토큰화한다.
"""
import re
from decimal import Decimal
from src.domain.ac_models import Borrowing
from src.infrastructure.pdf.row_parsers.base import (
    tokenize_row, is_noise, _DATE_8, _RATE,
)

_REPAY_KW = ("상환",)
_COLLAT_KW = ("담보", "보증")
_PURE_NUM = re.compile(r"^[\d,]+(?:\.\d+)?$")


def _is_loan_row(s: str) -> bool:
    """날짜(8자리) 또는 이자율 토큰을 가진 줄 = 실제 대출 상세 행."""
    return any(_DATE_8.match(tok) or _RATE.match(tok) for tok in s.split())


def _is_pure_number_line(s: str) -> bool:
    toks = s.split()
    return len(toks) == 1 and bool(_PURE_NUM.match(toks[0]))


def _is_pure_text_line(s: str) -> bool:
    """숫자/금액이 전혀 없는 텍스트만의 줄 (대출종류 후보)."""
    if not s or is_noise(s):
        return False
    return not any(ch.isdigit() for ch in s)


def _reassemble(block: str) -> list[str]:
    """wrap 된 단독 숫자/텍스트 줄을 바로 아래 loan row 에 병합한다.
    보수적으로: pending 줄은 '날짜/이자율을 가진 loan row' 에만 병합.
    종류(텍스트)와 한도(숫자) 가 둘 다 위에 떠 있으면 둘 다 앞에 붙인다."""
    raw = [l.strip() for l in block.splitlines()]
    out: list[str] = []
    pending: list[str] = []  # 아직 loan row 를 못 만난 단독 숫자/텍스트 줄

    for s in raw:
        if not s:
            continue
        if _is_loan_row(s):
            # pending(위에 떠 있던 한도/종류)을 loan row 앞에 prepend
            merged = (" ".join(pending + [s])).strip() if pending else s
            out.append(merged)
            pending = []
        elif _is_pure_number_line(s) or _is_pure_text_line(s):
            # 단독 숫자 또는 종류 텍스트 → 다음 loan row 를 기다림.
            # 단, '0' 같은 의미 없는 단독 숫자(잔액 wrap stray)는 한도로 오인 방지 위해
            # 정수 0 은 버린다.
            if _is_pure_number_line(s):
                v = s.replace(",", "")
                try:
                    if Decimal(v) == 0:
                        continue
                except Exception:
                    pass
            pending.append(s)
        else:
            # 일반 텍스트/꼬리 줄: pending 을 흘려보내지 않고 유지하되 이 줄은 무시.
            # ('(주)_상환청구권' 같은 tail 은 loan row 가 이미 소비된 뒤라 pending 비어 있음)
            continue
    return out


def parse_ac2(block: str, bc_no: str, bank: str) -> list[Borrowing]:
    out: list[Borrowing] = []
    for s in _reassemble(block):
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts or not (t.dates or t.rate):
            continue
        amts = t.amounts
        # 한도/잔액: 금액이 2개 이상이면 첫째=한도, 둘째=잔액(대출금액).
        # 1개뿐이면 그것이 대출금액(잔액)이고 한도는 0 (한도를 복구 못한 경우).
        if len(amts) >= 2:
            limit = amts[0]
            balance = amts[1]
        else:
            limit = Decimal("0")
            balance = amts[0]
        contract_date = t.dates[0] if len(t.dates) >= 1 else None
        maturity = t.dates[1] if len(t.dates) >= 2 else None
        last_int = t.dates[2] if len(t.dates) >= 3 else None
        # 대출종류: 상환·담보 키워드가 아닌 첫 텍스트 토큰
        contract_type = next(
            (w for w in t.text_tokens
             if not any(k in w for k in _REPAY_KW) and not any(k in w for k in _COLLAT_KW)),
            None,
        )
        if contract_type is None:
            contract_type = (t.text_tokens[0] if t.text_tokens else s.split()[0])
        contract_type = contract_type[:40]
        repayment = next((w for w in t.text_tokens if any(k in w for k in _REPAY_KW)), None)
        collateral = next((w for w in t.text_tokens if any(k in w for k in _COLLAT_KW)), None)
        out.append(Borrowing(
            bc_no=bc_no, bank=bank, contract_type=contract_type,
            limit_ccy=t.currency or "KRW", limit_amt=limit,
            balance_ccy=t.currency or "KRW", balance=balance,
            contract_date=contract_date, maturity=maturity,
            rate=t.rate, last_interest_date=last_int,
            repayment=repayment, collateral=collateral,
        ))
    return out
