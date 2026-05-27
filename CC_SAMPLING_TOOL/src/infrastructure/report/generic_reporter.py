"""
generic_reporter.py — 빈 워크북에서 7개 시트를 직접 작성하는 조서 리포터

데이터 출처:
  C100  조회서     — 회사 원장 + UploadGuide 연락처 + PDF 회신 상태
  C100A 주소 적정성 — UploadGuide 연락처 (없으면 빈 표)
  C100-1 표본규모  — SampleSizeResult + SamplingParams
  C100-2 Key item  — CompletenessCheck + PartyDecision + UploadGuide 발송제외
  C100-3 MUS 추출  — MUSResult
  대체적 절차      — AlternativeProcedureEntry (Step 4·5 완료 시)
  샘플링 요약      — 1페이지 핵심 요약

템플릿 복사 없음. openpyxl 직접 스타일링.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side
)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src.domain.mus import MUSResult
from src.domain.population import CompletenessCheck, PartyDecision
from src.domain.sample_size import SampleSizeResult


# ─────────────────────────────────────────────────────────────
# 기대 시트 이름 집합 (채권 기준, 테스트·검증용)
# ─────────────────────────────────────────────────────────────
EXPECTED_GENERIC_SHEETS: set[str] = {
    "샘플링 요약",
    "C100 조회서",
    "C100A 조회처 주소 적정성",
    "C100-1 표본규모 결정",
    "C100-2 Key item 추출",
    "C100-3 표본 추출(MUS)",
    "대체적 절차",
}


# ─────────────────────────────────────────────────────────────
# 색상 상수
# ─────────────────────────────────────────────────────────────
COLOR_HEADER_BG  = "1F4E78"   # 진파랑 헤더 배경
COLOR_HEADER_FG  = "FFFFFF"   # 흰 글씨
COLOR_SUBHEADER  = "2E75B6"   # 중간 파랑 소제목
COLOR_KEY_ITEM   = "FEF3C7"   # 연노랑 Key item
COLOR_SAMPLED    = "C6EFCE"   # 연초록 Representative
COLOR_RELATED    = "FCE4D6"   # 연주황 특관자
COLOR_CONCLUSION_OK     = "D1FAE5"  # 충분
COLOR_CONCLUSION_PARTIAL = "FEF9C3" # 부분
COLOR_CONCLUSION_FAIL    = "FEE2E2" # 미해소
COLOR_ALT_ROW    = "F2F2F2"   # 짝수 행 연회색

FONT_MAIN = "맑은 고딕"


# ─────────────────────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────────────────────

@dataclass
class ReportContext:
    company_name: str
    period_end: date
    kind: str                          # "receivable" | "payable" | "both"
    preparer: str = ""
    reviewer: str = ""
    prep_date: date | None = None
    review_date: date | None = None
    workpaper_no_prefix: str = "C100"


@dataclass
class PartyContactInfo:
    """거래처 연락처 — UploadGuide 또는 수동 입력."""
    name: str
    country: str = ""
    business_no: str = ""
    ceo_name: str = ""
    contact_person: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class ExclusionRow:
    """발송제외 거래처 행 — UploadGuide 발송제외 시트."""
    name: str
    account_name: str = ""
    currency: str = ""
    amount: float = 0.0
    kind: str = ""


@dataclass
class ConfirmationReplyInfo:
    """PDF 회신 결과 요약 — Step 4 완료 시."""
    party_name: str
    status: str           # "matched" | "mismatch" | "needs_review" | "미회신"
    extracted_balance: float | None = None
    reply_date: str | None = None


@dataclass
class AlternativeProcedureEntry:
    """대체적 절차 — Step 5 완료 시."""
    party_name: str
    reason: str
    ledger_balance: float | None
    procedure_type: str
    evidence_names: list[str]
    covered_amount: float | None
    coverage_ratio: float | None
    conclusion: str
    auditor_notes: str | None = None


# ─────────────────────────────────────────────────────────────
# 공통 스타일 헬퍼
# ─────────────────────────────────────────────────────────────

def _font(bold=False, size=9, color="000000", italic=False) -> Font:
    return Font(name=FONT_MAIN, bold=bold, size=size, color=color, italic=italic)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _thin_border() -> Border:
    thin = Side(style="thin", color="BFBFBF")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _center() -> Alignment:
    return Alignment(horizontal="center", vertical="center", wrap_text=True)


def _left() -> Alignment:
    return Alignment(horizontal="left", vertical="center", wrap_text=True)


def _right() -> Alignment:
    return Alignment(horizontal="right", vertical="center")


def _header_cell(ws: Worksheet, row: int, col: int, value: str,
                 span_end_col: int | None = None) -> None:
    """진파랑 배경 + 흰 굵은 글씨 헤더 셀."""
    cell = ws.cell(row, col, value)
    cell.font = _font(bold=True, color=COLOR_HEADER_FG, size=9)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.border = _thin_border()
    cell.alignment = _center()
    if span_end_col:
        ws.merge_cells(
            start_row=row, start_column=col,
            end_row=row, end_column=span_end_col
        )


def _sub_header_cell(ws: Worksheet, row: int, col: int, value: str,
                     span_end_col: int | None = None) -> None:
    """중간 파랑 소제목 셀."""
    cell = ws.cell(row, col, value)
    cell.font = _font(bold=True, color=COLOR_HEADER_FG, size=9)
    cell.fill = _fill(COLOR_SUBHEADER)
    cell.border = _thin_border()
    cell.alignment = _left()
    if span_end_col:
        ws.merge_cells(
            start_row=row, start_column=col,
            end_row=row, end_column=span_end_col
        )


def _label_cell(ws: Worksheet, row: int, col: int, value: str,
                bold=False) -> None:
    cell = ws.cell(row, col, value)
    cell.font = _font(bold=bold, size=9)
    cell.border = _thin_border()
    cell.alignment = _left()


def _data_cell(ws: Worksheet, row: int, col: int, value,
               number_format: str | None = None,
               align: str = "right",
               fill_color: str | None = None) -> None:
    cell = ws.cell(row, col, value)
    cell.font = _font(size=9)
    cell.border = _thin_border()
    if align == "right":
        cell.alignment = _right()
    elif align == "center":
        cell.alignment = _center()
    else:
        cell.alignment = _left()
    if number_format:
        cell.number_format = number_format
    if fill_color:
        cell.fill = _fill(fill_color)


def _amount_cell(ws: Worksheet, row: int, col: int, value: float | None,
                 fill_color: str | None = None) -> None:
    """원화 금액 셀 — 천단위 콤마."""
    _data_cell(ws, row, col, value, number_format="#,##0", fill_color=fill_color)


def _pct_cell(ws: Worksheet, row: int, col: int, value: float | None) -> None:
    """비율 셀 — 소수점 1자리 퍼센트."""
    if value is not None:
        _data_cell(ws, row, col, f"{value*100:.1f}%", align="center")
    else:
        _data_cell(ws, row, col, "", align="center")


def _set_col_width(ws: Worksheet, col: int, width: float) -> None:
    ws.column_dimensions[get_column_letter(col)].width = width


def _meta_row(ws: Worksheet, row: int, label: str, value: str,
              label_col=1, val_col=2, val_span: int | None = None) -> None:
    """메타정보 행 (레이블 + 값)."""
    lc = ws.cell(row, label_col, label)
    lc.font = _font(bold=True, size=9)
    lc.fill = _fill("D6E4F7")
    lc.border = _thin_border()
    lc.alignment = _left()

    vc = ws.cell(row, val_col, value)
    vc.font = _font(size=9)
    vc.border = _thin_border()
    vc.alignment = _left()
    if val_span and val_span > val_col:
        ws.merge_cells(start_row=row, start_column=val_col,
                       end_row=row, end_column=val_span)


# ─────────────────────────────────────────────────────────────
# 메인 진입점
# ─────────────────────────────────────────────────────────────

def build_generic_report(
    out_path: str | Path,
    ctx: ReportContext,
    completeness: CompletenessCheck,
    size_result: SampleSizeResult,
    decisions: list[PartyDecision],
    mus_result: MUSResult,
    performance_materiality: float,
    population_amount: float,
    contacts: list[PartyContactInfo] | None = None,
    exclusion_rows: list[ExclusionRow] | None = None,
    pdf_replies: list[ConfirmationReplyInfo] | None = None,
    alt_procedures: list[AlternativeProcedureEntry] | None = None,
) -> None:
    """빈 워크북에서 7개 시트 직접 작성 — 템플릿 복사 없음."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 기본 Sheet 제거

    prefix = ctx.workpaper_no_prefix  # "C100" or "AA100"

    # 시트 생성 순서 (조서 가독성 기준)
    _build_summary(wb, ctx, size_result, decisions, population_amount,
                   performance_materiality, pdf_replies, alt_procedures)
    _build_c100(wb, ctx, decisions, contacts or [], pdf_replies or [], prefix)
    _build_c100a(wb, ctx, contacts or [])
    _build_c100_1(wb, ctx, size_result, decisions, population_amount,
                  performance_materiality, prefix)
    _build_c100_2(wb, ctx, completeness, size_result, decisions,
                  performance_materiality, exclusion_rows or [], prefix)
    _build_c100_3(wb, ctx, size_result, mus_result, prefix)
    _build_alt_procedures(wb, ctx, alt_procedures or [])

    wb.save(out_path)


