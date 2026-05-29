from decimal import Decimal
from datetime import date
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

def test_tokenize_extracts_dates_amounts_ccy():
    row = "일반자금대출 KRW 1,000,000,000 5,000,000 20250610 20260610 4.5000"
    tok = tokenize_row(row)
    assert tok.currency == "KRW"
    assert Decimal("1000000000") in tok.amounts
    assert date(2025, 6, 10) in tok.dates
    assert tok.rate == Decimal("4.5000")

def test_noise_line_detected():
    assert is_noise("해당 거래 없음")
    assert is_noise("확인자 소속 및 직위 : 기업금융")
    assert not is_noise("일반자금대출 1,000,000,000")
