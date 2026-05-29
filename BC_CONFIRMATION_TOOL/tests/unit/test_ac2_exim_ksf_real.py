import glob
from decimal import Decimal
from datetime import date
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

ROOT = Path(__file__).resolve().parents[2]
def _sec(substr,n):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    return split_sections(extract_rows(Path(p[0]))).get(n,'')

def test_exim_rate_prefix():
    recs=parse_ac2(_sec('한국수출입',2),'BC-8','한국수출입은행')
    assert recs, '수출입 차입금 0건'
    assert any(r.limit_amt==Decimal('5000000000') or r.balance==Decimal('5000000000') for r in recs), [(str(r.limit_amt),str(r.balance)) for r in recs]
    assert any(r.rate==Decimal('4.310') for r in recs), [str(r.rate) for r in recs]
    assert any('수입자금' in r.contract_type for r in recs)

def test_ksf_type_no_header_leak():
    recs=parse_ac2(_sec('한국증권금융',3),'BC-9','한국증권금융')
    for r in recs:
        assert '연이자율' not in r.contract_type and '지급일' not in r.contract_type, r.contract_type
    assert any(r.limit_amt==Decimal('23000000000') for r in recs)
