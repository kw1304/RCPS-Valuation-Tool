import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.form_profile import FormProfile
from src.application.parse_response_uc import route_or_classify, _dispatch
ROOT = Path(__file__).resolve().parents[2]
def _route_recs(sub, ac_want):
    g=glob.glob(str(ROOT/'INPUT'/'온라인'/f'*{sub}*.pdf'))
    if not g: pytest.skip(f'{sub} 없음')
    t=extract_rows(Path(g[0])); fam=identify_form(t); b=split_sections(t)
    out=[]
    for n,blk in b.items():
        r=route_or_classify(fam,n,blk)
        if r and r['ac']==ac_want:
            out+=_dispatch(ac_want, r.get('block',blk),'BC',sub,r)
    return out
def test_kookmin_yeondae_to_ac4():
    recs=_route_recs('국민은행','AC4')
    amts={getattr(r,'limit_amt',None) or getattr(r,'balance',None) for r in recs}
    # 연대보증 코스맥스엔비티 5,500,000,000
    assert Decimal('5500000000') in amts, [(str(getattr(r,'limit_amt','')),str(getattr(r,'balance',''))) for r in recs]
def test_ibk_yeondae_no_comma_to_ac4():
    recs=_route_recs('기업은행','AC4')
    amts={getattr(r,'limit_amt',None) or getattr(r,'balance',None) for r in recs}
    assert Decimal('2400000000') in amts and Decimal('12000000000') in amts, [(str(getattr(r,'limit_amt','')),str(getattr(r,'balance',''))) for r in recs]
def test_nonghyup_yeondae_glued_currency_to_ac4():
    recs=_route_recs('농협','AC4')
    amts={getattr(r,'limit_amt',None) or getattr(r,'balance',None) for r in recs}
    assert Decimal('144000000') in amts or Decimal('6000000000') in amts, [(str(getattr(r,'limit_amt','')),str(getattr(r,'balance',''))) for r in recs]
def test_kookmin_collateral_stays_ac5():
    recs=_route_recs('국민은행','AC5')
    amts={r.book_amount for r in recs}
    assert Decimal('20171880000') in amts, [str(r.book_amount) for r in recs]  # 상장주식 §9
