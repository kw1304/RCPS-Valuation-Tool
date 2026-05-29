from decimal import Decimal
from datetime import date
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

def test_parse_loan_row():
    block = """운영일반운전자금대출 14,500,000,000 0 20250610 20260610 4.5000 20251210 일시상환 9차담보제공
당좌대출 5,000,000,000 0 20210219 20260213 4.6600 20251219 일시상환 9차담보제공"""
    recs = parse_ac2(block, bc_no="BC-1", bank="국민은행")
    assert len(recs) == 2
    assert recs[0].limit_amt == Decimal("14500000000")
    assert recs[0].maturity == date(2026, 6, 10)
    assert recs[0].rate == Decimal("4.5000")
    assert "일시상환" in (recs[0].repayment or "")

def test_no_deal_returns_empty():
    assert parse_ac2("해당 거래 없음", bc_no="BC-1", bank="국민은행") == []
