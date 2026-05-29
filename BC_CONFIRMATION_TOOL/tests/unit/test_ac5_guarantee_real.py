import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5

ROOT = Path(__file__).resolve().parents[2]
prof=FormProfile.load()
def _sec(substr, n):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    return split_sections(extract_rows(Path(p[0]))).get(n,'')

def _has(recs, amt):
    a=Decimal(amt)
    return any(r.book_amount==a or getattr(r,'appraised_amount',None)==a for r in recs)

def test_ibk_guarantee_no_comma():
    recs=parse_ac5(_sec('기업은행',5),'BC-2','기업은행',direction='provided')
    assert _has(recs,'2400000000') and _has(recs,'12000000000'), [str(r.book_amount) for r in recs]

def test_woori_guarantee():
    r5=parse_ac5(_sec('우리은행',5),'BC-3','우리은행',direction='provided')
    assert _has(r5,'17218800000'), [str(r.book_amount) for r in r5]

def test_nonghyup_suffix_glued_currency():
    recs=parse_ac5(_sec('농협',5),'BC-23','농협',direction='provided')
    assert _has(recs,'144000000') or _has(recs,'2400000000'), [str(r.book_amount) for r in recs]

def test_sanup_guarantee():
    recs=parse_ac5(_sec('산업은행',5),'BC-6','산업은행',direction='provided')
    assert _has(recs,'36607800000'), [str(r.book_amount) for r in recs]

def test_hana_collateral_no_regression():
    recs=parse_ac5(_sec('KEB하나',9),'BC-4','KEB하나',direction='provided')
    assert _has(recs,'2634000000'), [str(r.book_amount) for r in recs]
    for r in recs: assert r.book_amount>=1000000  # 조각 없음
