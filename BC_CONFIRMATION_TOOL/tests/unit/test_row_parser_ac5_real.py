import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5

ROOT = Path(__file__).resolve().parents[2]
def _sec9(substr):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    t=extract_rows(Path(p[0]))
    return split_sections(t).get(9,'')

def test_keb_hana_no_fragment_garbage():
    recs=parse_ac5(_sec9('KEB하나'), bc_no='BC-4', bank='KEB하나은행', direction='provided')
    # 주소/면적/순위 조각이 record로 나오면 안 됨
    for r in recs:
        assert r.book_amount >= 1000000, f'fragment as amount: {r.collateral_type}={r.book_amount}'
        assert r.collateral_type not in ('경기도','서울','부산','386.15','161.16')
        assert not r.collateral_type.replace('.','').isdigit()
    # 실제 담보 금액(채권최고액/설정금액)이 잡혀야: 2,634,000,000 또는 12,000,000,000 등
    amts={r.book_amount for r in recs}|{getattr(r,'appraised_amount',None) for r in recs}
    assert Decimal('2634000000') in amts or Decimal('12000000000') in amts, sorted(str(a) for a in amts if a)

def test_kookmin_listed_stock_kept():
    recs=parse_ac5(_sec9('국민은행'), bc_no='BC-1', bank='국민은행', direction='provided')
    assert any(r.book_amount==Decimal('20171880000') for r in recs), [str(r.book_amount) for r in recs]
    # 주소/면적 조각 없음
    assert all(r.book_amount>=1000000 for r in recs if r.book_amount)
