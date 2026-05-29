"""AC2 value-level golden test: 좌표 재구성 bank.txt fixture(국민은행) 기반.

AC2 컬럼은 POSITIONAL (참고조서 정답 기준): 약정한도액 = 첫 금액 컬럼,
대출금액 = 둘째 금액 컬럼, 인쇄된 그대로 전사한다. 국민 첫 대출 행은
'0.00 14,500,000,000.0' 이므로 약정한도액 0 / 대출금액 14.5bn 이 정답이다.
(14.5bn 은 줄바꿈으로 끝자리('0')가 다음 줄로 잘렸다가 복구된다.)"""
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

    # 첫 대출: '0.00 14,500,000,000.0' → 약정한도액 0 / 대출금액 14.5bn (POSITIONAL).
    wrapped = next((r for r in recs if r.balance == Decimal("14500000000.00")), None)
    assert wrapped is not None, "대출금액 14,500,000,000 이 복구되지 않음"
    assert wrapped.limit_amt == Decimal("0")
    assert wrapped.limit_amt != wrapped.balance
    assert wrapped.rate == Decimal("4.5000")
    assert wrapped.maturity == date(2026, 6, 10)

    # 한도+잔액 둘 다 가진 행: 약정한도액 1bn / 대출금액 18,720,900
    twoamt = next((r for r in recs if r.balance == Decimal("18720900.00")), None)
    assert twoamt is not None, "한도+잔액 둘 다 가진 행이 복구되지 않음"
    assert twoamt.limit_amt == Decimal("1000000000.00")

    # 기업일반운전자금대출 5bn/0, 3bn/0 (POSITIONAL: 한도 컬럼만, 대출 0)
    assert any(r.limit_amt == Decimal("5000000000.00") and r.balance == 0 for r in recs)
    assert any(r.limit_amt == Decimal("3000000000.00") and r.balance == 0 for r in recs)

    # contract_type 에 상환/담보 키워드가 들어가면 안 됨
    for r in recs:
        assert "상환" not in r.contract_type
        assert "담보" not in r.contract_type

    # 모든 금액은 0 이거나 실원화(>=1000): 이자율(4.5000 등)이 금액으로 새지 않음.
    for r in recs:
        assert r.limit_amt == 0 or r.limit_amt >= 1000
        assert r.balance == 0 or r.balance >= 1000
