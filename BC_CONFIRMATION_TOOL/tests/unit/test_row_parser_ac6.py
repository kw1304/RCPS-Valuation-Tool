from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac6_bills import parse_ac6

def test_parse_bill():
    block = "약속어음 3 50,000,000"
    recs = parse_ac6(block, bc_no="BC-1", bank="국민은행", direction="received")
    assert len(recs) == 1
    assert recs[0].direction == "received"

def test_dangjwa_sub():
    block = "당좌예금 09360101 1,500,000"
    recs = parse_ac6(block, bc_no="BC-1", bank="국민은행", direction="provided", sub="당좌")
    assert recs[0].sub == "당좌"

def test_no_deal_empty():
    assert parse_ac6("해당 거래 없음", bc_no="BC-1", bank="국민은행", direction="received") == []
