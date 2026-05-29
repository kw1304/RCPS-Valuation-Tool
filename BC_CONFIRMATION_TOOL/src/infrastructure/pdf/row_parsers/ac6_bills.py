"""AC6 어음·수표·당좌 파서. direction: received(교부받음)/provided(교부)."""
from decimal import Decimal
from src.domain.ac_models import BillCheck
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac6(block: str, bc_no: str, bank: str,
              direction: str = "received", sub: str | None = None) -> list[BillCheck]:
    out: list[BillCheck] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts and not t.text_tokens:
            continue
        kind = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        count = 0
        balance = Decimal("0")
        if t.amounts:
            ints = [a for a in t.amounts if a == a.to_integral_value() and a < 1000]
            count = int(ints[0]) if ints else 0
            big = [a for a in t.amounts if a >= 1000]
            balance = big[0] if big else (t.amounts[-1] if t.amounts else Decimal("0"))
        # sentinel/placeholder 행 제외: 실제 양수 잔액도 양수 건수도 없으면 skip
        # (예: "대표이사명 99991231 000000000 00000000" → count 0, balance 0)
        if count <= 0 and balance <= 0:
            continue
        out.append(BillCheck(
            bc_no=bc_no, bank=bank, kind=kind,
            count=count, balance=balance, direction=direction, sub=sub,
        ))
    return out
