import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac7_insurance import parse_ac7

ROOT = Path(__file__).resolve().parents[2]


def _sec1(sub, *dirs):
    for d in dirs:
        g = glob.glob(str(ROOT / 'INPUT' / d / f'*{sub}*.pdf'))
        if g:
            return split_sections(extract_rows(Path(g[0]))).get(1, '')
    pytest.skip(f'{sub} 없음')


def _covs(recs):
    return {r.coverage_amount for r in recs if r.coverage_amount}


def test_samsung_fire_coverage():
    recs = parse_ac7(_sec1('삼성화재', '에스트래픽/온라인'), 'BC', '삼성화재')
    assert recs
    assert Decimal('500000000') in _covs(recs), [(r.policy_no, str(r.coverage_amount)) for r in recs]


def test_db_fire_coverage():
    recs = parse_ac7(_sec1('DB손해보험', '코스맥스바이오 (2)/온라인'), 'BC', 'DB손해보험')
    assert Decimal('15000000') in _covs(recs), [(r.policy_no, str(r.coverage_amount)) for r in recs]


def test_kb_bio_coverage():
    recs = parse_ac7(_sec1('KB손해보험', '코스맥스바이오 (2)/온라인'), 'BC', 'KB손해보험')
    assert Decimal('147831814') in _covs(recs), [(r.policy_no, str(r.coverage_amount)) for r in recs]


def test_kb_bti_no_regression():
    recs = parse_ac7(_sec1('KB손해보험', '온라인'), 'BC', 'KB손해보험')
    assert any(r.coverage_amount == Decimal('300000000') for r in recs)
