from pathlib import Path
from src.domain.party_normalize import PartyNormalizer
N = PartyNormalizer.load(Path(__file__).resolve().parents[2] / "configs")

def _m(s): return N.normalize(s)

def test_new_banks_matched():
    for b in ['광주은행','부산은행','수협은행','경남은행','전북은행','제주은행']:
        assert _m(b).matched, b

def test_insurers_matched():
    for b in ['삼성생명보험','한화생명','교보생명','DB손해보험','롯데손해보험','삼성화재해상보험','메리츠화재해상보험','MG손해보험','에이스아메리칸화재해상보험']:
        assert _m(b).matched, b

def test_securities_matched():
    for b in ['아이엠증권','하나증권','신영증권','한국투자증권','유안타증권','DB증권']:
        assert _m(b).matched, b

def test_hana_securities_not_bank():
    # 하나증권 must NOT collapse to KEB하나은행
    r=_m('하나증권')
    assert r.matched and '증권' in r.canonical and '은행' not in r.canonical, r.canonical

def test_im_securities_not_bank():
    r=_m('아이엠증권')
    assert '증권' in r.canonical and '뱅크' not in r.canonical, r.canonical

def test_structural_fallback_asset_managers():
    # 미등록 자산운용/공제조합도 구조매칭
    for b in ['에이원자산운용','지브이에이자산운용','아트만자산운용','라이프자산운용','비엔비자산운용','소프트웨어공제조합','엔지니어링공제조합','전기공사공제조합','정보통신공제조합']:
        assert _m(b).matched, b

def test_cards_matched():
    for b in ['KB국민카드','신한카드','삼성카드']:
        assert _m(b).matched, b

def test_non_financial_not_matched():
    for b in ['법무법인한별','법무법인 케이원챔버','2024-12-31']:
        assert not _m(b).matched, b

def test_existing_still_ok():
    assert _m('국민은행').matched and _m('국민은행').canonical=='국민은행'
    assert _m('KB증권').matched
    assert _m('서울보증보험').matched
