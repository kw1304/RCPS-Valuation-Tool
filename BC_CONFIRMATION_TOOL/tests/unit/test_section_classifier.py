from src.infrastructure.pdf.section_classifier import classify_sections


def test_split_sections_by_keywords():
    text = """
    1. 예금 잔액
    KB내맘대로통장 보통예금 계좌번호 09360101 잔액 1,234,567원

    2. 차입금
    일반자금대출 한도 1,000,000,000원 잔액 500,000,000원

    3. 지급보증
    L/C 한도 100,000원
    """
    sections = classify_sections(text)
    assert "AC1" in sections
    assert "AC2" in sections
    assert "AC4" in sections
    assert "예금" in sections["AC1"] or "보통예금" in sections["AC1"]
