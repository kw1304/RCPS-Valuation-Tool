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


def _find(sub):
    for d in ['코스맥스비티아이_2024/금융기관조회/온라인조회서', '온라인',
              '에스트래픽/온라인', '코스맥스바이오 (2)/온라인']:
        g = glob.glob(str(ROOT / 'INPUT' / d / f'*{sub}*.pdf'))
        if g:
            return Path(g[0])
    pytest.skip(f'{sub} 없음')


def _blocks(sub):
    t = extract_rows(_find(sub))
    return identify_form(t), split_sections(t)


def test_ksf_sec8_collateral_routed():
    fam, b = _blocks('한국증권금융')
    prof = FormProfile.load()
    found = False
    for n, blk in b.items():
        r = prof.route(fam, n) or route_or_classify(fam, n, blk)
        if r and r.get('ac') == 'AC5' and '131' in blk.replace(',', ''):
            found = True
    assert found, 'KSF 담보 131.7억 미라우팅'


def test_ksf_sec8_collateral_amount_parsed():
    """파이프라인 일관성: KSF §8 담보 → AC5 record, 131,714,940,000 추출."""
    fam, b = _blocks('한국증권금융')
    prof = FormProfile.load()
    target = Decimal('131714940000')
    hit = False
    for n, blk in b.items():
        r = prof.route(fam, n) or route_or_classify(fam, n, blk)
        if r and r.get('ac') == 'AC5':
            recs = _dispatch('AC5', route_or_classify(fam, n, blk).get('block', blk),
                             'BC', '한국증권금융', r)
            for rec in recs:
                if rec.book_amount == target:
                    hit = True
    assert hit, 'KSF 담보 131,714,940,000 미추출'


def test_samsung_transaction_log_ignored():
    fam, b = _blocks('삼성증권')
    prof = FormProfile.load()
    for n, blk in b.items():
        if prof.route(fam, n) is None:
            r = route_or_classify(fam, n, blk)
            if any(k in blk for k in ['거래내역', '입고', '매도', '잔고']) \
                    and not any(s in blk.split('거래내역을 첨부')[0]
                                for s in ['131', '감정 금액 설정']):
                # 담보 sub-block 이 무거래면 거래내역 섹션은 None 유지
                if '해당 거래 없음' in blk.split('거래내역을 첨부')[0]:
                    assert r is None, f'거래내역 sec{n} 잘못 라우팅됨: {r}'


def test_daeshin_transaction_log_not_parsed_as_collateral():
    """대신증권 §8: 담보=해당거래없음, 거래내역에 10억 → AC5 record 생성 금지."""
    fam, b = _blocks('대신증권')
    prof = FormProfile.load()
    for n, blk in b.items():
        if prof.route(fam, n) is not None:
            continue
        r = route_or_classify(fam, n, blk)
        if r and r.get('ac') == 'AC5':
            recs = _dispatch('AC5', r.get('block', blk), 'BC', '대신증권', r)
            assert not recs, f'대신 거래내역이 담보로 파싱됨 sec{n}: {len(recs)}건'