# ─────────────────────────────────────────────────────────────
# Sheet 1: 샘플링 요약
# ─────────────────────────────────────────────────────────────

def _build_summary(
    wb, ctx: ReportContext,
    size_result: SampleSizeResult,
    decisions: list[PartyDecision],
    population_amount: float,
    pm: float,
    pdf_replies: list[ConfirmationReplyInfo] | None,
    alt_procedures: list[AlternativeProcedureEntry] | None,
) -> None:
    ws = wb.create_sheet("샘플링 요약")

    # 열 너비
    for c, w in [(1, 28), (2, 18), (3, 18), (4, 18), (5, 18)]:
        _set_col_width(ws, c, w)

    ws.row_dimensions[1].height = 30

    # 제목
    cell = ws.cell(1, 1, "채권채무조회서 샘플링 결과 요약")
    cell.font = _font(bold=True, size=14, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells("A1:E1")

    # 메타정보
    r = 2
    kind_label = {"receivable": "채권", "payable": "채무", "both": "채권+채무"}.get(ctx.kind, ctx.kind)
    prep_date = ctx.prep_date or date.today()
    review_date = ctx.review_date or date.today()
    for label, value in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("조회 구분", kind_label),
        ("작성자", ctx.preparer),
        ("검토자", ctx.reviewer),
        ("작성일", str(prep_date)),
        ("검토일", str(review_date)),
    ]:
        _meta_row(ws, r, label, value, val_span=5)
        r += 1

    r += 1
    # KPI 표 제목
    _sub_header_cell(ws, r, 1, "주요 샘플링 파라미터", span_end_col=5)
    r += 1

    ki = [d for d in decisions if d.is_key_item and not d.is_excluded]
    rep = [d for d in decisions if d.is_representative and not d.is_key_item and not d.is_excluded]
    final = [d for d in decisions if d.final_sampled and not d.is_excluded]

    kpi_rows = [
        ("모집단 금액", population_amount, "#,##0"),
        ("수행중요성 (PM)", pm, "#,##0"),
        ("Key item 기준금액", size_result.key_item_threshold, "#,##0"),
        ("Key item 건수", len(ki), "#,##0"),
        ("Key item 금액", sum(d.balance for d in ki), "#,##0"),
        ("표본간격 (J)", size_result.sample_interval, "#,##0"),
        ("MUS 표본규모", size_result.final_sample_size, "#,##0"),
        ("최종 샘플링 건수 (Key+Rep+특관자)", len(final), "#,##0"),
    ]

    for label, value, fmt in kpi_rows:
        _label_cell(ws, r, 1, label, bold=True)
        _data_cell(ws, r, 2, value, number_format=fmt, align="right")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        r += 1

    # 회수 현황 (Step 4 있을 때만)
    if pdf_replies:
        r += 1
        _sub_header_cell(ws, r, 1, "조회서 회수 현황", span_end_col=5)
        r += 1

        total_sent = len(final)
        replied = [rep for rep in pdf_replies if rep.status not in ("미회신",)]
        matched = [rep for rep in pdf_replies if rep.status == "matched"]
        mismatch = [rep for rep in pdf_replies if rep.status == "mismatch"]
        no_reply = [rep for rep in pdf_replies if rep.status == "미회신"]

        for label, value in [
            ("발송 건수", total_sent),
            ("회신 수령 건수", len(replied)),
            ("일치 건수", len(matched)),
            ("불일치 건수", len(mismatch)),
            ("미회신 건수", len(no_reply)),
        ]:
            _label_cell(ws, r, 1, label, bold=True)
            _data_cell(ws, r, 2, value, number_format="#,##0", align="right")
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
            r += 1

    # 대체적 절차 현황 (Step 5 있을 때만)
    if alt_procedures:
        r += 1
        _sub_header_cell(ws, r, 1, "대체적 절차 현황", span_end_col=5)
        r += 1

        sufficient = sum(1 for p in alt_procedures if p.conclusion == "충분")
        partial    = sum(1 for p in alt_procedures if p.conclusion == "부분")
        unresolved = sum(1 for p in alt_procedures if p.conclusion == "미해소")

        for label, value, fill in [
            ("충분 (커버리지 ≥ 95%)", sufficient, COLOR_CONCLUSION_OK),
            ("부분 (커버리지 50~95%)", partial,    COLOR_CONCLUSION_PARTIAL),
            ("미해소 (커버리지 < 50%)", unresolved, COLOR_CONCLUSION_FAIL),
        ]:
            _label_cell(ws, r, 1, label, bold=True)
            _data_cell(ws, r, 2, value, number_format="#,##0",
                       align="right", fill_color=fill)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
            r += 1


