import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac7_insurance import parse_ac7

ROOT = Path(__file__).resolve().parents[2]
def _sec1(substr):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    return split_sections(extract_rows(Path(p[0])))[1]

def test_hanwha_alphanumeric_policies():
    recs=parse_ac7(_sec1('한화손해보험'), bc_no='BC-20', bank='한화손해보험')
    assert len(recs) >= 20, f'한화손보 정책 {len(recs)}건만 (24건 기대)'
    assert any((r.coverage_amount or 0) >= 100_000_000 for r in recs), '부보금액 대형 누락'

def test_meritz_fire_policy():
    recs=parse_ac7(_sec1('메리츠화재'), bc_no='BC-21', bank='메리츠화재')
    assert len(recs) >= 1

def test_hyundai_won_currency():
    recs=parse_ac7(_sec1('현대해상'), bc_no='BC-24', bank='현대해상')
    amts={r.coverage_amount for r in recs}|{getattr(r,'premium',None) for r in recs}
    assert Decimal('1412800000') in amts or Decimal('9692417') in amts, f'현대해상 금액 누락: {sorted(str(a) for a in amts if a)}'

def test_kb_insurance_no_regression():
    recs=parse_ac7(_sec1('KB손해보험'), bc_no='BC-19', bank='KB손해보험')
    assert len(recs)==3
    assert any(r.coverage_amount==Decimal('300000000') and r.premium==Decimal('2034000') for r in recs)
