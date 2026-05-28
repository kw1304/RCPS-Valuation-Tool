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
        if kind == "COMBINED":
            if section == "design_summary":
                row = _write_summary_7620(ws, state, row)
            elif section == "control_sheet":
                row = _write_c100_control(ws, state, row)
            elif section == "size_determination":
                row = _write_c100_1_size(ws, state, row)
            elif section == "key_item":
                row = _write_c100_2_keyitem(ws, state, row)
            elif section == "mus_sample":
                row = _write_c100_3_mus(ws, state, row)
            elif section == "alternative":
                row = _write_alternative_combined(ws, state, row)
        else:
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


def _write_design_summary_combined(ws, state, row):
    """채권·채무 모집단·표본 요약 — 종류 컬럼 + 합계 행."""
    headers = ["종류", "모집단 건수", "모집단 잔액(KRW)", "표본 건수",
               "표본 잔액(KRW)", "커버리지"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    totals = {"pop_count": 0, "pop_total": 0.0,
              "samp_count": 0, "samp_total": 0.0}
    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        pop = state.get("populations", {}).get(kind_code, {})
        samp = state.get("samples", {}).get(kind_code, {})
        pop_c = pop.get("count", 0)
        pop_t = pop.get("total_krw", 0)
        samp_c = samp.get("count", 0)
        samp_t = samp.get("total_krw", 0)
        cov = samp_t / pop_t if pop_t else 0

        cells = [label, pop_c, pop_t, samp_c, samp_t, cov]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx in (2, 4):
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            elif c_idx in (3, 5):
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            elif c_idx == 6:
                c.alignment = NUM_ALIGN
                c.number_format = "0.0%"
            else:
                c.alignment = TEXT_ALIGN
        totals["pop_count"] += pop_c
        totals["pop_total"] += pop_t
        totals["samp_count"] += samp_c
        totals["samp_total"] += samp_t
        row += 1

    # 합계
    cov_total = (totals["samp_total"] / totals["pop_total"]
                 if totals["pop_total"] else 0)
    cells = ["합계", totals["pop_count"], totals["pop_total"],
             totals["samp_count"], totals["samp_total"], cov_total]
    for c_idx, v in enumerate(cells, start=1):
        c = ws.cell(row=row, column=c_idx, value=v)
        c.font = SUBTITLE_FONT
        c.border = CELL_BORDER
        if c_idx in (2, 4):
            c.alignment = NUM_ALIGN
            c.number_format = "#,##0"
        elif c_idx in (3, 5):
            c.alignment = NUM_ALIGN
            c.number_format = "#,##0"
        elif c_idx == 6:
            c.alignment = NUM_ALIGN
            c.number_format = "0.0%"
        else:
            c.alignment = TEXT_ALIGN
    row += 1
    return row


def _write_sendlist_combined(ws, state, row):
    headers = ["종류", "거래처코드", "거래처명", "계정과목",
               "잔액(KRW)", "통화", "선정사유"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        for it in state.get("samples", {}).get(kind_code, {}).get("items", []):
            cells = [label, it["party_id"], it["name"], it["gl_account"],
                     it["balance_krw"], it["ccy"], it["selection_reason"]]
            for c_idx, v in enumerate(cells, start=1):
                c = ws.cell(row=row, column=c_idx, value=v)
                c.font = BODY_FONT
                c.border = CELL_BORDER
                if c_idx == 5:
                    c.alignment = NUM_ALIGN
                    c.number_format = "#,##0"
                else:
                    c.alignment = TEXT_ALIGN
            row += 1
    return row


def _write_matching_combined(ws, state, row):
    headers = ["종류", "거래처", "장부잔액", "회신금액", "차이",
               "차이사유", "판정", "PDF경로"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        for cf in state.get("confirmations", {}).get(kind_code, []):
            cells = [
                label,
                f"{cf['name']} ({cf['party_id']})",
                cf["expected"], cf["confirmed"], cf["diff"],
                cf.get("diff_reason"), cf.get("verdict"), cf.get("pdf_path"),
            ]
            for c_idx, v in enumerate(cells, start=1):
                c = ws.cell(row=row, column=c_idx, value=v)
                c.font = BODY_FONT
                c.border = CELL_BORDER
                if c_idx in (3, 4, 5):
                    c.alignment = NUM_ALIGN
                    c.number_format = "#,##0"
                else:
                    c.alignment = TEXT_ALIGN
            row += 1
    return row


def _write_alternative_combined(ws, state, row):
    headers = ["종류", "거래처", "절차유형", "증빙금액(KRW)", "비고"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        for ap_item in state.get("alternatives", {}).get(kind_code, []):
            cells = [
                label,
                f"{ap_item.get('name', '')} ({ap_item['party_id']})",
                ap_item["procedure_type"], ap_item["evidence_sum"],
                ap_item.get("note", ""),
            ]
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


def _write_projection_combined(ws, state, row):
    """채권·채무 별로 projection 표시 + 마지막에 합산 verdict."""
    # 컬럼: 항목 | 채권 | 채무 | 합산
    headers = ["항목", "채권", "채무", "합산"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    ar = state.get("projection", {}).get("AR") or {}
    ap = state.get("projection", {}).get("AP") or {}

    def _val(d, key, default=0):
        return d.get(key, default) if d else default

    rows_data = [
        ("신뢰수준", _val(ar, "confidence"), _val(ap, "confidence"), None),
        ("Sampling interval", _val(ar, "sampling_interval"),
         _val(ap, "sampling_interval"), None),
        ("Projected misstatement",
         _val(ar, "projected_misstatement"),
         _val(ap, "projected_misstatement"),
         _val(ar, "projected_misstatement") + _val(ap, "projected_misstatement")),
        ("Basic precision",
         _val(ar, "basic_precision"), _val(ap, "basic_precision"),
         _val(ar, "basic_precision") + _val(ap, "basic_precision")),
        ("Incremental allowance",
         _val(ar, "incremental_allowance"), _val(ap, "incremental_allowance"),
         _val(ar, "incremental_allowance") + _val(ap, "incremental_allowance")),
        ("Upper limit",
         _val(ar, "upper_limit"), _val(ap, "upper_limit"),
         _val(ar, "upper_limit") + _val(ap, "upper_limit")),
        ("Tolerable",
         _val(ar, "tolerable"), _val(ap, "tolerable"),
         _val(ar, "tolerable") + _val(ap, "tolerable")),
    ]

    for label, ar_v, ap_v, sum_v in rows_data:
        cells = [label, ar_v, ap_v, sum_v if sum_v is not None else ""]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx == 1:
                c.alignment = TEXT_ALIGN
            elif label == "신뢰수준":
                c.alignment = NUM_ALIGN
                if isinstance(v, (int, float)):
                    c.number_format = "0.0%"
            else:
                c.alignment = NUM_ALIGN
                if isinstance(v, (int, float)):
                    c.number_format = "#,##0"
        row += 1

    # 판정 행
    ar_verdict = ar.get("verdict") if ar else "—"
    ap_verdict = ap.get("verdict") if ap else "—"
    sum_upper = _val(ar, "upper_limit") + _val(ap, "upper_limit")
    sum_tol = _val(ar, "tolerable") + _val(ap, "tolerable")
    sum_verdict = "WITHIN_TOLERABLE" if sum_upper <= sum_tol else "EXCEED"

    cells = ["판정", ar_verdict, ap_verdict, sum_verdict]
    for c_idx, v in enumerate(cells, start=1):
        c = ws.cell(row=row, column=c_idx, value=v)
        c.font = SUBTITLE_FONT
        c.border = CELL_BORDER
        c.alignment = TEXT_ALIGN
    row += 1
    return row


def _write_summary_7620(ws, state, row):
    """샘플링 요약 — overview 행 + 강제포함/제외 내역."""
    headers = ["종류", "모집단 건수", "모집단 잔액(KRW)", "표본 건수",
               "강제포함(RP)", "강제포함(KEY)", "대표(REP)",
               "표본 잔액(KRW)", "커버리지"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    totals = [0] * 6  # pop_c, pop_t, samp_c, samp_t, rp, key, rep
    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        pop = state.get("populations", {}).get(kind_code, {})
        samp = state.get("samples", {}).get(kind_code, {})
        items = samp.get("items", [])
        n_rp = sum(1 for it in items if it.get("selection_reason") == "FORCED_RP")
        n_key = sum(1 for it in items if it.get("selection_reason") == "FORCED_KEY")
        n_rep = sum(1 for it in items if it.get("selection_reason") == "REP")
        pop_c = pop.get("count", 0)
        pop_t = pop.get("total_krw", 0)
        samp_c = samp.get("count", 0)
        samp_t = samp.get("total_krw", 0)
        cov = samp_t / pop_t if pop_t else 0
        cells = [label, pop_c, pop_t, samp_c, n_rp, n_key, n_rep, samp_t, cov]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx == 1:
                c.alignment = TEXT_ALIGN
            elif c_idx == 9:
                c.alignment = NUM_ALIGN
                c.number_format = "0.0%"
            else:
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
        totals[0] += pop_c
        totals[1] += pop_t
        totals[2] += samp_c
        totals[3] += samp_t
        totals[4] += n_rp
        totals[5] += n_key
        row += 1

    # 합계
    cov_total = totals[3] / totals[1] if totals[1] else 0
    cells = ["합계", totals[0], totals[1], totals[2],
             totals[4], totals[5], totals[2] - totals[4] - totals[5],
             totals[3], cov_total]
    for c_idx, v in enumerate(cells, start=1):
        c = ws.cell(row=row, column=c_idx, value=v)
        c.font = SUBTITLE_FONT
        c.border = CELL_BORDER
        if c_idx == 1:
            c.alignment = TEXT_ALIGN
        elif c_idx == 9:
            c.alignment = NUM_ALIGN
            c.number_format = "0.0%"
        else:
            c.alignment = NUM_ALIGN
            c.number_format = "#,##0"
    row += 1
    return row


def _write_c100_control(ws, state, row):
    """C100 조회서 control sheet — 거래처별 행, 계정과목별 컬럼.

    src_sheet에 적힌 계정과목명을 컬럼화. 같은 거래처 여러 계정에 잔액 있으면 분산.
    """
    # 모든 표본에서 src_sheet 추출하여 동적 계정 컬럼 결정
    ar_items = state.get("samples", {}).get("AR", {}).get("items", [])
    ap_items = state.get("samples", {}).get("AP", {}).get("items", [])

    # ingest_uc 집계로 src_sheet에 "외상매출금+미수금" 형태 가능
    # 각 거래처의 src_sheet 분리해서 계정명 추출
    ar_accounts: set[str] = set()
    ap_accounts: set[str] = set()
    for it in ar_items:
        srcs = (it.get("gl_account") or "").split("+")
        # src_sheet이 더 정확하지만 state엔 없음 → gl_account 사용
        # 사실 v2 state는 gl_account만 노출 — 계정과목명 분리는 한계
        # 임시: 단일 컬럼 "채권 잔액"으로 통합 표기
    # 단순화: AR 컬럼 1개 + AP 컬럼 1개로 표기 (계정과목별 분리는 ingest 시 src_sheet 보존이 필요한데 state가 노출 안 함)

    headers = ["No", "거래처코드", "거래처명",
               "채권 잔액(KRW)", "채무 잔액(KRW)", "합계(KRW)", "선정사유"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    # 거래처별 합산 (같은 party_id 또는 name AR+AP)
    by_party: dict[str, dict] = {}
    for it in ar_items:
        key = it.get("party_id") or it.get("name")
        ent = by_party.setdefault(key, {
            "party_id": it.get("party_id"), "name": it.get("name"),
            "ar": 0, "ap": 0,
            "reasons": set(),
        })
        ent["ar"] += abs(it.get("balance_krw", 0))
        ent["reasons"].add(it.get("selection_reason", ""))
    for it in ap_items:
        # AR과 다른 party_id일 수 있음
        key = it.get("party_id") or it.get("name")
        # AR과 같은 키여도 별개 처리 (party_id 일치 시 합쳐짐)
        ent = by_party.setdefault(key, {
            "party_id": it.get("party_id"), "name": it.get("name"),
            "ar": 0, "ap": 0,
            "reasons": set(),
        })
        ent["ap"] += abs(it.get("balance_krw", 0))
        ent["reasons"].add(it.get("selection_reason", ""))

    # 총합 큰 순 정렬
    rows_sorted = sorted(by_party.values(), key=lambda e: -(e["ar"] + e["ap"]))
    for i, ent in enumerate(rows_sorted, start=1):
        total = ent["ar"] + ent["ap"]
        reason = ",".join(sorted(ent["reasons"]))
        cells = [i, ent["party_id"], ent["name"],
                 ent["ar"] or "", ent["ap"] or "", total, reason]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx in (1, 4, 5, 6):
                c.alignment = NUM_ALIGN
                if isinstance(v, (int, float)) and v:
                    c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_c100_1_size(ws, state, row):
    """C100-1 표본규모 결정 — key-value 표."""
    proj = state.get("project", {})
    materiality = proj.get("materiality", 0)
    tolerable = proj.get("tolerable", 0)

    items = [
        ("감사목적", "보고기간말 현재 채권채무의 실재성·완전성 검토를 위한 표본 규모 결정"),
        ("", ""),
        ("[모집단 정보]", ""),
    ]
    for kind_code, label in (("AR", "채권 (AR) 모집단"), ("AP", "채무 (AP) 모집단")):
        pop = state.get("populations", {}).get(kind_code, {})
        items.append((f"  {label} 건수", pop.get("count", 0)))
        items.append((f"  {label} 잔액(KRW)", pop.get("total_krw", 0)))

    items.extend([
        ("", ""),
        ("[표본규모 결정요소]", ""),
        ("수행중요성 (materiality)", materiality),
        ("허용왜곡표시 (tolerable)", tolerable),
        ("Key item 기준금액", tolerable * 0.5),
        ("신뢰수준", "95% (RF 3.0)"),
        ("", ""),
        ("[샘플링 결과]", ""),
    ])

    for kind_code, label in (("AR", "AR 표본"), ("AP", "AP 표본")):
        samp = state.get("samples", {}).get(kind_code, {})
        s_items = samp.get("items", [])
        n_rp = sum(1 for it in s_items if it.get("selection_reason") == "FORCED_RP")
        n_key = sum(1 for it in s_items if it.get("selection_reason") == "FORCED_KEY")
        n_rep = sum(1 for it in s_items if it.get("selection_reason") == "REP")
        items.append((f"  {label} 총 건수", samp.get("count", 0)))
        items.append((f"  {label} 특관자(RP)", n_rp))
        items.append((f"  {label} Key item", n_key))
        items.append((f"  {label} Representative", n_rep))

    for label, val in items:
        c1 = ws.cell(row=row, column=1, value=label)
        c1.font = SUBTITLE_FONT if label.startswith("[") else BODY_FONT
        c1.alignment = TEXT_ALIGN
        if val != "":
            c2 = ws.cell(row=row, column=2, value=val)
            c2.font = BODY_FONT
            if isinstance(val, (int, float)):
                c2.alignment = NUM_ALIGN
                c2.number_format = "#,##0"
            else:
                c2.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_c100_2_keyitem(ws, state, row):
    """C100-2 Key item 추출 — 강제포함 거래처 list (RP + KEY)."""
    headers = ["No", "종류", "거래처코드", "거래처명",
               "잔액(KRW)", "선정사유", "사유 상세"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    forced_items = []
    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        for it in state.get("samples", {}).get(kind_code, {}).get("items", []):
            reason = it.get("selection_reason", "")
            if reason in ("FORCED_RP", "FORCED_KEY"):
                forced_items.append({**it, "kind_label": label, "kind": kind_code})

    forced_items.sort(key=lambda x: -abs(x.get("balance_krw", 0)))

    reason_desc = {
        "FORCED_RP": "특수관계자 (ISA 550 강제포함)",
        "FORCED_KEY": "Key item — 잔액 ≥ 기준금액 (ISA 530)",
    }

    for i, it in enumerate(forced_items, start=1):
        cells = [i, it["kind_label"], it.get("party_id"), it.get("name"),
                 abs(it.get("balance_krw", 0)),
                 it.get("selection_reason"),
                 reason_desc.get(it.get("selection_reason"), "")]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx in (1, 5):
                c.alignment = NUM_ALIGN
                if c_idx == 5:
                    c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_c100_3_mus(ws, state, row):
    """C100-3 Representative MUS 표본 — 누적합산 + 선정 표시."""
    ws.cell(row=row, column=1, value="Representative sample (MUS 방법)").font = SUBTITLE_FONT
    row += 1
    ws.cell(row=row, column=1, value="모집단 중 강제포함 외 REP로 선정된 거래처 목록").font = META_FONT
    row += 2

    headers = ["No", "종류", "거래처코드", "거래처명",
               "잔액(KRW)", "선정사유"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1

    rep_items = []
    for kind_code, label in (("AR", "채권"), ("AP", "채무")):
        for it in state.get("samples", {}).get(kind_code, {}).get("items", []):
            if it.get("selection_reason") == "REP":
                rep_items.append({**it, "kind_label": label, "kind": kind_code})

    rep_items.sort(key=lambda x: -abs(x.get("balance_krw", 0)))

    for i, it in enumerate(rep_items, start=1):
        cells = [i, it["kind_label"], it.get("party_id"), it.get("name"),
                 abs(it.get("balance_krw", 0)), "REP (PPS 추출)"]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx in (1, 5):
                c.alignment = NUM_ALIGN
                if c_idx == 5:
                    c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row
