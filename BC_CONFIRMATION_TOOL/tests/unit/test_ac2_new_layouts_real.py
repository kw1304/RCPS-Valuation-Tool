"""AC2 — 날짜·이자율 없는 한도행 인식 (실측 PDF 값 검증).

광주은행: 신용카드 한도 5,000,000 (이자율 없음, 잔액 0) — §2.
NH투자증권: 보통담보대출 한도 500,000,000 (계좌번호 선행, 날짜·이자율 없음) — §3.
"""
import glob
from decimal import Decimal
from pathlib import Path

import pytest

from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

ROOT = Path(__file__).resolve().parents[2]


def _find(sub, dirs=None):
    """sub 포함 PDF 1건의 extract_rows. dirs 로 탐색 우선순위를 줄 수 있다."""
    if dirs is None:
        dirs = ['에스트래픽/온라인', '코스맥스바이오 (2)/온라인',
                '코스맥스비티아이_2024/금융기관조회/온라인조회서', '온라인']
    for d in dirs:
        g = glob.glob(str(ROOT / 'INPUT' / d / f'*{sub}*.pdf'))
        if g:
            return extract_rows(Path(g[0]))
    pytest.skip(f'{sub} 없음')


def test_gwangju_credit_card_limit():
    b = split_sections(_find('광주은행'))
    recs = parse_ac2(b.get(2, ''), 'BC-3', '광주은행')
    assert recs, '광주 0건'
    assert any(r.limit_amt == Decimal('5000000') for r in recs), \
        [(r.contract_type, str(r.limit_amt), str(r.balance)) for r in recs]
    assert any('신용카드' in r.contract_type for r in recs), \
        [r.contract_type for r in recs]
    # 신용카드 한도행: 약정한도액 5m / 대출금액 0 (POSITIONAL 단일 한도 컬럼).
    cc = next((r for r in recs if r.limit_amt == Decimal('5000000')), None)
    assert cc is not None and cc.balance == 0, \
        [(str(r.limit_amt), str(r.balance)) for r in recs]


def test_nh_invest_collateral_loan():
    # 코스맥스비티아이_2024 회신본이 보통담보대출 500,000,000 한도를 가진 실측 케이스
    # (에스트래픽 NH 회신본은 '해당 거래 없음').
    b = split_sections(_find('NH투자',
                             dirs=['코스맥스비티아이_2024/금융기관조회/온라인조회서']))
    recs = parse_ac2(b.get(3, ''), 'BC-13', 'NH투자증권')
    assert any(r.limit_amt == Decimal('500000000') for r in recs), \
        [(r.contract_type, str(r.limit_amt)) for r in recs]
    assert any('담보대출' in r.contract_type for r in recs), \
        [r.contract_type for r in recs]
    # 보통담보대출 한도행: 약정한도액 500m / 대출금액 0 (POSITIONAL 단일 한도 컬럼).
    dl = next((r for r in recs if r.limit_amt == Decimal('500000000')), None)
    assert dl is not None and dl.balance == 0, \
        [(str(r.limit_amt), str(r.balance)) for r in recs]
