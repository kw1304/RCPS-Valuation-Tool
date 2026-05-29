import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_security_details
ROOT = Path(__file__).resolve().parents[2]
def _sec2(sub,d):
    g=glob.glob(str(ROOT/'INPUT'/d/f'*{sub}*.pdf'))
    if not g: pytest.skip(f'{sub} 없음')
    return split_sections(extract_rows(Path(g[0]))).get(2,'')
def test_mirae_bond_valuation_not_quantity():
    recs=parse_ac1_security_details(_sec2('미래에셋','에스트래픽/온라인'),'BC','미래에셋')
    vals={r.valuation for r in recs if r.valuation}
    assert Decimal('10593757') in vals or Decimal('41769926') in vals, [(r.ticker_name,str(r.valuation)) for r in recs]
    # 수량(10,650,000/42,015,000)이 평가액으로 들어가면 안 됨
    assert Decimal('42015000') not in vals
def test_kb_stock_no_regression():
    g=glob.glob(str(ROOT/'INPUT'/'온라인'/'*KB증권*.pdf'))
    if not g: pytest.skip('KB증권 없음')
    recs=parse_ac1_security_details(split_sections(extract_rows(Path(g[0]))).get(2,''),'BC','KB증권')
    assert any(r.valuation==Decimal('30970000000') for r in recs)
