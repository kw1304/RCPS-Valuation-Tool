"""통합 조서(C100/AA100) Excel 빌더.

YAML 양식 로드 → state dict → openpyxl Workbook.
"""
from __future__ import annotations
import io
from pathlib import Path
from typing import Any
import yaml
import openpyxl
from openpyxl.utils import get_column_letter
from src.infrastructure.excel_writer.styles import (
    HEADER_FILL, HEADER_FONT, HEADER_ALIGN,
    BODY_FONT, NUM_ALIGN, TEXT_ALIGN, CELL_BORDER,
    TITLE_FONT, SUBTITLE_FONT, META_FONT, SIGN_FONT, TICKMARK_FONT,
)


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "templates"


def load_template(name: str) -> dict:
    p = _TEMPLATES_DIR / f"{name}.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_nested(d: dict, dotpath: str) -> Any:
    cur: Any = d
    for k in dotpath.split("."):
        if cur is None:
            return None
        cur = cur.get(k) if isinstance(cur, dict) else getattr(cur, k, None)
    return cur


def _write_header(ws, tpl: dict, state: dict) -> int:
    ws.cell(row=1, column=1, value=tpl["title"]).font = TITLE_FONT
    row = 3
    for h in tpl.get("header", []):
        ws.cell(row=row, column=1, value=h["label"]).font = META_FONT
        val = _get_nested(state, h["field"])
        if h.get("format") == "currency" and isinstance(val, (int, float)):
            cell = ws.cell(row=row, column=2, value=val)
            cell.number_format = "#,##0"
        else:
            ws.cell(row=row, column=2, value=val)
        ws.cell(row=row, column=2).font = META_FONT
        row += 1
    return row + 1


def _write_signature(ws, tpl: dict, start_row: int) -> int:
    sig = tpl.get("signature", {})
    ws.cell(row=start_row, column=1, value="-" * 40).font = SIGN_FONT
    r = start_row + 1
    for key in ("prepared_by", "reviewed_by", "date_field"):
        label = sig.get(key, key)
        ws.cell(row=r, column=1, value=label + ":").font = SIGN_FONT
        ws.cell(row=r, column=2, value="(   )").font = SIGN_FONT
        r += 1
    return r + 1


def _write_tickmark_legend(ws, tpl: dict, start_row: int) -> int:
    tm = tpl.get("tickmarks", {})
    if not tm:
        return start_row
    ws.cell(row=start_row, column=1, value="tickmark 범례").font = SUBTITLE_FONT
    r = start_row + 1
    for mark, desc in tm.items():
        ws.cell(row=r, column=1, value=mark).font = TICKMARK_FONT
        ws.cell(row=r, column=2, value=desc).font = META_FONT
        r += 1
    return r + 1


def build_workpaper(template_name: str, state: dict) -> bytes:
    tpl = load_template(template_name)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    kind = tpl["kind"]

    for sheet_spec in tpl["sheets"]:
        ws = wb.create_sheet(sheet_spec["name"])
        row = _write_header(ws, tpl, state)
        ws.cell(row=row, column=1, value=sheet_spec["title"]).font = SUBTITLE_FONT
        row += 2

        section = sheet_spec["section"]
        if section == "design_summary":
            row = _write_design_summary(ws, state, kind, row)
        elif section == "sendlist":
            row = _write_sendlist(ws, state, kind, row)
        elif section == "matching":
            row = _write_matching(ws, state, kind, row)
        elif section == "alternative":
            row = _write_alternative(ws, state, kind, row)
        elif section == "projection":
            row = _write_projection(ws, state, kind, row)

        row += 2
        row = _write_signature(ws, tpl, row)
        if section == "design_summary":
            row = _write_tickmark_legend(ws, tpl, row)

        for col_idx in range(1, 8):
            ws.column_dimensions[get_column_letter(col_idx)].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_design_summary(ws, state, kind, row):
    pop = state.get("populations", {}).get(kind, {})
    samp = state.get("samples", {}).get(kind, {})
    items = [
        ("모집단 건수", pop.get("count", 0)),
        ("모집단 잔액 (KRW)", pop.get("total_krw", 0)),
        ("표본 건수", samp.get("count", 0)),
        ("표본 잔액 (KRW)", samp.get("total_krw", 0)),
        ("커버리지", (samp.get("total_krw", 0) / pop["total_krw"])
                       if pop.get("total_krw") else 0),
    ]
    for label, val in items:
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        c = ws.cell(row=row, column=2, value=val)
        c.font = BODY_FONT
        c.alignment = NUM_ALIGN
        c.number_format = "#,##0" if label != "커버리지" else "0.0%"
        row += 1
    return row


def _write_sendlist(ws, state, kind, row):
    headers = ["거래처코드", "거래처명", "계정과목", "잔액(KRW)", "통화", "선정사유"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1
    for it in state.get("samples", {}).get(kind, {}).get("items", []):
        cells = [it["party_id"], it["name"], it["gl_account"],
                 it["balance_krw"], it["ccy"], it["selection_reason"]]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx == 4:
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_matching(ws, state, kind, row):
    headers = ["거래처", "장부잔액", "회신금액", "차이", "차이사유", "판정", "PDF경로"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1
    for cf in state.get("confirmations", {}).get(kind, []):
        cells = [
            f"{cf['name']} ({cf['party_id']})",
            cf["expected"], cf["confirmed"], cf["diff"],
            cf.get("diff_reason"), cf.get("verdict"), cf.get("pdf_path"),
        ]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx in (2, 3, 4):
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_alternative(ws, state, kind, row):
    headers = ["거래처", "절차유형", "증빙금액(KRW)", "비고"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1
    for ap_item in state.get("alternatives", {}).get(kind, []):
        cells = [
            f"{ap_item.get('name', '')} ({ap_item['party_id']})",
            ap_item["procedure_type"], ap_item["evidence_sum"],
            ap_item.get("note", ""),
        ]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx == 3:
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_projection(ws, state, kind, row):
    p = state.get("projection", {}).get(kind)
    if not p:
        ws.cell(row=row, column=1, value="(Projection 미산출)").font = META_FONT
        return row + 1
    items = [
        ("신뢰수준", p["confidence"]),
        ("Sampling interval (KRW)", p["sampling_interval"]),
        ("Projected misstatement", p["projected_misstatement"]),
        ("Basic precision", p["basic_precision"]),
        ("Incremental allowance", p["incremental_allowance"]),
        ("Upper limit", p["upper_limit"]),
        ("Tolerable", p["tolerable"]),
        ("판정", p["verdict"]),
    ]
    for label, val in items:
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        c = ws.cell(row=row, column=2, value=val)
        c.font = BODY_FONT
        c.alignment = NUM_ALIGN if isinstance(val, (int, float)) else TEXT_ALIGN
        if isinstance(val, (int, float)) and label != "신뢰수준":
            c.number_format = "#,##0"
        elif label == "신뢰수준":
            c.number_format = "0.0%"
        row += 1
    return row
