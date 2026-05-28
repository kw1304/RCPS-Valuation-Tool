import pytest
import io
import openpyxl
from src.infrastructure.excel_writer.workpaper import build_workpaper


def _full_state():
    return {
        "project": {
            "client": "ACME", "period_end": "2025-12-31",
            "base_ccy": "KRW", "materiality": 500_000_000,
            "tolerable": 250_000_000,
        },
        "populations": {
            "AR": {"count": 120, "total_krw": 250_000_000},
            "AP": {"count": 80, "total_krw": 120_000_000},
        },
        "samples": {
            "AR": {"count": 2, "total_krw": 18_000_000, "items": [
                {"party_id": "AR000", "name": "고객사000", "gl_account": "11200",
                 "balance_krw": 10_000_000, "ccy": "KRW",
                 "selection_reason": "FORCED_RP",
                 "is_related_party": True, "is_bad_debt": False},
                {"party_id": "AR050", "name": "고객사050", "gl_account": "11200",
                 "balance_krw": 8_000_000, "ccy": "KRW",
                 "selection_reason": "REP",
                 "is_related_party": False, "is_bad_debt": False},
            ]},
            "AP": {"count": 1, "total_krw": 5_000_000, "items": [
                {"party_id": "AP000", "name": "공급사000", "gl_account": "21100",
                 "balance_krw": 5_000_000, "ccy": "KRW",
                 "selection_reason": "FORCED_KEY",
                 "is_related_party": False, "is_bad_debt": False},
            ]},
        },
        "confirmations": {
            "AR": [{"party_id": "AR000", "name": "고객사000",
                    "expected": 10_000_000, "confirmed": 10_000_000,
                    "diff": 0, "diff_reason": None, "verdict": "MATCH",
                    "status": "RECEIVED", "pdf_path": None}],
            "AP": [{"party_id": "AP000", "name": "공급사000",
                    "expected": 5_000_000, "confirmed": 4_900_000,
                    "diff": -100_000, "diff_reason": None,
                    "verdict": "DISCREPANCY", "status": "RECEIVED",
                    "pdf_path": None}],
        },
        "alternatives": {
            "AR": [{"party_id": "AR050", "name": "고객사050",
                    "procedure_type": "후속회수",
                    "evidence_sum": 8_000_000, "note": "회수증빙"}],
            "AP": [],
        },
        "projection": {
            "AR": {"confidence": 0.95, "sampling_interval": 50_000_000,
                   "tolerable": 250_000_000,
                   "projected_misstatement": 0,
                   "basic_precision": 150_000_000,
                   "incremental_allowance": 0,
                   "upper_limit": 150_000_000,
                   "verdict": "WITHIN_TOLERABLE",
                   "strata_snapshot": []},
            "AP": {"confidence": 0.95, "sampling_interval": 40_000_000,
                   "tolerable": 50_000_000,
                   "projected_misstatement": 0,
                   "basic_precision": 120_000_000,
                   "incremental_allowance": 0,
                   "upper_limit": 120_000_000,
                   "verdict": "EXCEED",
                   "strata_snapshot": []},
        },
    }


def test_combined_template_loads():
    blob = build_workpaper("cc_combined", _full_state())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    # 통합 sheet 5종
    assert "CC_summary" in wb.sheetnames
    assert "CC_sendlist" in wb.sheetnames
    assert "CC_matching" in wb.sheetnames
    assert "CC_alternative" in wb.sheetnames
    assert "CC_projection" in wb.sheetnames


def test_combined_sendlist_contains_both_kinds():
    """발송명단 시트에 AR + AP 모두 표시."""
    blob = build_workpaper("cc_combined", _full_state())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["CC_sendlist"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "AR000" in flat
    assert "AR050" in flat
    assert "AP000" in flat
    # 종류 컬럼 헤더 포함
    assert "종류" in flat or "kind" in flat


def test_combined_matching_contains_both():
    blob = build_workpaper("cc_combined", _full_state())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["CC_matching"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "MATCH" in flat
    assert "DISCREPANCY" in flat


def test_combined_projection_both_ar_ap():
    blob = build_workpaper("cc_combined", _full_state())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["CC_projection"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    # 채권·채무 라벨 모두
    assert any("채권" in v for v in flat)
    assert any("채무" in v for v in flat)
    assert "WITHIN_TOLERABLE" in flat
    assert "EXCEED" in flat


def test_combined_summary_both_populations():
    blob = build_workpaper("cc_combined", _full_state())
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["CC_summary"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("채권" in v for v in flat)
    assert any("채무" in v for v in flat)
