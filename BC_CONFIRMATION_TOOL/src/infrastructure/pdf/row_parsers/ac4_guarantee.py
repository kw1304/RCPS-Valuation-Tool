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
        # 증권번호·순번 등 index 정수(쉼표 없는 < 1000 정수)는 금액이 아니므로 제거.
        # 원본 토큰 중 어떤 것이 쉼표를 포함했는지로 "진짜 돈"을 판별한다.
        raw_tokens = s.split()
        comma_vals = {tok.replace(",", "") for tok in raw_tokens if "," in tok}

        def _is_money(a):
            sval = str(a.to_integral_value()) if a == a.to_integral_value() else str(a)
            if sval.replace(".", "").lstrip("-") in comma_vals:
                return True
            # 쉼표가 원래 없던 값: index/순번 의심 → 1000 이상만 돈으로 인정
            return a >= 1000
        amts = [a for a in t.amounts if _is_money(a)]
        if not amts:
            continue
        gtype = (t.text_tokens[0] if t.text_tokens else raw_tokens[0])[:40]
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
