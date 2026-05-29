"""국민은행 §1 예금 AC1 VALUE 테스트 — FULL 파이프라인(extract_rows→split→parse).

무테 표의 줄바꿈 금액이 좌표 재구성으로 복구되어 가짜 0원이 사라지는지 고정한다.
ground truth: 11개 계좌, 퇴직연금 126,598,004 / ONE KB 308,755 / 당좌개설보증금 1,500,000.
"""
import glob
from decimal import Decimal
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_deposit

ROOT = Path(__file__).resolve().parents[2]


def _kookmin_ac1():
    p = [x for x in glob.glob(str(ROOT / "INPUT" / "온라인" / "*.pdf")) if "국민은행" in x]
    if not p:
        pytest.skip("국민은행 PDF 없음")
    block = split_sections(extract_rows(Path(p[0])))[1]
    return parse_ac1_deposit(block, bc_no="BC-1", bank="국민은행")


def test_kookmin_deposit_rows_and_amounts():
    recs = _kookmin_ac1()
    assert len(recs) >= 11, f"예금 행 11개 이상 기대, got {len(recs)}"

    def _bal(pred):
        r = next((x for x in recs if pred(x)), None)
        assert r is not None, f"행 없음 ({[x.product for x in recs]})"
        return r.balance

    # 퇴직연금 — 줄바꿈으로 유실되던 가짜 0원이 복구되어야
    assert _bal(lambda x: "퇴직연금" in (x.product or "")) == Decimal("126598004.00")
    # ONE KB 사업자통장 — 행 자체가 누락되던 케이스
    assert _bal(lambda x: x.account_no == "09360101055020") == Decimal("308755.00")
    # 당좌개설보증금 — 행 자체가 누락되던 케이스
    assert _bal(lambda x: "당좌개설보증금" in (x.product or "")
                or x.account_no == "0936127300000019") == Decimal("1500000.00")
