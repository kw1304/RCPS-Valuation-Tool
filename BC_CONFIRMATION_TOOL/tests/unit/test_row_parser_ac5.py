from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5

def test_parse_collateral():
    block = "부동산근저당 1,200,000,000 900,000,000"
    recs = parse_ac5(block, bc_no="BC-1", bank="국민은행", direction="provided")
    assert len(recs) == 1
    assert recs[0].book_amount == Decimal("1200000000")
    assert recs[0].direction == "provided"

def test_no_deal_empty():
    assert parse_ac5("해당 거래 없음", bc_no="BC-1", bank="국민은행", direction="provided") == []
