from src.application.parse_response_uc import _has_real_data

def test_real_data_detection():
    assert _has_real_data("종합보증 USD 30,000,000 20251231")
    assert not _has_real_data("조회기준일 2025.12.31 현재 해당 거래 없음 1/6")
    assert not _has_real_data("해당사항 없음")
    assert _has_real_data("어음 3 50,000,000")
