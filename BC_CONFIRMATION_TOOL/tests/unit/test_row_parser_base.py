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

def test_total_row_is_noise_but_not_product_name():
    from src.infrastructure.pdf.row_parsers.base import is_noise
    assert is_noise("합계 3 118,850,000")          # 합계 leading token → noise
    assert is_noise("소계 2 50,000,000")
    assert not is_noise("종합계약보증 USD 30,000,000")  # 합계 substring but real product → NOT noise
    assert not is_noise("소계약이행보증 10,000,000")
