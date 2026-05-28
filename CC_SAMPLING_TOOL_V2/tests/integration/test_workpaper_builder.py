import pytest
import io
import openpyxl
from src.infrastructure.excel_writer.workpaper import (
    build_workpaper, load_template,
)


def _sample_state():
    return {
        "project": {
            "client": "ACME", "period_end": "2025-12-31",
            "base_ccy": "KRW", "materiality": 500_000_000,
            "tolerable": 250_000_000,
        },
        "populations": {"AR": {"count": 100, "total_krw": 5_000_000_000},
                         "AP": {"count": 0, "total_krw": 0}},
        "samples": {"AR": {"count": 10, "total_krw": 1_500_000_000,
                            "items": []}, "AP": {"count": 0, "items": []}},
        "confirmations": {"AR": [], "AP": []},
        "alternatives": {"AR": [], "AP": []},
        "projection": {"AR": None, "AP": None},
    }


def test_load_template_c100():
    tpl = load_template("c100")
    assert tpl["workpaper_code"] == "C100"
    assert tpl["kind"] == "AR"
    assert len(tpl["sheets"]) == 5


def test_build_c100_minimal():
    state = _sample_state()
    blob = build_workpaper("c100", state)
    assert isinstance(blob, bytes) and len(blob) > 0
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "C100_summary" in wb.sheetnames
    assert "C101_sendlist" in wb.sheetnames
    assert "C104_projection" in wb.sheetnames


def test_workpaper_header_contains_client():
    state = _sample_state()
    blob = build_workpaper("c100", state)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["C100_summary"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("ACME" in v for v in flat)


def test_workpaper_signature_block():
    state = _sample_state()
    blob = build_workpaper("c100", state)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["C100_summary"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("작성자" in v for v in flat)
