"""AC6 거래명세/결제명세 로그 억제 — 레코드 폭증 방지 (real-PDF value test).

§10 당좌거래명세(입금금액/지급금액/적요 일별 거래원장)와 §7 전자어음 결제명세
(만기일자/금액/일련번호 per-serial 결제 enumeration)는 확인 대상 어음·수표 보유가
아니라 거래 로그다. AC6 레코드로 폭증시키면 안 된다 (당좌예금 잔액은 AC1 §1에 있음).
"""
import glob
from pathlib import Path

import pytest

from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.section_splitter import split_sections
from src.application.parse_response_uc import route_or_classify, _dispatch

ROOT = Path(__file__).resolve().parents[2]


def _ibk_bio():
    g = glob.glob(str(ROOT / 'INPUT' / '코스맥스바이오 (2)' / '온라인' / '*기업은행*.pdf'))
    if not g:
        pytest.skip('기업은행 없음')
    t = extract_rows(Path(g[0]))
    return identify_form(t), split_sections(t)


def test_dangjwa_log_not_exploded():
    fam, b = _ibk_bio()
    total = 0
    for n, blk in b.items():
        r = route_or_classify(fam, n, blk)
        if r and r['ac'] == 'AC6':
            total += len(_dispatch('AC6', r.get('block', blk), 'BC', '기업은행', r))
    assert total < 30, f'AC6 폭증: {total}건 (당좌거래명세 로그 미억제)'


def test_section10_dangjwa_log_suppressed():
    """§10 입금금액/지급금액/적요 당좌거래명세 → AC6 0건."""
    fam, b = _ibk_bio()
    blk = b.get(10, '')
    assert blk, '§10 없음'
    r = route_or_classify(fam, 10, blk)
    cnt = len(_dispatch('AC6', r.get('block', blk), 'BC', '기업은행', r)) if r and r['ac'] == 'AC6' else 0
    assert cnt == 0, f'§10 당좌거래명세 미억제: {cnt}건'


def test_section7_settlement_log_suppressed():
    """§7 만기일자/금액/일련번호 전자어음 결제명세 (per-serial 수백건) → AC6 0건."""
    fam, b = _ibk_bio()
    blk = b.get(7, '')
    assert blk, '§7 없음'
    r = route_or_classify(fam, 7, blk)
    cnt = len(_dispatch('AC6', r.get('block', blk), 'BC', '기업은행', r)) if r and r['ac'] == 'AC6' else 0
    assert cnt == 0, f'§7 전자어음 결제명세 미억제: {cnt}건'
