import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac3_derivative import parse_ac3

ROOT = Path(__file__).resolve().parents[2]


def _find(sub, n):
    for d in ['코스맥스비티아이_2024/금융기관조회/온라인조회서', '온라인',
              '에스트래픽/온라인', '코스맥스바이오 (2)/온라인']:
        g = glob.glob(str(ROOT / 'INPUT' / d / f'*{sub}*.pdf'))
        if g:
            return split_sections(extract_rows(Path(g[0]))).get(n, '')
    pytest.skip(f'{sub} 없음')


def test_shinhan_ccy_swap_legs():
    recs = parse_ac3(_find('신한은행', 4), 'BC-5', '신한은행')
    assert recs, '신한 파생 0건'
    r = recs[0]
    amts = {r.buy_amt, r.sell_amt}
    assert Decimal('785780251') not in amts, '평가금액이 notional로 오저장'
    assert Decimal('10000000') in amts or Decimal('13890000000') in amts, \
        [(r.buy_ccy, str(r.buy_amt), r.sell_ccy, str(r.sell_amt))]
    assert 'USD' in (r.buy_ccy, r.sell_ccy), 'USD leg 손실'
