from decimal import Decimal
from datetime import date
from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac3_derivative import parse_ac3

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"


def test_fx_forward_real():
    t = (FIX / "bank.txt").read_text(encoding="utf-8")
    block = split_sections(t)[4]
    recs = parse_ac3(block, bc_no="BC-1", bank="국민은행")
    assert len(recs) >= 1
    r = recs[0]
    # 실제 bank.txt sec4 의 데이터 행 instrument 토큰은 "스왑"(FX swap) 이다.
    # (STEP0 spec 설명은 "선물"이라 했으나 fixture 바이트는 스왑 — 둘 다 파생상품 키워드)
    assert "스왑" in r.instrument or "선물" in r.instrument
    assert r.contract_date == date(2024, 9, 3)
    assert r.maturity == date(2024, 9, 9)
    # 13.4bn notional present somewhere
    assert Decimal("13416000000") in (r.buy_amt, r.sell_amt) or r.buy_amt == Decimal("13416000000")


def test_securities_derivative_empty():
    t = (FIX / "securities.txt").read_text(encoding="utf-8")
    block = split_sections(t)[5]
    assert parse_ac3(block, bc_no="BC-13", bank="KB증권") == []


def test_two_derivatives_not_merged():
    block = """선물환 USD 20240903 13,416,000,000.00 20240909 0.0000 RR: 4.410 10,000,000.00
스왑 USD 20250101 5,000,000,000.00 20250601 0.0000 4,000,000.00"""
    recs = parse_ac3(block, bc_no="BC", bank="bank")
    assert len(recs) == 2, [r.instrument for r in recs]
    fwd = next(r for r in recs if "선물" in r.instrument)
    swp = next(r for r in recs if "스왑" in r.instrument)
    assert fwd.contract_date == date(2024, 9, 3) and fwd.maturity == date(2024, 9, 9)
    assert swp.contract_date == date(2025, 1, 1) and swp.maturity == date(2025, 6, 1)
    # notionals not cross-contaminated
    assert fwd.buy_amt == Decimal("13416000000") and fwd.sell_amt == Decimal("10000000")
    assert swp.buy_amt == Decimal("5000000000") and swp.sell_amt == Decimal("4000000")
    # rate 4.410 must NOT appear as an amount
    assert Decimal("4.410") not in (fwd.buy_amt, fwd.sell_amt)


def test_rate_not_in_notional():
    block = "선물환 USD 20240903 13,416,000,000.00 20240909 0.0000 RR: 4.410 10,000,000.00"
    r = parse_ac3(block, bc_no="BC", bank="bank")[0]
    assert r.buy_amt == Decimal("13416000000")
    assert r.sell_amt == Decimal("10000000")