# ─────────────────────────────────────────────────────────────
# Sheet 2: C100 조회서 control sheet
# ─────────────────────────────────────────────────────────────

_AR_ACCOUNTS = ["외상매출금", "받을어음", "미수금", "선급금", "임차보증금", "장기대여금"]
_AP_ACCOUNTS = ["외상매입금", "지급어음(외담대외상매입금)", "미지급금", "임대보증금"]


def _build_c100(
    wb, ctx: ReportContext,
    decisions: list[PartyDecision],
    contacts: list[PartyContactInfo],
    pdf_replies: list[ConfirmationReplyInfo],
    prefix: str,
) -> None:
    sheet_name = f"{prefix} 조회서"
    ws = wb.create_sheet(sheet_name)

    # 열 너비 설정
    widths = {1: 6, 2: 22, 3: 12, 4: 12, 5: 12, 6: 12, 7: 12, 8: 12,
              9: 14, 10: 14, 11: 14, 12: 14, 13: 18, 14: 22, 15: 14}
    for c, w in widths.items():
        _set_col_width(ws, c, w)

    prep_date = ctx.prep_date or date.today()
    review_date = ctx.review_date or date.today()

    # 메타 행
    r = 1
    for label, val in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("작성자", ctx.preparer),
        ("검토자", ctx.reviewer),
        ("작성일", str(prep_date)),
        ("검토일", str(review_date)),
    ]:
        _meta_row(ws, r, label, val, val_span=15)
        r += 1

    r += 1
    # 제목
    cell = ws.cell(r, 1, f"{prefix} 조회서 control sheet")
    cell.font = _font(bold=True, size=11, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=15)
    r += 1

    # 헤더 행 (채권/채무 구분에 따라 컬럼 동적 구성)
    is_ar = ctx.kind in ("receivable", "both")
    is_ap = ctx.kind in ("payable", "both")

    ar_accounts = _AR_ACCOUNTS if is_ar else []
    ap_accounts = _AP_ACCOUNTS if is_ap else []

    # 헤더 그룹: No / 거래처명 / 채권... / 채권계 / 채무... / 채무계 / 합계 / 주소 / 담당자 / 이메일 / 회신상태
    COL_NO    = 1
    COL_NAME  = 2
    col_ar_start = 3
    col_ar_end   = col_ar_start + len(ar_accounts) - 1
    col_ar_sum   = col_ar_end + 1
    col_ap_start = col_ar_sum + 1
    col_ap_end   = col_ap_start + len(ap_accounts) - 1
    col_ap_sum   = col_ap_end + 1
    col_total    = col_ap_sum + 1
    col_contact  = col_total + 1
    col_mgr      = col_contact + 1
    col_email    = col_mgr + 1
    col_reply    = col_email + 1

    # 헤더 행
    _header_cell(ws, r, COL_NO, "No")
    _header_cell(ws, r, COL_NAME, "거래처명")
    for i, acct in enumerate(ar_accounts):
        _header_cell(ws, r, col_ar_start + i, acct)
    if ar_accounts:
        _header_cell(ws, r, col_ar_sum, "채권 계")
    for i, acct in enumerate(ap_accounts):
        _header_cell(ws, r, col_ap_start + i, acct)
    if ap_accounts:
        _header_cell(ws, r, col_ap_sum, "채무 계")
    _header_cell(ws, r, col_total, "합계")
    _header_cell(ws, r, col_contact, "주소/국가")
    _header_cell(ws, r, col_mgr, "담당자")
    _header_cell(ws, r, col_email, "이메일")
    _header_cell(ws, r, col_reply, "회신 상태")
    r += 1

    # 연락처 빠른 조회
    contact_map = {c.name: c for c in contacts}
    reply_map: dict[str, str] = {}
    for rep in pdf_replies:
        reply_map[rep.party_name] = rep.status

    final_parties = sorted(
        [d for d in decisions if d.final_sampled and not d.is_excluded],
        key=lambda d: -d.balance,
    )

    totals_ar: dict[str, float] = {a: 0.0 for a in ar_accounts}
    totals_ap: dict[str, float] = {a: 0.0 for a in ap_accounts}
    grand_total = 0.0

    for seq, d in enumerate(final_parties, 1):
        row_color = COLOR_RELATED if d.is_related_party else (
            COLOR_KEY_ITEM if d.is_key_item else (
                COLOR_SAMPLED if d.is_representative else None
            )
        )

        _data_cell(ws, r, COL_NO, seq, align="center", fill_color=row_color)
        _data_cell(ws, r, COL_NAME, d.name, align="left", fill_color=row_color)

        ar_sum = 0.0
        for i, acct in enumerate(ar_accounts):
            amt = d.by_account.get(acct, 0.0)
            _amount_cell(ws, r, col_ar_start + i, amt or None, fill_color=row_color)
            ar_sum += amt
            totals_ar[acct] = totals_ar.get(acct, 0.0) + amt

        if ar_accounts:
            _amount_cell(ws, r, col_ar_sum, ar_sum or None, fill_color=row_color)

        ap_sum = 0.0
        for i, acct in enumerate(ap_accounts):
            amt = d.by_account.get(acct, 0.0)
            _amount_cell(ws, r, col_ap_start + i, amt or None, fill_color=row_color)
            ap_sum += amt
            totals_ap[acct] = totals_ap.get(acct, 0.0) + amt

        if ap_accounts:
            _amount_cell(ws, r, col_ap_sum, ap_sum or None, fill_color=row_color)

        total_row = ar_sum + ap_sum or d.balance
        _amount_cell(ws, r, col_total, total_row, fill_color=row_color)
        grand_total += total_row

        # 연락처
        ct = contact_map.get(d.name)
        country = ct.country if ct else ""
        mgr = ct.contact_person if ct else ""
        email = ct.email if ct else ""

        _data_cell(ws, r, col_contact, country, align="center", fill_color=row_color)
        _data_cell(ws, r, col_mgr, mgr, align="left", fill_color=row_color)
        _data_cell(ws, r, col_email, email, align="left", fill_color=row_color)

        # 회신 상태
        reply_status = reply_map.get(d.name, "미회신")
        status_label = {
            "matched": "일치",
            "mismatch": "불일치",
            "needs_review": "검토필요",
            "미회신": "미회신",
        }.get(reply_status, reply_status)
        status_fill = {
            "일치":   COLOR_CONCLUSION_OK,
            "불일치": COLOR_CONCLUSION_FAIL,
        }.get(status_label)
        _data_cell(ws, r, col_reply, status_label, align="center",
                   fill_color=status_fill or row_color)
        r += 1

    # 합계 행
    _label_cell(ws, r, COL_NO, "")
    _label_cell(ws, r, COL_NAME, "총합계")
    ws.cell(r, COL_NAME).font = _font(bold=True, size=9)

    for i, acct in enumerate(ar_accounts):
        _amount_cell(ws, r, col_ar_start + i, totals_ar.get(acct) or None)
    if ar_accounts:
        _amount_cell(ws, r, col_ar_sum, sum(totals_ar.values()) or None)
    for i, acct in enumerate(ap_accounts):
        _amount_cell(ws, r, col_ap_start + i, totals_ap.get(acct) or None)
    if ap_accounts:
        _amount_cell(ws, r, col_ap_sum, sum(totals_ap.values()) or None)
    _amount_cell(ws, r, col_total, grand_total or None)


