from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

def test_no_cross_row_contamination():
    # 대출A: 한도 14.5bn (wrapped above), bal 0 ; 대출B: 한도 5bn, bal 777m (both amounts present)
    block = """14,500,000,000
대출A 0.00 20250610 20260610 4.5000 일시상환
대출B 5,000,000,000 777,000,000 20210219 20260213 4.6600 일시상환"""
    recs = parse_ac2(block, bc_no="BC", bank="bank")
    a = next(r for r in recs if "대출A" in r.contract_type)
    b = next(r for r in recs if "대출B" in r.contract_type)
    assert a.limit_amt == Decimal("14500000000")
    assert b.limit_amt == Decimal("5000000000")   # NOT contaminated by 대출A's wrap
    assert b.balance == Decimal("777000000")
