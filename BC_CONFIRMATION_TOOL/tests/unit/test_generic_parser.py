from src.infrastructure.pdf.generic_parser import (
    parse_ac1_deposit,
    parse_ac2_borrowing,
)


def test_parse_ac1_simple_balance():
    text = "보통예금 계좌번호 0936-0101-0057-44 통화 KRW 잔액 10,218원 이자율 0.10%"
    recs = parse_ac1_deposit(text, bc_no="BC-1", bank="국민은행")
    assert len(recs) >= 1
    r = recs[0]
    assert r.product.startswith("보통예금") or "보통예금" in r.product
    assert int(r.balance) == 10218
    assert r.currency == "KRW"


def test_parse_ac2_borrowing_with_limit():
    text = "일반자금대출 한도 1,000,000,000원 잔액 500,000,000원 계약일 2025-06-10"
    recs = parse_ac2_borrowing(text, bc_no="BC-2", bank="기업은행")
    assert len(recs) == 1
    assert int(recs[0].limit_amt) == 1_000_000_000
    assert int(recs[0].balance) == 500_000_000
