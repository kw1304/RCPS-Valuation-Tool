"""AC4 value-level golden test: 실제 surety.txt fixture 기반.
- 합계/총계 total 행이 record로 새어나오지 않음
- 증권번호(순번) 정수가 limit_amt 로 오인되지 않음
- 실제 보증금액이 balance 로 잡힘."""
from decimal import Decimal
from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac4_guarantee import parse_ac4

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections" / "surety.txt"


def test_ac4_surety_no_total_row_and_correct_amounts():
    blocks = split_sections(FIX.read_text(encoding="utf-8"))
    recs = parse_ac4(blocks[1], bc_no="BC-22", bank="서울보증보험", direction="received")

    # 실제 보증 line item 은 2건 (30,000,000 / 88,850,000). 합계(118,850,000) 행 제외.
    assert len(recs) == 2, f"보증 2건이어야 함(합계행 제외), got {len(recs)}: {[(r.guarantee_type, str(r.balance)) for r in recs]}"

    balances = {r.balance for r in recs}
    assert Decimal("30000000") in balances
    assert Decimal("88850000") in balances
    # 합계 금액이 어디에도 record 로 남지 않음
    assert Decimal("118850000") not in balances
    for r in recs:
        assert "합계" not in r.guarantee_type and "총계" not in r.guarantee_type

    # 증권번호(1,2) 가 limit_amt 로 오인되지 않음 (금액 1개뿐이라 limit=0)
    for r in recs:
        assert r.limit_amt != Decimal("1")
        assert r.limit_amt != Decimal("2")

    # 30,000,000 보증은 balance 로 잡혀야 하고 limit_amt=1 이 아니어야 함
    g30 = next(r for r in recs if r.balance == Decimal("30000000"))
    assert g30.limit_amt == Decimal("0")