# ─────────────────────────────────────────────────────────────
# Sheet 3: C100A 조회처 주소 적정성
# ─────────────────────────────────────────────────────────────

def _build_c100a(
    wb, ctx: ReportContext,
    contacts: list[PartyContactInfo],
) -> None:
    ws = wb.create_sheet("C100A 조회처 주소 적정성")

    for c, w in [(1, 6), (2, 22), (3, 10), (4, 16), (5, 14),
                 (6, 14), (7, 18), (8, 24), (9, 10), (10, 20)]:
        _set_col_width(ws, c, w)

    prep_date = ctx.prep_date or date.today()
    r = 1
    for label, val in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("작성자", ctx.preparer),
        ("검토자", ctx.reviewer),
        ("작성일", str(prep_date)),
    ]:
        _meta_row(ws, r, label, val, val_span=10)
        r += 1

    r += 1
    cell = ws.cell(r, 1, "C100A 조회처 주소 적정성 확인")
    cell.font = _font(bold=True, size=11, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=10)
    r += 1

    headers = ["No", "거래처명", "국가", "사업자번호", "대표자명",
               "담당자명", "전화번호", "이메일", "주소 적정성", "비고"]
    for i, h in enumerate(headers, 1):
        _header_cell(ws, r, i, h)
    r += 1

    if not contacts:
        _data_cell(ws, r, 1, "", align="center")
        cell = ws.cell(r, 2, "UploadGuide 미제공 — 주소 정보 없음")
        cell.font = _font(italic=True, size=9, color="808080")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
        return

    for seq, ct in enumerate(contacts, 1):
        row_color = COLOR_ALT_ROW if seq % 2 == 0 else None
        _data_cell(ws, r, 1, seq, align="center", fill_color=row_color)
        _data_cell(ws, r, 2, ct.name, align="left", fill_color=row_color)
        _data_cell(ws, r, 3, ct.country, align="center", fill_color=row_color)
        _data_cell(ws, r, 4, ct.business_no, align="left", fill_color=row_color)
        _data_cell(ws, r, 5, ct.ceo_name, align="left", fill_color=row_color)
        _data_cell(ws, r, 6, ct.contact_person, align="left", fill_color=row_color)
        _data_cell(ws, r, 7, ct.phone, align="left", fill_color=row_color)
        _data_cell(ws, r, 8, ct.email, align="left", fill_color=row_color)
        _data_cell(ws, r, 9, "✓" if ct.email or ct.phone else "✗", align="center", fill_color=row_color)
        _data_cell(ws, r, 10, "", align="left", fill_color=row_color)
        r += 1


