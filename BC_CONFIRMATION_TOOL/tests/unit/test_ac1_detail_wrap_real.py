import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_security_details

ROOT = Path(__file__).resolve().parents[2]
def _sec2(substr):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    return split_sections(extract_rows(Path(p[0]))).get(2,'')

def test_ksf_detail_valuation_wrapped():
    recs=parse_ac1_security_details(_sec2('한국증권금융'),'BC-9','한국증권금융')
    assert any(r.valuation==Decimal('205706000000') for r in recs), [(r.ticker_name,str(r.valuation)) for r in recs]
    assert any('코스맥스' in (r.ticker_name or '') for r in recs)

def test_shinhan_invest_detail_valuation():
    recs=parse_ac1_security_details(_sec2('신한투자'),'BC-12','신한투자증권')
    assert any(r.valuation==Decimal('24450000000') for r in recs), [(r.ticker_name,str(r.valuation)) for r in recs]

def test_kb_detail_no_regression():
    recs=parse_ac1_security_details(_sec2('KB증권'),'BC-13','KB증권')
    assert len(recs)>=8
    assert any(r.valuation==Decimal('30970000000') for r in recs)
    for r in recs:
        assert 'KRW KRW' not in (r.collateral_type or '')
