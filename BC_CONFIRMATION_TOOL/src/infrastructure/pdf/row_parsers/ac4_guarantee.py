"""AC4 지급보증 파서. direction: received(제공받음)/provided(제공)."""
from decimal import Decimal
from src.domain.ac_models import Guarantee
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac4(block: str, bc_no: str, bank: str, direction: str = "received") -> list[Guarantee]:
    out: list[Guarantee] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        amts = t.amounts
        gtype = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        out.append(Guarantee(
            bc_no=bc_no, bank=bank, guarantee_type=gtype,
            limit_ccy=t.currency or "KRW", limit_amt=amts[0],
            balance_ccy=t.currency or "KRW",
            balance=amts[1] if len(amts) >= 2 else Decimal("0"),
            maturity=t.dates[0] if t.dates else None,
            direction=direction,
        ))
    return out
