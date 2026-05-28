"""특수관계자 거래처명 set 반환."""
from __future__ import annotations
from pathlib import Path
import openpyxl


def parse_related_parties(path: Path, sheet_name: str) -> set[str]:
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        return set()
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return set()
    return {str(r[0]).strip() for r in rows[1:] if r and r[0]}