# ─────────────────────────────────────────────────────────────
# Sheet 4: C100-1 표본규모 결정
# ─────────────────────────────────────────────────────────────

def _build_c100_1(
    wb, ctx: ReportContext,
    size_result: SampleSizeResult,
    decisions: list[PartyDecision],
    population_amount: float,
    pm: float,
    prefix: str,
) -> None:
    ws = wb.create_sheet(f"{prefix}-1 표본규모 결정")

    for c, w in [(1, 32), (2, 18), (3, 18), (4, 18), (5, 18)]:
        _set_col_width(ws, c, w)

    prep_date = ctx.prep_date or date.today()
    r = 1
    for label, val in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("작성자", ctx.preparer),
        ("검토자", ctx.reviewer),
        ("작성일", str(prep_date)),
    ]:
        _meta_row(ws, r, label, val, val_span=5)
        r += 1

    r += 1
    cell = ws.cell(r, 1, f"{prefix}-1 표본규모 결정 (MUS)")
    cell.font = _font(bold=True, size=11, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    r += 1

    # 1. 감사목적
    r += 1
    _sub_header_cell(ws, r, 1, "1. 감사목적", span_end_col=5)
    r += 1
    purpose_text = (
        "본 절차는 감사기준서 505(외부조회)에 따라 채권채무 잔액의 실재성·완전성을 "
        "확인하기 위한 외부 조회 절차입니다. MUS(Monetary Unit Sampling)를 이용하여 "
        "통계적 방법으로 표본을 추출합니다."
    )
    cell = ws.cell(r, 1, purpose_text)
    cell.font = _font(size=9)
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r+1, end_column=5)
    ws.row_dimensions[r].height = 40
    r += 2

    # 2. 조회대상 표본
    r += 1
    _sub_header_cell(ws, r, 1, "2. 조회대상 표본", span_end_col=5)
    r += 1

    ki = [d for d in decisions if d.is_key_item and not d.is_excluded]
    rep = [d for d in decisions if d.is_representative and not d.is_key_item and not d.is_excluded]
    final_all = [d for d in decisions if d.final_sampled and not d.is_excluded]
    ki_amt = sum(d.balance for d in ki)
    rep_amt = sum(d.balance for d in rep)
    total_amt = ki_amt + rep_amt
    total_n = len(ki) + len(rep)

    for c, h in [(1, "구분"), (2, "건수"), (3, "금액"), (4, "Coverage (건수)"), (5, "Coverage (금액)")]:
        _header_cell(ws, r, c, h)
    r += 1

    sample_rows = [
        ("Key item", len(ki), ki_amt,
         len(ki) / len(final_all) if final_all else 0,
         ki_amt / population_amount if population_amount else 0),
        ("Representative (MUS)", len(rep), rep_amt,
         len(rep) / len(final_all) if final_all else 0,
         rep_amt / population_amount if population_amount else 0),
        ("표본 합계", total_n, total_amt,
         total_n / len(final_all) if final_all else 0,
         total_amt / population_amount if population_amount else 0),
        ("모집단", len([d for d in decisions if not d.is_excluded]), population_amount, 1.0, 1.0),
    ]
    for label, n, amt, cov_n, cov_a in sample_rows:
        is_total = label in ("표본 합계", "모집단")
        _label_cell(ws, r, 1, label, bold=is_total)
        _data_cell(ws, r, 2, n, number_format="#,##0", align="center")
        _amount_cell(ws, r, 3, amt)
        _pct_cell(ws, r, 4, cov_n)
        _pct_cell(ws, r, 5, cov_a)
        r += 1

    # 3. 표본규모 결정근거
    r += 1
    _sub_header_cell(ws, r, 1, "3. 표본규모 결정근거", span_end_col=5)
    r += 1

    params_table = [
        ("모집단 금액", population_amount, "#,##0"),
        ("수행중요성 (PM)", pm, "#,##0"),
        ("Key item 기준금액 (PM × {}%)".format(int(size_result.key_item_ratio * 100)),
         size_result.key_item_threshold, "#,##0"),
        ("Key item 금액 (차감)", ki_amt, "#,##0"),
        ("Key item 건수", len(ki), "#,##0"),
        ("Base sample size", size_result.base_sample_size, "#,##0"),
        ("신뢰계수 (CF)", size_result.confidence_factor, "0.00"),
        ("Final sample size", size_result.final_sample_size, "#,##0"),
        ("표본간격 (J)", size_result.sample_interval, "#,##0"),
        ("잔여 모집단", size_result.remaining_population, "#,##0"),
    ]
    for label, val, fmt in params_table:
        _label_cell(ws, r, 1, label, bold=("Final" in label or "Base" in label))
        _data_cell(ws, r, 2, val, number_format=fmt, align="right")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        r += 1


