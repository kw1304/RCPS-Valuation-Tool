from src.infrastructure.pdf.generic_parser import (
    parse_ac1_deposit,
)


def test_parse_ac1_simple_balance():
    """Real 회신서 line format: '상품 계좌(10~16) [통화] 잔액 (이자) 이자율 최종이자(YYYYMMDD) 만기(YYYYMMDD)'"""
    text = "사업자응원통장-보통예금 09360101044822 KRW 10,218.00 (0.00) 0.0000 20251213 00000000"
    recs = parse_ac1_deposit(text, bc_no="BC-1", bank="국민은행")
    assert len(recs) >= 1
    r = recs[0]
    assert "보통예금" in r.product
    assert int(r.balance) == 10218
    assert r.currency == "KRW"
    assert r.account_no == "09360101044822"
    assert r.last_interest_date is not None


def test_parse_ac1_securities_format():
    """증권사 line: '상품 계좌 통화 금액 예수금 신용설정 미수금 [제한사항]'"""
    text = "신탁 01211149339 KRW 17,976,367 - - - 해당사항없음"
    recs = parse_ac1_deposit(text, bc_no="BC-12", bank="신한투자증권")
    assert len(recs) >= 1
    r = recs[0]
    assert r.category == "securities"
    assert int(r.balance) == 17976367
