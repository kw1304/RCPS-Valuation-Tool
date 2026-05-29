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

def test_keb_hana_krw_prefix_amounts():
    recs=parse_ac1_deposit(_sec1('KEB하나'), bc_no='BC-4', bank='KEB하나은행')
    bals={r.balance for r in recs}
    assert Decimal('32023447835') in bals, f'MMDA 320억 누락: {sorted(str(b) for b in bals)}'
    assert Decimal('706014312') in bals, '퇴직연금신탁 706M 누락'
    assert Decimal('20000000') in bals and Decimal('59959081') in bals, '기업자유 금액 누락'
    # USD 1,138,268.99
    assert any(abs(r.balance-Decimal('1138268.99'))<1 for r in recs), '외화 USD 누락'

def test_daishin_zero_rows_listed():
    recs=parse_ac1_deposit(_sec1('대신증권'), bc_no='BC-10', bank='대신증권')
    assert len(recs) >= 11, f'대신 11계좌 중 {len(recs)}건만 (완전성 누락)'

def test_no_regression_key_amounts():
    import itertools
    cases={'국민은행':['126598004','308755','1500000'],'기업은행':['503905003','8002500','3000000'],
           '우리은행':['727414231','27'],'KB증권':['103957823700','1750000000'],'신한투자':['24450000000','17976367']}
    for bank,expect in cases.items():
        recs=parse_ac1_deposit(_sec1(bank), bc_no='X', bank=bank)
        bals={str(r.balance).split('.')[0] for r in recs}
        for e in expect:
            assert e in bals, f'{bank} {e} 회귀: {sorted(bals)}'
