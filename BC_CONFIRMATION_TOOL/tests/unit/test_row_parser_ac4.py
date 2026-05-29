from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac4_guarantee import parse_ac4

def test_parse_guarantee_with_direction():
    block = "지급보증 L/C 100,000,000 80,000,000 20251231"
    recs = parse_ac4(block, bc_no="BC-1", bank="국민은행", direction="received")
    assert len(recs) == 1
    assert recs[0].limit_amt == Decimal("100000000")
    assert recs[0].direction == "received"

def test_no_deal_returns_empty():
    assert parse_ac4("해당 거래 없음", bc_no="BC-1", bank="국민은행", direction="received") == []
