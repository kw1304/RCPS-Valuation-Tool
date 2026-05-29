import glob, re
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
ROOT = Path(__file__).resolve().parents[2]
def _kookmin():
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if '국민은행' in x]
    if not p: pytest.skip('국민 없음')
    return extract_rows(Path(p[0]))
def test_wrapped_amounts_rejoin():
    t=_kookmin()
    # 퇴직연금 줄에 126,598,004 가 같은 줄에 있어야
    for line in t.splitlines():
        if '퇴직연금' in line:
            assert '126,598,004' in line, f'퇴직연금 줄에 금액 없음: {line!r}'
            break
    else:
        pytest.fail('퇴직연금 줄 없음')
    # ONE KB 사업자통장 줄에 308,755
    assert any('308,755' in l and ('ONE' in l or '055020' in l) for l in t.splitlines()), 'ONE KB 308,755 누락'
    # 당좌개설보증금 1,500,000
    assert any('1,500,000' in l and ('당좌개설' in l or '300000019' in l) for l in t.splitlines()), '당좌개설보증금 1,500,000 누락'
