import glob
from decimal import Decimal
from datetime import date
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_security_details
ROOT = Path(__file__).resolve().parents[2]
def _sec2(sub, subdir='에스트래픽/온라인'):
    g=glob.glob(str(ROOT/'INPUT'/subdir/f'*{sub}*.pdf'))
    if not g: pytest.skip(f'{sub} 없음')
    return split_sections(extract_rows(Path(g[0]))).get(2,'')
def test_hana_bond_valuation_not_date():
    recs=parse_ac1_security_details(_sec2('하나증권'),'BC-41','하나증권')
    # 만기일이 평가액에 안 들어가야: 모든 valuation은 날짜(2_000만 미만의 YYYYMMDD)가 아니어야
    for r in recs:
        assert not (r.valuation and 19000000 <= int(r.valuation) <= 20991231 and int(r.valuation)%1==0 and str(int(r.valuation)).startswith(('19','20')) and len(str(int(r.valuation)))==8), f'date as valuation: {r.valuation}'
    # 대전지역개발채권 평가액 5,245,805
    b=[r for r in recs if r.ticker_name and '대전' in r.ticker_name]
    assert b, [r.ticker_name for r in recs]
    assert b[0].valuation==Decimal('5245805'), (str(b[0].valuation), str(b[0].maturity))
    assert b[0].maturity==date(2030,5,31)
def test_kb_stock_detail_no_regression():
    g=glob.glob(str(ROOT/'INPUT'/'온라인'/'*KB증권*.pdf'))
    if not g: pytest.skip('KB증권 없음')
    recs=parse_ac1_security_details(split_sections(extract_rows(Path(g[0]))).get(2,''),'BC-13','KB증권')
    assert len(recs)>=8
    assert any(r.valuation==Decimal('30970000000') for r in recs)
