from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_security_details

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"


def test_security_detail_from_split_block():
    text = (FIX / "securities.txt").read_text(encoding="utf-8")
    blocks = split_sections(text)
    block = blocks[2]  # securities §2 = 유가증권 상세명세
    recs = parse_ac1_security_details(block, bc_no="BC-13", bank="KB증권")
    assert len(recs) >= 3, f"expected >=3 종목 rows, got {len(recs)}"
    # 종목명·평가액이 채워져야
    assert any(r.ticker_name and r.valuation for r in recs)


def test_detail_still_works_with_header_present():
    # 헤더가 포함된 전체 텍스트로도 여전히 동작 (하위호환)
    text = (FIX / "securities.txt").read_text(encoding="utf-8")
    recs = parse_ac1_security_details(text, bc_no="BC-13", bank="KB증권")
    assert len(recs) >= 3
