"""AC5 담보제공자산 파서. direction: provided(제공)/received(제공받음)."""
from decimal import Decimal
from src.domain.ac_models import Collateral
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac5(block: str, bc_no: str, bank: str, direction: str = "provided") -> list[Collateral]:
    out: list[Collateral] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        ctype = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        out.append(Collateral(
            bc_no=bc_no, bank=bank, collateral_type=ctype,
            book_amount=t.amounts[0],
            appraised_amount=t.amounts[1] if len(t.amounts) >= 2 else None,
            direction=direction,
        ))
    return out
