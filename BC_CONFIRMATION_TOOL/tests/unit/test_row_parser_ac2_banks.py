"""AC2 차입금 다은행 VALUE 테스트.

국민은행만 맞고 우리/KEB하나/신한/산업에서 틀린 숫자가 나오던 문제를 고정한다:
  - 이자율(3.815 / 4.51 / 0.00)이 한도/잔액 컬럼으로 새는 것
  - '총 한도액 :' 합계행이 record 로 잡히는 것
  - contract_type 에 은행명/헤더어가 들어가는 것
  - (KRW) prefix·줄바꿈으로 쪼개진 금액(7,000,000, + 000)을 복구하지 못하는 것

실 회신서 sec2 를 extractor+splitter 로 읽어 expected 값을 검증한다.
"""
import glob
from decimal import Decimal
from datetime import date
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

ROOT = Path(__file__).resolve().parents[2]

# contract_type 으로 절대 들어가선 안 되는 헤더/합계/은행명 토큰
_BAD_TYPE = {
    "금액", "이자", "대출", "종류", "약정한도액", "대출금액", "연이율",
    "최종이자지급일", "최종만기일", "상환방법", "담보", "보증", "총", "한도액",
    "합계", "은행", "우리", "국민", "신한", "산업", "하나", "KEB하나",
}


def _sec2(substr: str) -> str:
    p = [x for x in glob.glob(str(ROOT / "INPUT" / "온라인" / "*.pdf")) if substr in x]
    if not p:
        pytest.skip(f"{substr} PDF 없음")
    t = extract_rows(Path(p[0]))
    return split_sections(t)[2]


def _assert_no_rate_as_amount(recs):
    """모든 한도/잔액은 0 이거나 실원화(>=1000). 이자율(3.815 등)이 절대 들어가면 안 됨."""
    for r in recs:
        assert r.limit_amt == 0 or r.limit_amt >= 1000, f"rate-as-limit? {r.limit_amt} type={r.contract_type}"
        assert r.balance == 0 or r.balance >= 1000, f"rate-as-balance? {r.balance} type={r.contract_type}"


def _assert_type_clean(recs):
    for r in recs:
        ct = r.contract_type or ""
        assert "은행" not in ct, f"은행명이 type 에 누출: {ct}"
        assert ct.strip() not in _BAD_TYPE, f"헤더/합계어가 type: {ct}"
        toks = ct.split()
        for tk in toks:
            assert tk not in _BAD_TYPE, f"헤더 토큰이 type 에 포함: {tk} ({ct})"


def test_kookmin_still_correct():
    """국민은행 회귀: 좌표 재구성으로 회신서 컬럼(약정한도액 대출금액)을 정확히 읽는다.
    첫 대출 '기업일반운전자금대출' 행은 약정한도액 0.00 / 대출금액(잔액) 14,500,000,000
    (구 평면텍스트 경로는 컬럼 연관이 깨져 한도·잔액이 뒤바뀌어 있었음).
    외상매출채권전자대출은 한도 1bn·잔액 18,720,900."""
    recs = parse_ac2(_sec2("국민은행"), bc_no="BC-1", bank="국민은행")
    assert len(recs) == 4, [r.contract_type for r in recs]
    _assert_no_rate_as_amount(recs)
    _assert_type_clean(recs)
    # 대출금액(잔액) 컬럼에 14.5bn — 좌표 재구성 후 회신서 컬럼 순서대로 정확히 귀속.
    w = next((r for r in recs if r.balance == Decimal("14500000000.00")), None)
    assert w is not None, [(str(r.limit_amt), str(r.balance)) for r in recs]
    assert w.limit_amt == Decimal("0.00")
    assert w.rate == Decimal("4.5000")
    assert w.maturity == date(2026, 6, 10)
    two = next((r for r in recs if r.balance == Decimal("18720900.00")), None)
    assert two is not None
    assert two.limit_amt == Decimal("1000000000.00")


def test_woori_zero_not_total_row():
    recs = parse_ac2(_sec2("우리은행"), bc_no="BC-3", bank="우리은행")
    assert recs, "우리 차입금 0건"
    _assert_no_rate_as_amount(recs)
    _assert_type_clean(recs)
    # 총 한도액 행이 record 로 잡히면 안 됨
    assert all(r.contract_type not in ("총", "합계", "총 한도액") for r in recs)
    # 모든 한도/잔액 0 (우리는 전부 0)
    assert all(r.limit_amt == 0 for r in recs), [str(r.limit_amt) for r in recs]
    assert all(r.balance == 0 for r in recs), [str(r.balance) for r in recs]
    # 대출종류는 B2B PLUS 로 시작
    assert any(r.contract_type.startswith("B2B PLUS") for r in recs), [r.contract_type for r in recs]
    first = next(r for r in recs if r.contract_type.startswith("B2B PLUS"))
    assert first.contract_date == date(2009, 6, 25)
    assert first.maturity == date(2026, 7, 3)


def test_keb_hana_amounts_not_rate():
    recs = parse_ac2(_sec2("KEB하나"), bc_no="BC-4", bank="KEB하나은행")
    assert recs, "하나 차입금 0건"
    _assert_no_rate_as_amount(recs)
    _assert_type_clean(recs)
    # 첫 대출: 기업시설일반자금대출 한도/잔액 7,000,000,000, rate 3.815
    first = next((r for r in recs if r.limit_amt == Decimal("7000000000")), None)
    assert first is not None, [str(r.limit_amt) for r in recs]
    assert first.balance == Decimal("7000000000")
    assert first.rate == Decimal("3.815")
    assert "기업시설일반자금대출" in first.contract_type
    assert first.contract_date == date(2014, 6, 16)
    assert first.maturity == date(2026, 7, 16)
    # 둘째: 21,870,000,000 rate 4.601
    second = next((r for r in recs if r.limit_amt == Decimal("21870000000")), None)
    assert second is not None, [str(r.limit_amt) for r in recs]
    assert second.balance == Decimal("21870000000")
    assert second.rate == Decimal("4.601")


def test_shinhan_amount():
    recs = parse_ac2(_sec2("신한은행"), bc_no="BC-5", bank="신한은행")
    assert recs, "신한 차입금 0건"
    _assert_no_rate_as_amount(recs)
    _assert_type_clean(recs)
    r = next((r for r in recs if r.limit_amt == Decimal("12800000000")), None)
    assert r is not None, [str(x.limit_amt) for x in recs]
    assert r.balance == Decimal("12800000000")
    assert r.rate == Decimal("4.51")
    assert "일반자금대출" in r.contract_type
    assert r.contract_date == date(2025, 6, 27)
    assert r.maturity == date(2026, 6, 27)


def test_sanup_limit_wrapped():
    recs = parse_ac2(_sec2("산업은행"), bc_no="BC-6", bank="산업은행")
    assert recs, "산업 차입금 0건"
    _assert_no_rate_as_amount(recs)
    _assert_type_clean(recs)
    assert len(recs) == 2, [r.contract_type for r in recs]
    limits = sorted(str(r.limit_amt) for r in recs)
    r20 = next((r for r in recs if r.limit_amt == Decimal("20000000000")), None)
    r10 = next((r for r in recs if r.limit_amt == Decimal("10000000000")), None)
    assert r20 is not None and r10 is not None, [str(r.limit_amt) for r in recs]
    for r in recs:
        assert r.balance == 0, f"산업 대출금액 0 기대, got {r.balance}"
        assert r.rate == Decimal("4.17000")
        assert "산업운영자금대출" in r.contract_type
        assert r.contract_date == date(2025, 6, 26)
        assert r.maturity == date(2026, 6, 26)
