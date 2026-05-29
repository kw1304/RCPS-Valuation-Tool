import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac7_insurance import parse_ac7
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5
ROOT = Path(__file__).resolve().parents[2]
def _sec(sub,d,n):
    g=glob.glob(str(ROOT/'INPUT'/d/f'*{sub}*.pdf'))
    if not g: pytest.skip(f'{sub} 없음')
    return split_sections(extract_rows(Path(g[0]))).get(n,'')
def test_samsung_premium():
    recs=parse_ac7(_sec('삼성화재','에스트래픽/온라인',1),'BC','삼성화재')
    prems={r.premium for r in recs if r.premium}
    assert Decimal('83212000') in prems, [(str(r.coverage_amount),str(r.premium)) for r in recs]
def test_kb_premium_no_regression():
    recs=parse_ac7(_sec('KB손해보험','온라인',1),'BC','KB손해보험')
    assert any(r.coverage_amount==Decimal('300000000') and r.premium==Decimal('2034000') for r in recs)
def test_ac5_senior_lien():
    recs=parse_ac5(_sec('신한은행','에스트래픽/온라인',9),'BC','신한','provided')
    liens={getattr(r,'senior_lien',None) for r in recs}
    assert Decimal('19000000') in liens, [(str(r.book_amount),str(r.appraised_amount),str(getattr(r,'senior_lien',None))) for r in recs]
def test_ac5_primary_no_regression():
    recs=parse_ac5(_sec('KEB하나','온라인',9),'BC','KEB하나','provided')
    assert any(r.book_amount==Decimal('2634000000') for r in recs)
