"""AC2 POSITIONAL 한도/대출 검증 — 참고조서(정답) 값 기반.

참고조서가 증명: AC2 컬럼은 POSITIONAL 이다.
  약정한도액 = 첫 번째 금액 컬럼, 대출금액 = 두 번째 금액 컬럼 (인쇄된 그대로 전사).
max/min 스왑·'한도>=잔액' 불변은 틀렸다 — 미인출 한도(한도0/대출X)·완전인출이
혼재하므로 좌표/문서 순서대로 귀속해야 정답과 일치한다.
  국민 운영자금: 한도 0 / 대출 14,500,000,000
  국민 외상매출: 한도 1,000,000,000 / 대출 18,720,900
  산업 운영자금: 한도 0 / 대출 20,000,000,000 (및 0 / 10,000,000,000)
  하나 기업시설: 한도 == 대출 (7,000,000,000)
"""
import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

ROOT = Path(__file__).resolve().parents[2]


def _sec2(sub, d='온라인'):
    g = glob.glob(str(ROOT / 'INPUT' / d / f'*{sub}*.pdf'))
    if not g:
        pytest.skip(f'{sub} 없음')
    return split_sections(extract_rows(Path(g[0]))).get(2, '')


def test_kookmin_positional():
    recs = parse_ac2(_sec2('국민은행'), 'BC-1', '국민은행')
    # 운영자금 한도0/대출14.5bn (POSITIONAL: 0 이 한도, 14.5bn 이 대출)
    op = [r for r in recs if r.limit_amt == 0 and r.balance == Decimal('14500000000')]
    assert op, [(r.contract_type[:10], str(r.limit_amt), str(r.balance)) for r in recs]
    # 외상매출 한도1bn/대출18.72m
    assert any(r.limit_amt == Decimal('1000000000') and r.balance == Decimal('18720900')
               for r in recs), [(str(r.limit_amt), str(r.balance)) for r in recs]
    # 기업일반운전자금 한도5bn/대출0, 한도3bn/대출0
    assert any(r.limit_amt == Decimal('5000000000') and r.balance == 0 for r in recs)
    assert any(r.limit_amt == Decimal('3000000000') and r.balance == 0 for r in recs)


def test_sanup_positional():
    recs = parse_ac2(_sec2('산업은행'), 'BC-6', '산업은행')
    # 한도0/대출20bn, 한도0/대출10bn (POSITIONAL)
    assert any(r.limit_amt == 0 and r.balance == Decimal('20000000000') for r in recs), \
        [(str(r.limit_amt), str(r.balance)) for r in recs]
    assert any(r.limit_amt == 0 and r.balance == Decimal('10000000000') for r in recs), \
        [(str(r.limit_amt), str(r.balance)) for r in recs]


def test_hana_equal():
    recs = parse_ac2(_sec2('KEB하나'), 'BC-4', '하나은행')
    assert any(r.limit_amt == Decimal('7000000000') and r.balance == Decimal('7000000000')
               for r in recs), [(str(r.limit_amt), str(r.balance)) for r in recs]
