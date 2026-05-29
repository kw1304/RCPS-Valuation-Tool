from decimal import Decimal
from datetime import date
from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac7_insurance import parse_ac7

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"


def test_insurance_real_policies():
    t = (FIX / "insurance.txt").read_text(encoding="utf-8")
    block = split_sections(t)[1]
    recs = parse_ac7(block, bc_no="BC-19", bank="KB손해보험")
    assert len(recs) == 3, [r.policy_no for r in recs]
    by = {r.policy_no: r for r in recs}
    assert "20258450627" in by
    p = by["20258450627"]
    assert p.coverage_amount == Decimal("300000000")
    assert p.premium == Decimal("2034000")
    assert p.start_date == date(2025, 12, 12)
    assert p.end_date == date(2026, 12, 11)
    # 부보금액 0 은 정상 0 — KB운전자 행이 보존되어야 함
    kb = by["20258440287"]
    assert kb.coverage_amount == Decimal("0")
    assert kb.premium == Decimal("1265530")
