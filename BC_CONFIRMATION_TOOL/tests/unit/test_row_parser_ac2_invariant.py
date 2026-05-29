"""AC2 POSITIONAL 컬럼 귀속 테스트 (국민은행 실측).

이전 '약정한도액(limit) >= 대출금액(balance) ALWAYS' 불변은 **틀렸다**.
참고조서(정답)가 증명: 미인출 한도(한도0/대출X)가 실재하므로 잔액이 한도를
초과하는 행이 정상 존재한다(국민 운영자금: 한도 0 / 대출 14.5bn).
따라서 max/min 스왑을 적용하지 않고, 인쇄된 컬럼 순서대로 귀속한다.
  약정한도액 = 첫 금액 컬럼, 대출금액 = 둘째 금액 컬럼.
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


def test_kookmin_positional_columns():
    recs = parse_ac2(_kookmin_sec2(), bc_no='BC-1', bank='국민은행')
    assert recs
    # 운영자금대출: 약정한도액 0 / 대출금액 14.5bn (미인출 한도가 아닌 인출 우선,
    # POSITIONAL — 첫 컬럼 0 이 한도, 둘째 컬럼 14.5bn 이 대출).
    op = [r for r in recs if r.balance == Decimal('14500000000')]
    assert op and op[0].limit_amt == 0, \
        [(str(r.limit_amt), str(r.balance)) for r in recs]
    # 외상매출채권전자대출: 약정한도액 1bn / 대출금액 18,720,900
    sx = [r for r in recs if r.limit_amt == Decimal('1000000000')]
    assert sx and sx[0].balance == Decimal('18720900'), \
        [(str(r.limit_amt), str(r.balance)) for r in recs]
