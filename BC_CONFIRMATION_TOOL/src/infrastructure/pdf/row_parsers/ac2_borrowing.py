"""AC2 차입금(대출) 파서. 한도금액·잔액·대출일·만기·이자율·상환방법·담보."""
from decimal import Decimal
from src.domain.ac_models import Borrowing
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac2(block: str, bc_no: str, bank: str) -> list[Borrowing]:
    out: list[Borrowing] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts or not (t.dates or t.rate):
            continue
        amts = t.amounts
        limit = amts[0] if len(amts) >= 1 else Decimal("0")
        balance = amts[1] if len(amts) >= 2 else amts[0]
        contract_date = t.dates[0] if len(t.dates) >= 1 else None
        maturity = t.dates[1] if len(t.dates) >= 2 else None
        last_int = t.dates[2] if len(t.dates) >= 3 else None
        contract_type = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        repayment = next((w for w in t.text_tokens if "상환" in w), None)
        collateral = next((w for w in t.text_tokens if "담보" in w or "보증" in w), None)
        out.append(Borrowing(
            bc_no=bc_no, bank=bank, contract_type=contract_type,
            limit_ccy=t.currency or "KRW", limit_amt=limit,
            balance_ccy=t.currency or "KRW", balance=balance,
            contract_date=contract_date, maturity=maturity,
            rate=t.rate, last_interest_date=last_int,
            repayment=repayment, collateral=collateral,
        ))
    return out
