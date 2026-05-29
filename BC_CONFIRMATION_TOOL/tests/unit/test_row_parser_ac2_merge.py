from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2


def test_no_cross_row_contamination():
    # 대출A: 한도 0 / 대출 14.5bn (detail inline '0.00 14,500,000,000.0') — POSITIONAL.
    # 대출B: 한도 5bn / 대출 777m (둘 다 detail inline). B 가 A 를 흡수하면 안 됨.
    block = """대출A 0.00 14,500,000,000.0 20250610 20260610 4.5000 일시상환
대출B 5,000,000,000 777,000,000 20210219 20260213 4.6600 일시상환"""
    recs = parse_ac2(block, bc_no="BC", bank="bank")
    a = next(r for r in recs if "대출A" in r.contract_type)
    b = next(r for r in recs if "대출B" in r.contract_type)
    # POSITIONAL: A 의 첫 컬럼 0 = 한도, 둘째 컬럼 14.5bn(wrap 복구) = 대출.
    assert a.limit_amt == Decimal("0")
    assert a.balance == Decimal("14500000000")
    # B 는 A 의 wrap 에 오염되지 않음.
    assert b.limit_amt == Decimal("5000000000")
    assert b.balance == Decimal("777000000")
