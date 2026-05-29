import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_deposit

ROOT = Path(__file__).resolve().parents[2]
def _sec1(substr):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    return split_sections(extract_rows(Path(p[0])))[1]

def test_ibk_no_comma_amounts_recovered():
    recs=parse_ac1_deposit(_sec1('기업은행'), bc_no='BC-2', bank='기업은행')
    bals={str(r.balance) for r in recs}
    assert any(r.balance==Decimal('503905003') for r in recs), f'퇴직연금 5억 누락: {sorted(bals)}'
    assert any(r.balance==Decimal('8002500') for r in recs), f'기업자유 8백만 누락: {sorted(bals)}'
    # 당좌개설보증금 3,000,000 (계좌번호 없어도 행 살아야)
    assert any(r.balance==Decimal('3000000') for r in recs), f'당좌개설보증금 누락: {sorted(bals)}'
    # 이자율이 금액으로 안 들어갔는지 (역): 큰 값이 rate에 없어야 — balance에 있어야
    assert all((r.interest_rate is None) or (r.interest_rate < 100) for r in recs), 'rate에 큰 값 오염'

def test_kookmin_ac1_no_regression():
    recs=parse_ac1_deposit(_sec1('국민은행'), bc_no='BC-1', bank='국민은행')
    assert any(r.balance==Decimal('126598004') for r in recs)
    assert any(r.balance==Decimal('308755') for r in recs)
    assert any(r.balance==Decimal('1500000') for r in recs)

def test_woori_ac1_no_regression():
    recs=parse_ac1_deposit(_sec1('우리은행'), bc_no='BC-3', bank='우리은행')
    assert any(r.balance==Decimal('727414231') for r in recs)
    assert any(r.balance==Decimal('27') for r in recs)
