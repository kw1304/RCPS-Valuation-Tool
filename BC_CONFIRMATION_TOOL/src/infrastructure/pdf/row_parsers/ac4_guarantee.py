"""AC4 지급보증 파서. direction: received(제공받음)/provided(제공).

direction='provided'(§5/§6/§8) = 회사가 타 법인(개인)을 위하여 제공한 연대보증/담보 (AC4②).
행 형태(양식별):
  국민  적격보증 코스맥스엔비티(주) 일반운전자금 5,500,000,000.00      (콤마 + .00)
  기업  일반보증약정 코스맥스바이오(주) 할인어음 KRW 2400000000.00     (KRW prefix, 콤마無)
  농협  연대보증 코스맥스바이오(주) 일반대출(01191037658 144000000KRW (4017235573)해당없음  (계좌번호 glued + KRW suffix)
즉 [연대보증유형] [제공받은자=계열사] [대상여신] [한도(금액)] 의 단일 원화 금액 1개.
계좌번호(01191037658/4017235573)·증권번호 index(1,2)는 금액으로 보면 안 되며,
ac5_collateral._won_amounts (콤마그룹/평문/통화prefix·suffix 인식 + 100만 임계 + 괄호 토큰
배제)가 이 모든 경우에서 진짜 한도금액만 정확히 뽑아준다 → 재사용한다."""
from decimal import Decimal
from src.domain.ac_models import Guarantee
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise
from src.infrastructure.pdf.row_parsers.ac5_collateral import (
    _won_amounts, _is_amount_token, _looks_numeric,
)

_CCY_TOKENS = {"KRW", "WON", "USD", "EUR", "JPY", "CNY", "HKD", "GBP", "AUD", "SGD", "CNH"}


def _guarantee_type(line: str) -> str:
    """연대보증 유형(또는 대상여신) = 줄의 첫 '실텍스트' 토큰.

    숫자/금액/통화 토큰은 건너뛴다. 보통 첫 토큰이 보증유형(적격보증/일반보증약정/연대보증).
    """
    toks = line.split()
    for tok in toks:
        if _is_amount_token(tok):
            break
        if _looks_numeric(tok):
            continue
        if tok in _CCY_TOKENS:
            continue
        return tok[:40]
    return (toks[0] if toks else "")[:40]


def parse_ac4(block: str, bc_no: str, bank: str, direction: str = "received") -> list[Guarantee]:
    out: list[Guarantee] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        # 진짜 원화 금액만 (계좌번호·증권번호 index·괄호 토큰 배제, 100만 임계).
        amts = _won_amounts(s)
        if not amts:
            continue
        t = tokenize_row(s)
        gtype = _guarantee_type(s)
        # 금액이 2개 이상이면 첫째=한도, 마지막=잔액. 1개면 잔액으로 보고 한도는 0.
        limit_amt = amts[0] if len(amts) >= 2 else Decimal("0")
        balance = amts[-1]
        out.append(Guarantee(
            bc_no=bc_no, bank=bank, guarantee_type=gtype,
            limit_ccy=t.currency or "KRW", limit_amt=limit_amt,
            balance_ccy=t.currency or "KRW",
            balance=balance,
            maturity=t.dates[0] if t.dates else None,
            direction=direction,
        ))
    return out
