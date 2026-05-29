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
