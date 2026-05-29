"""AC2 value-level golden test: 실제 bank.txt fixture(국민은행) 기반.
컬럼 wrap 된 약정한도액/대출종류가 올바른 record 로 재조립되는지 고정한다."""
from decimal import Decimal
from datetime import date
from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections" / "bank.txt"


def test_ac2_bank_wrapped_limit_balance():
    blocks = split_sections(FIX.read_text(encoding="utf-8"))
    recs = parse_ac2(blocks[2], bc_no="BC-1", bank="국민은행")

    assert len(recs) == 4, f"국민은행 sec2 대출 4건, got {len(recs)}"

    # wrap 된 14.5bn 한도가 복구되어야 하고, 같은 행의 대출금액(잔액)은 0.00
    wrapped = next((r for r in recs if r.limit_amt == Decimal("14500000000.0")), None)
    assert wrapped is not None, "wrap 된 14,500,000,000 한도가 복구되지 않음"
    assert wrapped.balance == Decimal("0.00")
    assert wrapped.limit_amt != wrapped.balance
    assert wrapped.rate == Decimal("4.5000")
    assert wrapped.maturity == date(2026, 6, 10)

    # 대출종류가 단독 줄로 wrap 된 행: 한도 1bn / 잔액 18,720,900 둘 다 복구
    twoamt = next((r for r in recs if r.balance == Decimal("18720900.00")), None)
    assert twoamt is not None, "한도+잔액 둘 다 가진 행이 복구되지 않음"
    assert twoamt.limit_amt == Decimal("1000000000.00")

    # contract_type 에 상환/담보 키워드가 들어가면 안 됨
    for r in recs:
        assert "상환" not in r.contract_type
        assert "담보" not in r.contract_type

    # 잔액을 한도로 default 하지 않음: 한도와 잔액이 모두 0 인 행은 없어야 함(여긴 모두 한도>0)
    for r in recs:
        assert r.limit_amt > 0
