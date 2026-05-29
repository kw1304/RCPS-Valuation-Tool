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

def test_ksf_stock_not_deposit():
    recs=parse_ac1_deposit(_sec1('한국증권금융'), bc_no='BC-9', bank='한국증권금융')
    big=[r for r in recs if r.balance==Decimal('205706000000')]
    assert big, [(r.product,str(r.balance),r.category) for r in recs]
    r=big[0]
    assert r.category=='securities', f'예금으로 오분류: {r.category}'
    assert r.asset_type=='stock', f'asset_type={r.asset_type}'
    assert '코스맥스보통주' in r.product, f'종목명 누락: {r.product!r}'
    # 처분제한(담보제공) 표시
    assert r.collateral_restriction and ('상세명세' in r.collateral_restriction or '담보' in r.collateral_restriction or '처분' in r.collateral_restriction)
    # 어떤 행도 205bn을 예금(bank)으로 두면 안 됨
    assert not any(r.category=='bank' and r.balance==Decimal('205706000000') for r in recs)

def test_kb_securities_no_regression():
    recs=parse_ac1_deposit(_sec1('KB증권'), bc_no='BC-13', bank='KB증권')
    assert any(r.balance==Decimal('103957823700') and r.category=='securities' for r in recs)