# ─────────────────────────────────────────────────────────────
# Sheet 5: C100-2 Key item 추출
# ─────────────────────────────────────────────────────────────

_AR_GROUP_COLS = {
    "외상매출금": 3, "받을어음": 4, "미수금": 5, "선급금": 6,
    "장기대여금": 7, "임차보증금": 8, "기타보증금": 9,
}
_AP_GROUP_COLS = {
    "외상매입금": 3, "지급어음(외담대외상매입금)": 4, "미지급금": 5,
    "선수금": 6, "임대보증금": 7,
}


def _build_c100_2(
    wb, ctx: ReportContext,
    completeness: CompletenessCheck,
    size_result: SampleSizeResult,
    decisions: list[PartyDecision],
    pm: float,
    exclusion_rows: list[ExclusionRow],
    prefix: str,
) -> None:
    ws = wb.create_sheet(f"{prefix}-2 Key item 추출")

    for c, w in [(1, 4), (2, 22), (3, 14), (4, 14), (5, 14),
                 (6, 14), (7, 14), (8, 14), (9, 14), (10, 16),
                 (11, 10), (12, 8), (13, 8), (14, 8), (15, 8)]:
        _set_col_width(ws, c, w)

    prep_date = ctx.prep_date or date.today()
    r = 1
    for label, val in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("작성자", ctx.preparer),
        ("작성일", str(prep_date)),
    ]:
        _meta_row(ws, r, label, val, val_span=15)
        r += 1

    r += 1
    cell = ws.cell(r, 1, f"{prefix}-2 Key item 추출 (MUS)")
    cell.font = _font(bold=True, size=11, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=15)
    r += 1

    # 1. 모집단 완전성 검토
    r += 1
    _sub_header_cell(ws, r, 1, "1. 모집단 완전성 검토", span_end_col=15)
    r += 1

    for c, h in [(1, "No"), (2, "계정과목그룹"), (3, "회사 명세서"), (4, "재무제표"),
                 (5, "차이"), (6, "비고")]:
        _header_cell(ws, r, c, h)
    ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=15)
    r += 1

    for i, row_data in enumerate(completeness.by_group, 1):
        diff_fill = COLOR_CONCLUSION_FAIL if abs(row_data["diff"]) > 0 else None
        _data_cell(ws, r, 1, i, align="center")
        _label_cell(ws, r, 2, row_data["group"])
        _amount_cell(ws, r, 3, row_data["ledger"])
        _amount_cell(ws, r, 4, row_data["fs"])
        _amount_cell(ws, r, 5, row_data["diff"], fill_color=diff_fill)
        note_cell = ws.cell(r, 6, row_data.get("note", "") or "")
        note_cell.font = _font(size=9)
        note_cell.border = _thin_border()
        note_cell.alignment = _left()
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=15)
        r += 1

    # 합계 행
    _label_cell(ws, r, 2, "합계", bold=True)
    _amount_cell(ws, r, 3, completeness.total_ledger)
    _amount_cell(ws, r, 4, completeness.total_fs)
    diff_color = COLOR_CONCLUSION_FAIL if abs(completeness.total_diff) > 0 else None
    _amount_cell(ws, r, 5, completeness.total_diff, fill_color=diff_color)
    r += 1

    # 2. 발송제외 거래처
    r += 1
    _sub_header_cell(ws, r, 1, "2. 발송제외 거래처", span_end_col=15)
    r += 1

    excl_from_decisions = [d for d in decisions if d.is_excluded]
    all_exclusions: list[tuple[str, str, float]] = []
    for d in excl_from_decisions:
        all_exclusions.append((d.name, d.exclusion_reason or "", d.balance))
    # UploadGuide 발송제외 추가 (중복 제외)
    existing_excl_names = {x[0] for x in all_exclusions}
    for ex in exclusion_rows:
        if ex.name not in existing_excl_names:
            all_exclusions.append((ex.name, "발송대상 제외", ex.amount))

    for c, h in [(1, "No"), (2, "거래처명"), (3, "장부가"), (4, "제외 사유")]:
        _header_cell(ws, r, c, h)
    ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=15)
    r += 1

    if all_exclusions:
        for seq, (name, reason, bal) in enumerate(all_exclusions, 1):
            _data_cell(ws, r, 1, seq, align="center")
            _label_cell(ws, r, 2, name)
            _amount_cell(ws, r, 3, bal)
            note_cell = ws.cell(r, 4, reason)
            note_cell.font = _font(size=9)
            note_cell.border = _thin_border()
            note_cell.alignment = _left()
            ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=15)
            r += 1
    else:
        _data_cell(ws, r, 1, "", align="center")
        cell = ws.cell(r, 2, "발송제외 거래처 없음")
        cell.font = _font(italic=True, size=9, color="808080")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=15)
        r += 1

    # 3. Key item 기준금액
    r += 1
    _sub_header_cell(ws, r, 1, "3. Key item 기준금액", span_end_col=15)
    r += 1

    for label, val, fmt in [
        ("수행중요성 (PM)", pm, "#,##0"),
        ("Key item 비율", size_result.key_item_ratio, "0%"),
        ("Key item 기준금액 (PM × 비율)", size_result.key_item_threshold, "#,##0"),
    ]:
        _label_cell(ws, r, 1, label, bold=True)
        _data_cell(ws, r, 2, val, number_format=fmt, align="right")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=15)
        r += 1

    # 4. 거래처 매트릭스
    r += 1
    _sub_header_cell(ws, r, 1, "4. 거래처별 매트릭스", span_end_col=15)
    r += 1

    is_ar = ctx.kind in ("receivable", "both")
    is_ap = ctx.kind in ("payable", "both")
    group_col_map = {}
    if is_ar:
        group_col_map = dict(_AR_GROUP_COLS)
    if is_ap:
        group_col_map = dict(_AP_GROUP_COLS)

    matrix_headers = [
        (1, "No"), (2, "거래처명"),
    ]
    # 계정 그룹 컬럼
    for g, c in group_col_map.items():
        matrix_headers.append((c, g))
    matrix_headers += [(10, "합계"), (11, "Key item"), (12, "Rep"), (13, "특관자"), (14, "최종선택")]

    for col_idx, label in matrix_headers:
        _header_cell(ws, r, col_idx, label)
    r += 1

    parties = sorted(
        [d for d in decisions if not d.is_excluded and d.balance > 0],
        key=lambda d: d.name,
    )

    totals: dict[str, float] = {}
    for d in parties:
        seq = parties.index(d) + 1
        row_color = (
            COLOR_RELATED if d.is_related_party else
            (COLOR_KEY_ITEM if d.is_key_item else
             (COLOR_SAMPLED if d.is_representative else None))
        )
        _data_cell(ws, r, 1, seq, align="center", fill_color=row_color)
        _data_cell(ws, r, 2, d.name, align="left", fill_color=row_color)

        for g, col in group_col_map.items():
            amt = d.by_account.get(g, 0.0)
            _amount_cell(ws, r, col, amt or None, fill_color=row_color)
            totals[g] = totals.get(g, 0.0) + amt

        _amount_cell(ws, r, 10, d.balance, fill_color=row_color)
        _data_cell(ws, r, 11, "Y" if d.is_key_item else "N", align="center", fill_color=row_color)
        _data_cell(ws, r, 12, "Y" if d.is_representative else "N", align="center", fill_color=row_color)
        _data_cell(ws, r, 13, "Y" if d.is_related_party else "N", align="center", fill_color=row_color)
        _data_cell(ws, r, 14, "Y" if d.final_sampled else "N", align="center", fill_color=row_color)
        r += 1

    # 합계 행
    _label_cell(ws, r, 2, "합계", bold=True)
    for g, col in group_col_map.items():
        _amount_cell(ws, r, col, totals.get(g) or None)
    _amount_cell(ws, r, 10, sum(d.balance for d in parties) or None)
    _data_cell(ws, r, 11, len([d for d in parties if d.is_key_item]), align="center")
    _data_cell(ws, r, 12, len([d for d in parties if d.is_representative]), align="center")
    _data_cell(ws, r, 13, len([d for d in parties if d.is_related_party]), align="center")
    _data_cell(ws, r, 14, len([d for d in parties if d.final_sampled]), align="center")


