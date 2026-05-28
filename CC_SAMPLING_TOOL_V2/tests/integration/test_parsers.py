import pytest
import openpyxl
from src.infrastructure.ingest.fs_parser import parse_fs_totals
from src.infrastructure.ingest.rp_parser import parse_related_parties
from src.infrastructure.ingest.allowance_parser import parse_allowance


def _xlsx(tmp_path, sheet, rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(sheet)
    for r in rows:
        ws.append(r)
    p = tmp_path / "f.xlsx"
    wb.save(p)
    return p


def test_parse_fs_totals(tmp_path):
    p = _xlsx(tmp_path, "재무제표", [
        ["계정", "기말금액"],
        ["매출채권", 50_000_000],
        ["매입채무", 30_000_000],
        ["기타", 1],
    ])
    totals = parse_fs_totals(p, sheet_name="재무제표")
    assert totals["AR"] == 50_000_000
    assert totals["AP"] == 30_000_000


def test_parse_related_parties(tmp_path):
    p = _xlsx(tmp_path, "특관자", [
        ["거래처명"],
        ["A자회사"],
        ["B관계회사"],
    ])
    rps = parse_related_parties(p, sheet_name="특관자")
    assert "A자회사" in rps
    assert "B관계회사" in rps


def test_parse_allowance(tmp_path):
    p = _xlsx(tmp_path, "충당금명세", [
        ["거래처코드", "거래처명", "잔액", "충당금", "부실여부"],
        ["P1", "갑", 1000, 500, "N"],
        ["P2", "을", 2000, 2000, "Y"],
    ])
    allow = parse_allowance(p, sheet_name="충당금명세")
    assert allow["P1"]["allowance_amt"] == 500
    assert allow["P1"]["is_bad_debt"] is False
    assert allow["P2"]["allowance_amt"] == 2000
    assert allow["P2"]["is_bad_debt"] is True
