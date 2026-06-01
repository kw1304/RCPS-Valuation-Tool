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
            # 잔액(원) = 최대 금액. 건수는 항상 잔액보다 작은 정수 — 과거 `<1000` 임계는
            # 어음 1,000건 이상에서 건수가 잔액 컬럼을 덮어쓰는 결함(8.5억→1,200원).
            balance = max(t.amounts)
            cnt_candidates = [a for a in t.amounts
                              if a != balance and a == a.to_integral_value() and 0 <= a < balance]
            count = int(min(cnt_candidates)) if cnt_candidates else 0
        # sentinel/placeholder 행 제외: 실제 양수 잔액도 양수 건수도 없으면 skip
        # (예: "대표이사명 99991231 000000000 00000000" → count 0, balance 0)
        if count <= 0 and balance <= 0:
            continue
        out.append(BillCheck(
            bc_no=bc_no, bank=bank, kind=kind,
            count=count, balance=balance, direction=direction, sub=sub,
        ))
    return out