# ─────────────────────────────────────────────────────────────
# Sheet 6: C100-3 표본 추출 (MUS)
# ─────────────────────────────────────────────────────────────

def _build_c100_3(
    wb, ctx: ReportContext,
    size_result: SampleSizeResult,
    mus_result: MUSResult,
    prefix: str,
) -> None:
    ws = wb.create_sheet(f"{prefix}-3 표본 추출(MUS)")

    for c, w in [(1, 6), (2, 24), (3, 18), (4, 18), (5, 10), (6, 16), (7, 18), (8, 8)]:
        _set_col_width(ws, c, w)

    prep_date = ctx.prep_date or date.today()
    r = 1
    for label, val in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("작성자", ctx.preparer),
        ("작성일", str(prep_date)),
    ]:
        _meta_row(ws, r, label, val, val_span=8)
        r += 1

    r += 1
    cell = ws.cell(r, 1, f"{prefix}-3 표본 추출 (MUS)")
    cell.font = _font(bold=True, size=11, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    r += 1

    # 1. 표본추출방법
    r += 1
    _sub_header_cell(ws, r, 1, "1. 표본추출방법", span_end_col=8)
    r += 1
    method_text = (
        "MUS(Monetary Unit Sampling): 거래금액 단위로 임의 출발점을 설정하고 "
        "표본간격(J)마다 화폐단위를 선택하는 통계적 표본추출 방법 (감사기준서 530)."
    )
    cell = ws.cell(r, 1, method_text)
    cell.font = _font(size=9)
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    ws.row_dimensions[r].height = 30
    r += 1

    # 2. 모수
    r += 1
    _sub_header_cell(ws, r, 1, "2. 표본추출 모수", span_end_col=8)
    r += 1

    for label, val, fmt in [
        ("잔여 모집단 (Key item 제외)", size_result.remaining_population, "#,##0"),
        ("표본규모 (N)", size_result.final_sample_size, "#,##0"),
        ("표본간격 (J)", size_result.sample_interval, "#,##0"),
        ("임의출발점 (r₀)", mus_result.random_start, "#,##0"),
    ]:
        _label_cell(ws, r, 1, label, bold=True)
        _data_cell(ws, r, 2, val, number_format=fmt, align="right")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
        r += 1

    # 3. MUS 추출 내역
    r += 1
    _sub_header_cell(ws, r, 1, "3. Representative sample 추출 내역", span_end_col=8)
    r += 1

    for c, h in [(1, "No"), (2, "거래처명"), (3, "잔액"), (4, "누적금액"),
                 (5, "선택횟수"), (6, "표본간격"), (7, "잔여"), (8, "hit")]:
        _header_cell(ws, r, c, h)
    r += 1

    for i, sel in enumerate(mus_result.selections, 1):
        row_color = COLOR_SAMPLED if sel.hit else None
        _data_cell(ws, r, 1, i, align="center", fill_color=row_color)
        _data_cell(ws, r, 2, sel.name, align="left", fill_color=row_color)
        _amount_cell(ws, r, 3, sel.balance, fill_color=row_color)
        _amount_cell(ws, r, 4, sel.cumulative, fill_color=row_color)
        _data_cell(ws, r, 5, sel.selections, align="center", fill_color=row_color)
        _amount_cell(ws, r, 6, size_result.sample_interval, fill_color=row_color)
        _amount_cell(ws, r, 7, sel.remainder_after, fill_color=row_color)
        _data_cell(ws, r, 8, "Y" if sel.hit else "N", align="center", fill_color=row_color)
        r += 1

    # 합계 행
    _label_cell(ws, r, 2, "합계", bold=True)
    _amount_cell(ws, r, 3, sum(s.balance for s in mus_result.selections))
    _data_cell(ws, r, 5, sum(s.selections for s in mus_result.selections), align="center")


# ─────────────────────────────────────────────────────────────
# Sheet 7: 대체적 절차
# ─────────────────────────────────────────────────────────────

def _build_alt_procedures(
    wb, ctx: ReportContext,
    procedures: list[AlternativeProcedureEntry],
) -> None:
    ws = wb.create_sheet("대체적 절차")

    for c, w in [(1, 6), (2, 22), (3, 10), (4, 16), (5, 14),
                 (6, 24), (7, 18), (8, 12), (9, 10), (10, 24)]:
        _set_col_width(ws, c, w)

    prep_date = ctx.prep_date or date.today()
    r = 1
    for label, val in [
        ("회사명", ctx.company_name),
        ("기준일", str(ctx.period_end)),
        ("작성자", ctx.preparer),
        ("작성일", str(prep_date)),
    ]:
        _meta_row(ws, r, label, val, val_span=10)
        r += 1

    r += 1
    cell = ws.cell(r, 1, "대체적 절차 — 미회신·불일치 거래처")
    cell.font = _font(bold=True, size=11, color=COLOR_HEADER_FG)
    cell.fill = _fill(COLOR_HEADER_BG)
    cell.alignment = _center()
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=10)
    r += 1

    r += 1
    headers = ["No", "거래처명", "사유", "장부가", "절차유형",
               "증빙명세", "커버금액", "커버리지%", "결론", "감사인 메모"]
    for i, h in enumerate(headers, 1):
        _header_cell(ws, r, i, h)
    r += 1

    if not procedures:
        cell = ws.cell(r, 2, "대체적 절차 대상 없음 (Step 5 미완료 또는 전원 일치)")
        cell.font = _font(italic=True, size=9, color="808080")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
        r += 1
    else:
        for i, proc in enumerate(procedures, 1):
            conclusion_fill = {
                "충분": COLOR_CONCLUSION_OK,
                "부분": COLOR_CONCLUSION_PARTIAL,
                "미해소": COLOR_CONCLUSION_FAIL,
            }.get(proc.conclusion, None)

            _data_cell(ws, r, 1, i, align="center")
            _data_cell(ws, r, 2, proc.party_name, align="left")
            _data_cell(ws, r, 3, proc.reason, align="center")
            _amount_cell(ws, r, 4, proc.ledger_balance)
            _data_cell(ws, r, 5, proc.procedure_type, align="center")
            _data_cell(ws, r, 6, "; ".join(proc.evidence_names) if proc.evidence_names else "", align="left")
            _amount_cell(ws, r, 7, proc.covered_amount)
            if proc.coverage_ratio is not None:
                _data_cell(ws, r, 8, f"{proc.coverage_ratio * 100:.1f}%", align="center",
                           fill_color=conclusion_fill)
            else:
                _data_cell(ws, r, 8, "", align="center")
            _data_cell(ws, r, 9, proc.conclusion, align="center", fill_color=conclusion_fill)
            _data_cell(ws, r, 10, proc.auditor_notes or "", align="left")
            r += 1

    # 요약 통계
    r += 1
    _sub_header_cell(ws, r, 1, "집계 요약", span_end_col=10)
    r += 1

    if procedures:
        sufficient = sum(1 for p in procedures if p.conclusion == "충분")
        partial    = sum(1 for p in procedures if p.conclusion == "부분")
        unresolved = sum(1 for p in procedures if p.conclusion == "미해소")
        total_covered = sum(p.covered_amount or 0 for p in procedures)
        total_ledger  = sum(p.ledger_balance or 0 for p in procedures)
        overall_ratio = total_covered / total_ledger if total_ledger > 0 else None

        for label, val, fmt, fill in [
            ("충분 건수", sufficient, "#,##0", COLOR_CONCLUSION_OK),
            ("부분 건수", partial,    "#,##0", COLOR_CONCLUSION_PARTIAL),
            ("미해소 건수", unresolved, "#,##0", COLOR_CONCLUSION_FAIL),
            ("장부가 합계", total_ledger, "#,##0", None),
            ("커버금액 합계", total_covered, "#,##0", None),
        ]:
            _label_cell(ws, r, 1, label, bold=True)
            _data_cell(ws, r, 2, val, number_format=fmt, align="right", fill_color=fill)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
            r += 1

        # 전체 커버리지
        if overall_ratio is not None:
            _label_cell(ws, r, 1, "전체 커버리지", bold=True)
            overall_fill = (COLOR_CONCLUSION_OK if overall_ratio >= 0.95 else
                           (COLOR_CONCLUSION_PARTIAL if overall_ratio >= 0.5 else
                            COLOR_CONCLUSION_FAIL))
            _data_cell(ws, r, 2, f"{overall_ratio * 100:.1f}%", align="right",
                       fill_color=overall_fill)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
            r += 1
