"""AC2 회계 항등(invariant) 테스트: 약정한도액(limit) >= 대출금액(balance) ALWAYS.

대출잔액이 약정한도액을 초과할 수 없다는 회계 불변을 고정한다.
좌표 재구성 후 wrap 으로 한도/잔액 컬럼 순서가 뒤바뀔 수 있으므로(국민 첫 대출:
'운영일반운전자금대출 0.00 14,500,000,000.0' → 0 이 먼저, 14.5bn 이 뒤),
금액 2개 중 큰 값=한도, 작은 값=잔액으로 귀속해야 회계적으로 옳다.
"""
import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

ROOT = Path(__file__).resolve().parents[2]


def _kookmin_sec2():
    p = [x for x in glob.glob(str(ROOT / 'INPUT' / '온라인' / '*.pdf')) if '국민은행' in x]
    if not p:
        pytest.skip('국민 없음')
    return split_sections(extract_rows(Path(p[0])))[2]


def test_kookmin_limit_ge_balance_invariant():
    recs = parse_ac2(_kookmin_sec2(), bc_no='BC-1', bank='국민은행')
    assert recs
    for r in recs:
        assert r.limit_amt >= r.balance, \
            f'한도<잔액 위반: {r.contract_type} lim={r.limit_amt} bal={r.balance}'
    # 운영자금대출 한도 14.5bn, 잔액 0
    big = [r for r in recs if r.limit_amt == Decimal('14500000000')]
    assert big and big[0].balance == 0, \
        [(str(r.limit_amt), str(r.balance)) for r in recs]
    # 단기수출 한도 1bn 잔액 18,720,900
    sx = [r for r in recs if r.limit_amt == Decimal('1000000000')]
    assert sx and sx[0].balance == Decimal('18720900'), \
        [(str(r.limit_amt), str(r.balance)) for r in recs]
