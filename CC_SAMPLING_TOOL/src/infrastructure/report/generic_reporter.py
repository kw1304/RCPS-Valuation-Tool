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

템플릿 복사 없음. openpyxl 직접 스타일링. (7620 양식 준거)
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
# 7620 스타일 상수 (양식 준거)
# ─────────────────────────────────────────────────────────────

FONT_NAME = "맑은 고딕"

# 폰트
FONT_BASE        = Font(name=FONT_NAME, size=10)
FONT_BOLD        = Font(name=FONT_NAME, size=10, bold=True)
FONT_TITLE       = Font(name=FONT_NAME, size=10, bold=True)
FONT_RED_BOLD    = Font(name=FONT_NAME, size=10, bold=True, color="FF0000")
FONT_HEADER_WHITE = Font(name=FONT_NAME, size=10, bold=True, color="FFFFFF")
FONT_GRAY_ITALIC  = Font(name=FONT_NAME, size=10, italic=True, color="808080")

# 채우기
FILL_HEADER_NAVY  = PatternFill("solid", fgColor="44546A")   # 테이블 헤더 navy
FILL_SUBHEADER    = PatternFill("solid", fgColor="D6DCE5")   # 소제목 구분 회청
FILL_INPUT_YELLOW = PatternFill("solid", fgColor="FFFFCC")   # 입력값 강조 연노랑
FILL_KEY_ITEM     = PatternFill("solid", fgColor="FFF2CC")   # Key item 행 연노랑
FILL_SAMPLED      = PatternFill("solid", fgColor="C6EFCE")   # MUS hit 연초록
FILL_EXCLUDED     = PatternFill("solid", fgColor="F4CCCC")   # 발송제외 연빨강
FILL_RELATED      = PatternFill("solid", fgColor="FCE4D6")   # 특관자 연주황
FILL_META_LABEL   = PatternFill("solid", fgColor="D6DCE5")   # 메타 레이블 배경
FILL_TOTAL_ROW    = PatternFill("solid", fgColor="D6DCE5")   # 합계 행
FILL_CONCLUSION_OK      = PatternFill("solid", fgColor="C6EFCE")
FILL_CONCLUSION_PARTIAL = PatternFill("solid", fgColor="FFF2CC")
FILL_CONCLUSION_FAIL    = PatternFill("solid", fgColor="F4CCCC")

# 테두리 — thin #888888
_THIN_SIDE   = Side(style="thin", color="888888")
BORDER_THIN  = Border(
    left=_THIN_SIDE, right=_THIN_SIDE,
    top=_THIN_SIDE, bottom=_THIN_SIDE,
)

# 숫자 포맷
NUMFMT_INT  = '_-* #,##0_-;\\-* #,##0_-;_-* "-"_-;_-@_-'
NUMFMT_DATE = "yyyy-mm-dd"
NUMFMT_PCT  = "0.0%"


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
# 공통 스타일 헬퍼 (7620 준거)
# ─────────────────────────────────────────────────────────────

def _set_col_width(ws: Worksheet, col: int, width: float) -> None:
    ws.column_dimensions[get_column_letter(col)].width = width


def _al(h: str = "left", v: str = "center", wrap: bool = False) -> Alignment:
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _apply(cell, font=None, fill=None, border=None, alignment=None,
           number_format: str | None = None) -> None:
    """한 번에 셀 서식 일괄 적용."""
    if font is not None:
        cell.font = font
    if fill is not None:
        cell.fill = fill
    if border is not None:
        cell.border = border
    if alignment is not None:
        cell.alignment = alignment
    if number_format is not None:
        cell.number_format = number_format


# ── 조서 공통 헤더 블록 (R1~R3) ─────────────────────────────
#
#  A1: 회사명          E1: 작성자:  F1: <이름>  G1: 일자:  H1: <날짜>  I1: 조서번호
#  A2: 시트제목(bold)  E2: 검토자:  F2: <이름>  G2: 일자:  H2: <날짜>  I2: <번호 빨강>
#  A3: 기준일: <날짜>

def _write_doc_header(
    ws: Worksheet,
    company: str,
    title: str,
    period_end: date,
    preparer: str,
    reviewer: str,
    prep_date: date,
    review_date: date,
    wp_no: str,                   # 예: "C100-1"  (빨강)
    last_col: int = 9,
) -> None:
    """7620 표준 조서 헤더 R1~R3 작성."""
    # 행 높이
    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 6   # 구분 여백

    # A1: 회사명
    c = ws.cell(1, 1, company)
    _apply(c, font=FONT_BASE, border=BORDER_THIN, alignment=_al("left"))

    # A2: 시트 제목
    c = ws.cell(2, 1, title)
    _apply(c, font=FONT_BOLD, border=BORDER_THIN, alignment=_al("left"))

    # A3: 기준일
    c = ws.cell(3, 1, period_end)
    _apply(c, font=FONT_BASE, border=BORDER_THIN,
           alignment=_al("left"), number_format=NUMFMT_DATE)

    # E1·E2 라벨
    for row, label in ((1, "작성자:"), (2, "검토자:")):
        c = ws.cell(row, 5, label)
        _apply(c, font=FONT_BASE, border=BORDER_THIN, alignment=_al("right"))

    # F1·F2 이름
    f1 = ws.cell(1, 6, preparer)
    _apply(f1, font=FONT_BASE, border=BORDER_THIN, alignment=_al("left"))
    f2 = ws.cell(2, 6, reviewer)
    _apply(f2, font=FONT_BASE, border=BORDER_THIN, alignment=_al("left"))

    # G1·G2 일자 라벨
    for row in (1, 2):
        c = ws.cell(row, 7, "일자:")
        _apply(c, font=FONT_BASE, border=BORDER_THIN, alignment=_al("right"))

    # H1·H2 날짜
    h1 = ws.cell(1, 8, prep_date)
    _apply(h1, font=FONT_BASE, border=BORDER_THIN,
           alignment=_al("center"), number_format=NUMFMT_DATE)
    h2 = ws.cell(2, 8, review_date)
    _apply(h2, font=FONT_BASE, border=BORDER_THIN,
           alignment=_al("center"), number_format=NUMFMT_DATE)

    # I1: "조서번호" 라벨
    c = ws.cell(1, 9, "조서번호")
    _apply(c, font=FONT_BASE, border=BORDER_THIN, alignment=_al("center"))

    # I2: 조서번호 값 (빨강 bold)
    c = ws.cell(2, 9, wp_no)
    _apply(c, font=FONT_RED_BOLD, border=BORDER_THIN, alignment=_al("center"))

    # 빈 셀 테두리 채우기 (A1~D3, B3, C3, D3)
    for row in range(1, 4):
        for col in range(2, 5):
            c = ws.cell(row, col)
            if not c.value:
                _apply(c, font=FONT_BASE, border=BORDER_THIN, alignment=_al("left"))

    # A3 이후 빈 셀 (B3~I3)
    for col in range(2, last_col + 1):
        c = ws.cell(3, col)
        if not c.value:
            _apply(c, font=FONT_BASE, border=BORDER_THIN, alignment=_al("left"))


# ── 소제목 행 ─────────────────────────────────────────────────
def _subheader_row(ws: Worksheet, row: int, text: str,
                   col_start: int = 1, col_end: int = 9) -> None:
    """D6DCE5 배경 소제목 행 (7620 감사목적 등 구분선)."""
    c = ws.cell(row, col_start, text)
    _apply(c, font=FONT_BOLD, fill=FILL_SUBHEADER,
           border=BORDER_THIN, alignment=_al("left"))
    if col_end > col_start:
        ws.merge_cells(start_row=row, start_column=col_start,
                       end_row=row, end_column=col_end)
    ws.row_dimensions[row].height = 18


# ── 테이블 헤더 행 ────────────────────────────────────────────
def _header_cell(ws: Worksheet, row: int, col: int, text: str,
                 col_end: int | None = None) -> None:
    """44546A navy 배경 + 흰 글씨 헤더 셀."""
    c = ws.cell(row, col, text)
    _apply(c, font=FONT_HEADER_WHITE, fill=FILL_HEADER_NAVY,
           border=BORDER_THIN, alignment=_al("center", wrap=True))
    if col_end and col_end > col:
        ws.merge_cells(start_row=row, start_column=col,
                       end_row=row, end_column=col_end)
    ws.row_dimensions[row].height = 20


# ── 데이터 셀 헬퍼 ────────────────────────────────────────────
def _text_cell(ws: Worksheet, row: int, col: int, value,
               bold: bool = False, fill: PatternFill | None = None,
               align: str = "left") -> None:
    c = ws.cell(row, col, value)
    _apply(c, font=FONT_BOLD if bold else FONT_BASE,
           fill=fill, border=BORDER_THIN, alignment=_al(align))
    ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 0, 16)


def _num_cell(ws: Worksheet, row: int, col: int, value,
              fill: PatternFill | None = None,
              fmt: str = NUMFMT_INT) -> None:
    c = ws.cell(row, col, value)
    _apply(c, font=FONT_BASE, fill=fill, border=BORDER_THIN,
           alignment=_al("right"), number_format=fmt)
    ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 0, 16)


def _pct_cell(ws: Worksheet, row: int, col: int, value: float | None,
              fill: PatternFill | None = None) -> None:
    if value is not None:
        c = ws.cell(row, col, value)
        _apply(c, font=FONT_BASE, fill=fill, border=BORDER_THIN,
               alignment=_al("center"), number_format=NUMFMT_PCT)
    else:
        _text_cell(ws, row, col, "", fill=fill, align="center")


def _total_row_cell(ws: Worksheet, row: int, col: int, value,
                    is_num: bool = False, fmt: str = NUMFMT_INT) -> None:
    """합계 행 셀 — FILL_SUBHEADER + FONT_BOLD."""
    c = ws.cell(row, col, value)
    _apply(c, font=FONT_BOLD, fill=FILL_TOTAL_ROW, border=BORDER_THIN,
           alignment=_al("right" if is_num else "left"),
           number_format=fmt if is_num else None)
    ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 0, 16)


def _input_cell(ws: Worksheet, row: int, col: int, value,
                fmt: str = NUMFMT_INT) -> None:
    """입력값 강조 셀 (PM, 기준금액 등) — FILL_INPUT_YELLOW."""
    c = ws.cell(row, col, value)
    _apply(c, font=FONT_BASE, fill=FILL_INPUT_YELLOW, border=BORDER_THIN,
           alignment=_al("right"), number_format=fmt)


# ── 행 색상 결정 ──────────────────────────────────────────────
def _party_fill(d: PartyDecision) -> PatternFill | None:
    if d.is_related_party:
        return FILL_RELATED
    if d.is_key_item:
        return FILL_KEY_ITEM
    if d.is_representative:
        return FILL_SAMPLED
    return None


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


@dataclass
class KindData:
    """채권/채무 한쪽에 필요한 모든 데이터 묶음."""
    ctx: ReportContext
    completeness: CompletenessCheck
    size_result: SampleSizeResult
    decisions: list[PartyDecision]
    mus_result: MUSResult
    performance_materiality: float
    population_amount: float
    contacts: list[PartyContactInfo] | None = None
    exclusion_rows: list[ExclusionRow] | None = None
    pdf_replies: list[ConfirmationReplyInfo] | None = None
    alt_procedures: list[AlternativeProcedureEntry] | None = None


def build_combined_report(
    out_path: str | Path,
    receivable: KindData | None,
    payable: KindData | None,
) -> None:
    """채권+채무 단일 워크북에 통합 출력.

    시트 구성 (최대 11개):
      1. 샘플링 요약
      2. C100 조회서
      3. C100-1 표본규모 결정
      4. C100-2 Key item 추출
      5. C100-3 표본 추출(MUS)
      6. AA100 조회서
      7. AA100-1 표본규모 결정
      8. AA100-2 Key item 추출
      9. AA100-3 표본 추출(MUS)
     10. C100A 조회처 주소 적정성
     11. 대체적 절차
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    base_ctx = (receivable or payable).ctx
    combined_decisions: list[PartyDecision] = []
    combined_contacts: list[PartyContactInfo] = []
    combined_pdf_replies: list[ConfirmationReplyInfo] = []
    combined_alt_procs: list[AlternativeProcedureEntry] = []
    total_pop = 0.0

    for kd in (receivable, payable):
        if kd is None:
            continue
        combined_decisions.extend(kd.decisions)
        if kd.contacts:
            combined_contacts.extend(kd.contacts)
        if kd.pdf_replies:
            combined_pdf_replies.extend(kd.pdf_replies)
        if kd.alt_procedures:
            combined_alt_procs.extend(kd.alt_procedures)
        total_pop += kd.population_amount

    rep_size = (receivable or payable).size_result
    rep_pm   = (receivable or payable).performance_materiality
    summary_ctx = ReportContext(
        company_name=base_ctx.company_name,
        period_end=base_ctx.period_end,
        kind="both",
        preparer=base_ctx.preparer,
        reviewer=base_ctx.reviewer,
        workpaper_no_prefix="",
    )
    _build_summary(
        wb, summary_ctx, rep_size, combined_decisions,
        total_pop, rep_pm, combined_pdf_replies, combined_alt_procs,
    )

    # 채권 시트들
    if receivable:
        kd = receivable
        _build_c100(wb, kd.ctx, kd.decisions, kd.contacts or [], kd.pdf_replies or [], "C100")
        _build_c100_1(wb, kd.ctx, kd.size_result, kd.decisions,
                      kd.population_amount, kd.performance_materiality, "C100")
        _build_c100_2(wb, kd.ctx, kd.completeness, kd.size_result, kd.decisions,
                      kd.performance_materiality, kd.exclusion_rows or [], "C100")
        _build_c100_3(wb, kd.ctx, kd.size_result, kd.mus_result, "C100")

    # 채무 시트들
    if payable:
        kd = payable
        _build_c100(wb, kd.ctx, kd.decisions, kd.contacts or [], kd.pdf_replies or [], "AA100")
        _build_c100_1(wb, kd.ctx, kd.size_result, kd.decisions,
                      kd.population_amount, kd.performance_materiality, "AA100")
        _build_c100_2(wb, kd.ctx, kd.completeness, kd.size_result, kd.decisions,
                      kd.performance_materiality, kd.exclusion_rows or [], "AA100")
        _build_c100_3(wb, kd.ctx, kd.size_result, kd.mus_result, "AA100")

    # C100A + 대체적 절차 — 양쪽 통합 단 1번
    _build_c100a(wb, summary_ctx, combined_contacts)
    _build_alt_procedures(wb, summary_ctx, combined_alt_procs)

    # 시트 순서 재정렬
    desired_order = [
        "샘플링 요약",
        "C100 조회서", "C100-1 표본규모 결정", "C100-2 Key item 추출", "C100-3 표본 추출(MUS)",
        "AA100 조회서", "AA100-1 표본규모 결정", "AA100-2 Key item 추출", "AA100-3 표본 추출(MUS)",
        "C100A 조회처 주소 적정성",
        "대체적 절차",
    ]
    new_order = [s for s in desired_order if s in wb.sheetnames]
    for idx, name in enumerate(new_order):
        cur_idx = wb.sheetnames.index(name)
        wb.move_sheet(name, offset=idx - cur_idx)

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

    # 컬럼 너비
    for col, w in [(1, 30), (2, 18), (3, 18), (4, 18), (5, 18),
                   (6, 12), (7, 12), (8, 14), (9, 14)]:
        _set_col_width(ws, col, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    # 조서 헤더 (R1~R4)
    kind_label = {"receivable": "채권 조회", "payable": "채무 조회",
                  "both": "채권채무 조회 통합"}.get(ctx.kind, ctx.kind)
    _write_doc_header(
        ws, ctx.company_name, f"샘플링 결과 요약 — {kind_label}",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no="요약",
    )

    r = 5  # R5~: 본문

    # 1. 핵심 KPI
    _subheader_row(ws, r, "1. 핵심 샘플링 파라미터", col_end=9)
    r += 1

    ki    = [d for d in decisions if d.is_key_item and not d.is_excluded]
    rep_d = [d for d in decisions if d.is_representative and not d.is_key_item and not d.is_excluded]
    final = [d for d in decisions if d.final_sampled and not d.is_excluded]
    ki_amt  = sum(d.balance for d in ki)
    rep_amt = sum(d.balance for d in rep_d)

    # 헤더
    for col, h in [(1, "항목"), (2, "값")]:
        _header_cell(ws, r, col, h, col_end=None)
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
    r += 1

    kpi_rows = [
        ("모집단 금액",                       population_amount),
        ("수행중요성 (PM)",                    pm),
        ("Key item 기준금액",                 size_result.key_item_threshold),
        ("Key item 건수",                     len(ki)),
        ("Key item 금액",                     ki_amt),
        ("표본간격 (J)",                      size_result.sample_interval),
        ("MUS 표본규모",                      size_result.final_sample_size),
        ("최종 샘플링 건수 (Key+Rep+특관자)", len(final)),
    ]
    for label, value in kpi_rows:
        _text_cell(ws, r, 1, label, bold=True)
        is_pm_or_key = label in ("수행중요성 (PM)", "Key item 기준금액")
        if is_pm_or_key:
            _input_cell(ws, r, 2, value)
        else:
            _num_cell(ws, r, 2, value)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
        r += 1

    # 2. 조회서 회수 현황 (Step 4)
    if pdf_replies:
        r += 1
        _subheader_row(ws, r, "2. 조회서 회수 현황", col_end=9)
        r += 1

        total_sent = len(final)
        replied    = [x for x in pdf_replies if x.status not in ("미회신",)]
        matched    = [x for x in pdf_replies if x.status == "matched"]
        mismatch   = [x for x in pdf_replies if x.status == "mismatch"]
        no_reply   = [x for x in pdf_replies if x.status == "미회신"]

        for col, h in [(1, "항목"), (2, "건수")]:
            _header_cell(ws, r, col, h)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
        r += 1

        for label, value in [
            ("발송 건수", total_sent),
            ("회신 수령 건수", len(replied)),
            ("일치 건수",  len(matched)),
            ("불일치 건수", len(mismatch)),
            ("미회신 건수", len(no_reply)),
        ]:
            _text_cell(ws, r, 1, label, bold=True)
            _num_cell(ws, r, 2, value)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
            r += 1

    # 3. 대체적 절차 현황 (Step 5)
    if alt_procedures:
        r += 1
        _subheader_row(ws, r, "3. 대체적 절차 현황", col_end=9)
        r += 1

        sufficient = sum(1 for p in alt_procedures if p.conclusion == "충분")
        partial    = sum(1 for p in alt_procedures if p.conclusion == "부분")
        unresolved = sum(1 for p in alt_procedures if p.conclusion == "미해소")

        for col, h in [(1, "결론"), (2, "건수")]:
            _header_cell(ws, r, col, h)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
        r += 1

        for label, value, fill in [
            ("충분 (커버리지 ≥ 95%)", sufficient, FILL_CONCLUSION_OK),
            ("부분 (커버리지 50~95%)", partial,    FILL_CONCLUSION_PARTIAL),
            ("미해소 (커버리지 < 50%)", unresolved, FILL_CONCLUSION_FAIL),
        ]:
            _text_cell(ws, r, 1, label, bold=True)
            _num_cell(ws, r, 2, value, fill=fill)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=9)
            r += 1


# ─────────────────────────────────────────────────────────────
# Sheet 2: C100 / AA100 조회서 (control sheet)
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

    # 컬럼 너비 — 7620 Control sheet 기준
    col_widths = {1: 4.0, 2: 33.85, 3: 13.0, 4: 13.0, 5: 13.0,
                  6: 13.0, 7: 13.0, 8: 13.0, 9: 13.0, 10: 13.0,
                  11: 13.0, 12: 13.0, 13: 16.0, 14: 13.0, 15: 14.0}
    for c, w in col_widths.items():
        _set_col_width(ws, c, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    # 조서 헤더
    _write_doc_header(
        ws, ctx.company_name, f"{prefix} 조회서",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no=f"{prefix}",
        last_col=15,
    )

    r = 5
    # 소제목
    _subheader_row(ws, r, "조회서 control sheet — 발송 거래처 목록", col_end=15)
    r += 1

    # 헤더 행 구성 (계정 컬럼 동적)
    is_ar = prefix == "C100"
    ar_accounts = _AR_ACCOUNTS if is_ar else []
    ap_accounts = _AP_ACCOUNTS if not is_ar else []

    COL_NO   = 1
    COL_NAME = 2
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

    _header_cell(ws, r, COL_NO,   "No")
    _header_cell(ws, r, COL_NAME, "거래처명")
    for i, acct in enumerate(ar_accounts):
        _header_cell(ws, r, col_ar_start + i, acct)
    if ar_accounts:
        _header_cell(ws, r, col_ar_sum, "채권 계")
    for i, acct in enumerate(ap_accounts):
        _header_cell(ws, r, col_ap_start + i, acct)
    if ap_accounts:
        _header_cell(ws, r, col_ap_sum, "채무 계")
    _header_cell(ws, r, col_total,   "합계")
    _header_cell(ws, r, col_contact, "주소/국가")
    _header_cell(ws, r, col_mgr,     "담당자")
    _header_cell(ws, r, col_email,   "이메일")
    _header_cell(ws, r, col_reply,   "회신 상태")
    r += 1

    contact_map = {c.name: c for c in contacts}
    reply_map   = {rep.party_name: rep.status for rep in pdf_replies}

    final_parties = sorted(
        [d for d in decisions if d.final_sampled and not d.is_excluded],
        key=lambda d: -d.balance,
    )

    totals_ar: dict[str, float] = {a: 0.0 for a in ar_accounts}
    totals_ap: dict[str, float] = {a: 0.0 for a in ap_accounts}
    grand_total = 0.0

    for seq, d in enumerate(final_parties, 1):
        fill = _party_fill(d)

        _text_cell(ws, r, COL_NO,   seq,    fill=fill, align="center")
        _text_cell(ws, r, COL_NAME, d.name, fill=fill, align="left")

        ar_sum = 0.0
        for i, acct in enumerate(ar_accounts):
            amt = d.by_account.get(acct, 0.0)
            if amt:
                _num_cell(ws, r, col_ar_start + i, amt, fill=fill)
            else:
                _text_cell(ws, r, col_ar_start + i, "", fill=fill, align="right")
            ar_sum += amt
            totals_ar[acct] = totals_ar.get(acct, 0.0) + amt

        if ar_accounts:
            _num_cell(ws, r, col_ar_sum, ar_sum or None, fill=fill)

        ap_sum = 0.0
        for i, acct in enumerate(ap_accounts):
            amt = d.by_account.get(acct, 0.0)
            if amt:
                _num_cell(ws, r, col_ap_start + i, amt, fill=fill)
            else:
                _text_cell(ws, r, col_ap_start + i, "", fill=fill, align="right")
            ap_sum += amt
            totals_ap[acct] = totals_ap.get(acct, 0.0) + amt

        if ap_accounts:
            _num_cell(ws, r, col_ap_sum, ap_sum or None, fill=fill)

        total_row = ar_sum + ap_sum or d.balance
        _num_cell(ws, r, col_total, total_row, fill=fill)
        grand_total += total_row

        ct = contact_map.get(d.name)
        _text_cell(ws, r, col_contact, ct.country        if ct else "", fill=fill, align="center")
        _text_cell(ws, r, col_mgr,     ct.contact_person if ct else "", fill=fill, align="left")
        _text_cell(ws, r, col_email,   ct.email          if ct else "", fill=fill, align="left")

        status_raw = reply_map.get(d.name, "미회신")
        status_label = {
            "matched": "일치", "mismatch": "불일치",
            "needs_review": "검토필요", "미회신": "미회신",
        }.get(status_raw, status_raw)
        status_fill = {
            "일치":   FILL_CONCLUSION_OK,
            "불일치": FILL_CONCLUSION_FAIL,
        }.get(status_label)
        _text_cell(ws, r, col_reply, status_label, fill=status_fill or fill, align="center")
        r += 1

    # 합계 행
    _total_row_cell(ws, r, COL_NO,   "")
    _total_row_cell(ws, r, COL_NAME, "총합계")
    for i, acct in enumerate(ar_accounts):
        _total_row_cell(ws, r, col_ar_start + i, totals_ar.get(acct) or None, is_num=True)
    if ar_accounts:
        _total_row_cell(ws, r, col_ar_sum, sum(totals_ar.values()) or None, is_num=True)
    for i, acct in enumerate(ap_accounts):
        _total_row_cell(ws, r, col_ap_start + i, totals_ap.get(acct) or None, is_num=True)
    if ap_accounts:
        _total_row_cell(ws, r, col_ap_sum, sum(totals_ap.values()) or None, is_num=True)
    _total_row_cell(ws, r, col_total, grand_total or None, is_num=True)


# ─────────────────────────────────────────────────────────────
# Sheet 3: C100A 조회처 주소 적정성
# ─────────────────────────────────────────────────────────────

def _build_c100a(
    wb, ctx: ReportContext,
    contacts: list[PartyContactInfo],
) -> None:
    ws = wb.create_sheet("C100A 조회처 주소 적정성")

    for c, w in [(1, 4.0), (2, 33.85), (3, 10.0), (4, 16.0), (5, 13.0),
                 (6, 13.0), (7, 16.0), (8, 24.0), (9, 10.0), (10, 20.0)]:
        _set_col_width(ws, c, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    _write_doc_header(
        ws, ctx.company_name, "C100A 조회처 주소 적정성 확인",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no="C100A",
        last_col=10,
    )

    r = 5
    _subheader_row(ws, r, "조회서 발송 주소·연락처 적정성 검토", col_end=10)
    r += 1

    headers = ["No", "거래처명", "국가", "사업자번호", "대표자명",
               "담당자명", "전화번호", "이메일", "주소 적정성", "비고"]
    for i, h in enumerate(headers, 1):
        _header_cell(ws, r, i, h)
    r += 1

    if not contacts:
        c_cell = ws.cell(r, 2, "UploadGuide 미제공 — 주소 정보 없음")
        _apply(c_cell, font=FONT_GRAY_ITALIC, border=BORDER_THIN, alignment=_al("left"))
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
        return

    for seq, ct in enumerate(contacts, 1):
        _text_cell(ws, r, 1, seq,              align="center")
        _text_cell(ws, r, 2, ct.name,          align="left")
        _text_cell(ws, r, 3, ct.country,       align="center")
        _text_cell(ws, r, 4, ct.business_no,   align="left")
        _text_cell(ws, r, 5, ct.ceo_name,      align="left")
        _text_cell(ws, r, 6, ct.contact_person, align="left")
        _text_cell(ws, r, 7, ct.phone,         align="left")
        _text_cell(ws, r, 8, ct.email,         align="left")
        ok = "Y" if (ct.email or ct.phone) else "N"
        fill_ok = FILL_SAMPLED if ok == "Y" else FILL_EXCLUDED
        _text_cell(ws, r, 9, ok, fill=fill_ok, align="center")
        _text_cell(ws, r, 10, "", align="left")
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

    # 컬럼 너비 — 7620 C100-1 기준
    for c, w in [(1, 33.85), (2, 19.28), (3, 16.71), (4, 13.0), (5, 13.0)]:
        _set_col_width(ws, c, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    _write_doc_header(
        ws, ctx.company_name, f"{prefix}-1 표본규모 결정 (MUS)",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no=f"{prefix}-1",
    )

    r = 5

    # 1. 감사목적
    _subheader_row(ws, r, "1. 감사목적", col_end=5)
    r += 1
    purpose_text = (
        "본 절차는 감사기준서 505(외부조회)에 따라 채권채무 잔액의 실재성·완전성을 "
        "확인하기 위한 외부 조회 절차입니다. MUS(Monetary Unit Sampling)를 이용하여 "
        "통계적 방법으로 표본을 추출합니다."
    )
    c = ws.cell(r, 1, purpose_text)
    _apply(c, font=FONT_BASE, border=BORDER_THIN,
           alignment=Alignment(horizontal="left", vertical="top", wrap_text=True))
    ws.merge_cells(start_row=r, start_column=1, end_row=r + 1, end_column=5)
    ws.row_dimensions[r].height = 40
    r += 2

    # 2. 조회대상 표본
    r += 1
    _subheader_row(ws, r, "2. 조회대상 표본", col_end=5)
    r += 1

    ki    = [d for d in decisions if d.is_key_item and not d.is_excluded]
    rep_d = [d for d in decisions if d.is_representative and not d.is_key_item and not d.is_excluded]
    final_all = [d for d in decisions if d.final_sampled and not d.is_excluded]
    ki_amt  = sum(d.balance for d in ki)
    rep_amt = sum(d.balance for d in rep_d)
    total_amt = ki_amt + rep_amt
    total_n   = len(ki) + len(rep_d)

    for c_idx, h in enumerate(["구분", "건수", "금액", "Coverage (건수)", "Coverage (금액)"], 1):
        _header_cell(ws, r, c_idx, h)
    r += 1

    sample_rows = [
        ("Key item",          len(ki),   ki_amt,
         len(ki)   / len(final_all) if final_all else 0,
         ki_amt   / population_amount if population_amount else 0),
        ("Representative (MUS)", len(rep_d), rep_amt,
         len(rep_d) / len(final_all) if final_all else 0,
         rep_amt  / population_amount if population_amount else 0),
        ("표본 합계",         total_n,  total_amt,
         total_n  / len(final_all) if final_all else 0,
         total_amt / population_amount if population_amount else 0),
        ("모집단",            len([d for d in decisions if not d.is_excluded]),
         population_amount, 1.0, 1.0),
    ]
    for label, n, amt, cov_n, cov_a in sample_rows:
        is_total = label in ("표본 합계", "모집단")
        _text_cell(ws, r, 1, label, bold=is_total)
        _num_cell(ws, r, 2, n)
        _num_cell(ws, r, 3, amt)
        _pct_cell(ws, r, 4, cov_n)
        _pct_cell(ws, r, 5, cov_a)
        if is_total:
            for col in range(1, 6):
                ws.cell(r, col).font = FONT_BOLD
                ws.cell(r, col).fill = FILL_TOTAL_ROW
        r += 1

    # 3. 표본규모 결정근거
    r += 1
    _subheader_row(ws, r, "3. 표본규모 결정근거", col_end=5)
    r += 1

    params = [
        ("모집단 금액",                                     population_amount, NUMFMT_INT, False),
        ("수행중요성 (PM)",                                 pm,                NUMFMT_INT, True),
        ("Key item 기준금액 (PM × {}%)".format(
            int(size_result.key_item_ratio * 100)),         size_result.key_item_threshold, NUMFMT_INT, True),
        ("Key item 금액 (차감)",                            ki_amt,            NUMFMT_INT, False),
        ("Key item 건수",                                   len(ki),           NUMFMT_INT, False),
        ("Base sample size",                                size_result.base_sample_size, NUMFMT_INT, False),
        ("신뢰계수 (CF)",                                   size_result.confidence_factor, "0.00", False),
        ("Final sample size",                               size_result.final_sample_size, NUMFMT_INT, False),
        ("표본간격 (J)",                                    size_result.sample_interval,   NUMFMT_INT, False),
        ("잔여 모집단",                                     size_result.remaining_population, NUMFMT_INT, False),
    ]
    for label, val, fmt, is_input in params:
        _text_cell(ws, r, 1, label,
                   bold=("Final" in label or "Base" in label))
        if is_input:
            _input_cell(ws, r, 2, val, fmt=fmt)
        else:
            _num_cell(ws, r, 2, val, fmt=fmt)
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

    for c, w in [(1, 2.7), (2, 33.85), (3, 19.28), (4, 16.71), (5, 13.0),
                 (6, 13.0), (7, 13.0), (8, 13.0), (9, 13.0), (10, 13.0),
                 (11, 10.0), (12, 8.0), (13, 8.0), (14, 8.0), (15, 8.0)]:
        _set_col_width(ws, c, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    _write_doc_header(
        ws, ctx.company_name, f"{prefix}-2 Key item 추출 (MUS)",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no=f"{prefix}-2",
        last_col=15,
    )

    r = 5

    # 1. 모집단 완전성 검토
    _subheader_row(ws, r, "1. 모집단 완전성 검토", col_end=15)
    r += 1

    for c_idx, h in enumerate(["No", "계정과목그룹", "회사 명세서", "재무제표", "차이", "비고"], 1):
        _header_cell(ws, r, c_idx, h, col_end=15 if c_idx == 6 else None)
    r += 1

    for i, row_data in enumerate(completeness.by_group, 1):
        diff_fill = FILL_EXCLUDED if abs(row_data["diff"]) > 0 else None
        _text_cell(ws, r, 1, i, align="center")
        _text_cell(ws, r, 2, row_data["group"])
        _num_cell(ws, r, 3, row_data["ledger"])
        _num_cell(ws, r, 4, row_data["fs"])
        _num_cell(ws, r, 5, row_data["diff"], fill=diff_fill)
        note = ws.cell(r, 6, row_data.get("note", "") or "")
        _apply(note, font=FONT_BASE, border=BORDER_THIN, alignment=_al("left"))
        ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=15)
        r += 1

    # 합계 행
    _total_row_cell(ws, r, 2, "합계")
    _total_row_cell(ws, r, 3, completeness.total_ledger, is_num=True)
    _total_row_cell(ws, r, 4, completeness.total_fs,     is_num=True)
    diff_color = FILL_EXCLUDED if abs(completeness.total_diff) > 0 else FILL_TOTAL_ROW
    c_diff = ws.cell(r, 5, completeness.total_diff)
    _apply(c_diff, font=FONT_BOLD, fill=diff_color, border=BORDER_THIN,
           alignment=_al("right"), number_format=NUMFMT_INT)
    r += 1

    # 2. 발송제외 거래처
    r += 1
    _subheader_row(ws, r, "2. 발송제외 거래처", col_end=15)
    r += 1

    excl_from_dec = [d for d in decisions if d.is_excluded]
    all_exclusions: list[tuple[str, str, float]] = []
    for d in excl_from_dec:
        all_exclusions.append((d.name, d.exclusion_reason or "", d.balance))
    existing_names = {x[0] for x in all_exclusions}
    for ex in exclusion_rows:
        if ex.name not in existing_names:
            all_exclusions.append((ex.name, "발송대상 제외", ex.amount))

    for c_idx, h in enumerate(["No", "거래처명", "장부가", "제외 사유"], 1):
        _header_cell(ws, r, c_idx, h, col_end=15 if c_idx == 4 else None)
    r += 1

    if all_exclusions:
        for seq, (name, reason, bal) in enumerate(all_exclusions, 1):
            _text_cell(ws, r, 1, seq, align="center", fill=FILL_EXCLUDED)
            _text_cell(ws, r, 2, name, fill=FILL_EXCLUDED, align="left")
            _num_cell(ws, r, 3, bal, fill=FILL_EXCLUDED)
            note_c = ws.cell(r, 4, reason)
            _apply(note_c, font=FONT_BASE, fill=FILL_EXCLUDED,
                   border=BORDER_THIN, alignment=_al("left"))
            ws.merge_cells(start_row=r, start_column=4, end_row=r, end_column=15)
            r += 1
    else:
        c_empty = ws.cell(r, 2, "발송제외 거래처 없음")
        _apply(c_empty, font=FONT_GRAY_ITALIC, border=BORDER_THIN, alignment=_al("left"))
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=15)
        r += 1

    # 3. Key item 기준금액 (입력값 강조)
    r += 1
    _subheader_row(ws, r, "3. Key item 기준금액", col_end=15)
    r += 1

    for label, val, fmt, is_input in [
        ("수행중요성 (PM)",              pm,                         NUMFMT_INT, True),
        ("Key item 비율",               size_result.key_item_ratio, "0%",       False),
        ("Key item 기준금액 (PM × 비율)", size_result.key_item_threshold, NUMFMT_INT, True),
    ]:
        _text_cell(ws, r, 1, label, bold=True)
        if is_input:
            _input_cell(ws, r, 2, val, fmt=fmt)
        else:
            _num_cell(ws, r, 2, val, fmt=fmt)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=15)
        r += 1

    # 4. 거래처별 매트릭스
    r += 1
    _subheader_row(ws, r, "4. 거래처별 매트릭스", col_end=15)
    r += 1

    is_ar = prefix == "C100"
    group_col_map = dict(_AR_GROUP_COLS) if is_ar else dict(_AP_GROUP_COLS)

    matrix_headers = [(1, "No"), (2, "거래처명")]
    for g, c_idx in group_col_map.items():
        matrix_headers.append((c_idx, g))
    matrix_headers += [(10, "합계"), (11, "Key"), (12, "Rep"), (13, "특관"), (14, "최종")]

    for col_idx, label in matrix_headers:
        _header_cell(ws, r, col_idx, label)
    r += 1

    parties = sorted(
        [d for d in decisions if not d.is_excluded and d.balance > 0],
        key=lambda d: d.name,
    )
    totals: dict[str, float] = {}

    for seq, d in enumerate(parties, 1):
        fill = _party_fill(d)
        _text_cell(ws, r, 1, seq,    fill=fill, align="center")
        _text_cell(ws, r, 2, d.name, fill=fill, align="left")

        for g, col in group_col_map.items():
            amt = d.by_account.get(g, 0.0)
            if amt:
                _num_cell(ws, r, col, amt, fill=fill)
            else:
                _text_cell(ws, r, col, "", fill=fill, align="right")
            totals[g] = totals.get(g, 0.0) + amt

        _num_cell(ws, r, 10, d.balance, fill=fill)
        _text_cell(ws, r, 11, "Y" if d.is_key_item       else "N", fill=fill, align="center")
        _text_cell(ws, r, 12, "Y" if d.is_representative else "N", fill=fill, align="center")
        _text_cell(ws, r, 13, "Y" if d.is_related_party  else "N", fill=fill, align="center")
        _text_cell(ws, r, 14, "Y" if d.final_sampled      else "N", fill=fill, align="center")
        r += 1

    # 합계 행
    _total_row_cell(ws, r, 2, "합계")
    for g, col in group_col_map.items():
        _total_row_cell(ws, r, col, totals.get(g) or None, is_num=True)
    _total_row_cell(ws, r, 10, sum(d.balance for d in parties) or None, is_num=True)
    _total_row_cell(ws, r, 11, len([d for d in parties if d.is_key_item]),       is_num=True)
    _total_row_cell(ws, r, 12, len([d for d in parties if d.is_representative]), is_num=True)
    _total_row_cell(ws, r, 13, len([d for d in parties if d.is_related_party]),  is_num=True)
    _total_row_cell(ws, r, 14, len([d for d in parties if d.final_sampled]),     is_num=True)


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

    for c, w in [(1, 2.7), (2, 33.85), (3, 19.28), (4, 16.71), (5, 13.0),
                 (6, 13.0), (7, 13.0), (8, 8.0)]:
        _set_col_width(ws, c, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    _write_doc_header(
        ws, ctx.company_name, f"{prefix}-3 표본 추출 (MUS)",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no=f"{prefix}-3",
    )

    r = 5

    # 1. 표본추출방법
    _subheader_row(ws, r, "1. 표본추출방법", col_end=8)
    r += 1
    method_text = (
        "MUS(Monetary Unit Sampling): 거래금액 단위로 임의 출발점을 설정하고 "
        "표본간격(J)마다 화폐단위를 선택하는 통계적 표본추출 방법 (감사기준서 530)."
    )
    c = ws.cell(r, 1, method_text)
    _apply(c, font=FONT_BASE, border=BORDER_THIN,
           alignment=Alignment(horizontal="left", vertical="top", wrap_text=True))
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    ws.row_dimensions[r].height = 30
    r += 1

    # 2. 표본추출 모수
    r += 1
    _subheader_row(ws, r, "2. 표본추출 모수", col_end=8)
    r += 1

    for label, val, fmt in [
        ("잔여 모집단 (Key item 제외)", size_result.remaining_population, NUMFMT_INT),
        ("표본규모 (N)",               size_result.final_sample_size,    NUMFMT_INT),
        ("표본간격 (J)",               size_result.sample_interval,      NUMFMT_INT),
        ("임의출발점 (r₀)",            mus_result.random_start,          NUMFMT_INT),
    ]:
        _text_cell(ws, r, 1, label, bold=True)
        _num_cell(ws, r, 2, val, fmt=fmt)
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=8)
        r += 1

    # 3. MUS 추출 내역
    r += 1
    _subheader_row(ws, r, "3. Representative sample 추출 내역", col_end=8)
    r += 1

    for c_idx, h in enumerate(
        ["No", "거래처명", "잔액", "누적금액", "선택횟수", "표본간격", "잔여", "hit"], 1
    ):
        _header_cell(ws, r, c_idx, h)
    r += 1

    for i, sel in enumerate(mus_result.selections, 1):
        fill = FILL_SAMPLED if sel.hit else None
        _text_cell(ws, r, 1, i,              fill=fill, align="center")
        _text_cell(ws, r, 2, sel.name,       fill=fill, align="left")
        _num_cell(ws, r, 3, sel.balance,     fill=fill)
        _num_cell(ws, r, 4, sel.cumulative,  fill=fill)
        _text_cell(ws, r, 5, sel.selections, fill=fill, align="center")
        _num_cell(ws, r, 6, size_result.sample_interval, fill=fill)
        _num_cell(ws, r, 7, sel.remainder_after, fill=fill)
        _text_cell(ws, r, 8, "Y" if sel.hit else "N", fill=fill, align="center")
        r += 1

    # 합계 행
    _total_row_cell(ws, r, 2, "합계")
    _total_row_cell(ws, r, 3, sum(s.balance for s in mus_result.selections), is_num=True)
    _total_row_cell(ws, r, 5, sum(s.selections for s in mus_result.selections), is_num=True)


# ─────────────────────────────────────────────────────────────
# Sheet 7: 대체적 절차
# ─────────────────────────────────────────────────────────────

def _build_alt_procedures(
    wb, ctx: ReportContext,
    procedures: list[AlternativeProcedureEntry],
) -> None:
    ws = wb.create_sheet("대체적 절차")

    for c, w in [(1, 2.7), (2, 33.85), (3, 10.0), (4, 16.71), (5, 13.0),
                 (6, 24.0), (7, 16.71), (8, 10.0), (9, 10.0), (10, 24.0)]:
        _set_col_width(ws, c, w)

    prep_date   = ctx.prep_date   or date.today()
    review_date = ctx.review_date or date.today()

    _write_doc_header(
        ws, ctx.company_name, "대체적 절차 — 미회신·불일치 거래처",
        ctx.period_end, ctx.preparer, ctx.reviewer,
        prep_date, review_date, wp_no="대체",
        last_col=10,
    )

    r = 5
    _subheader_row(ws, r, "대체적 절차 수행 내역", col_end=10)
    r += 1

    headers = ["No", "거래처명", "사유", "장부가", "절차유형",
               "증빙명세", "커버금액", "커버리지%", "결론", "감사인 메모"]
    for i, h in enumerate(headers, 1):
        _header_cell(ws, r, i, h)
    r += 1

    if not procedures:
        c_empty = ws.cell(r, 2, "대체적 절차 대상 없음 (Step 5 미완료 또는 전원 일치)")
        _apply(c_empty, font=FONT_GRAY_ITALIC, border=BORDER_THIN, alignment=_al("left"))
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
        r += 1
    else:
        for i, proc in enumerate(procedures, 1):
            conclusion_fill = {
                "충분":  FILL_CONCLUSION_OK,
                "부분":  FILL_CONCLUSION_PARTIAL,
                "미해소": FILL_CONCLUSION_FAIL,
            }.get(proc.conclusion)

            _text_cell(ws, r, 1, i, align="center")
            _text_cell(ws, r, 2, proc.party_name, align="left")
            _text_cell(ws, r, 3, proc.reason, align="center")
            _num_cell(ws, r, 4, proc.ledger_balance)
            _text_cell(ws, r, 5, proc.procedure_type, align="center")
            _text_cell(ws, r, 6,
                       "; ".join(proc.evidence_names) if proc.evidence_names else "",
                       align="left")
            _num_cell(ws, r, 7, proc.covered_amount)
            if proc.coverage_ratio is not None:
                _pct_cell(ws, r, 8, proc.coverage_ratio, fill=conclusion_fill)
            else:
                _text_cell(ws, r, 8, "", align="center")
            _text_cell(ws, r, 9, proc.conclusion,   fill=conclusion_fill, align="center")
            _text_cell(ws, r, 10, proc.auditor_notes or "", align="left")
            r += 1

    # 집계 요약
    r += 1
    _subheader_row(ws, r, "집계 요약", col_end=10)
    r += 1

    if procedures:
        sufficient = sum(1 for p in procedures if p.conclusion == "충분")
        partial    = sum(1 for p in procedures if p.conclusion == "부분")
        unresolved = sum(1 for p in procedures if p.conclusion == "미해소")
        total_covered = sum(p.covered_amount or 0 for p in procedures)
        total_ledger  = sum(p.ledger_balance or 0 for p in procedures)
        overall_ratio = total_covered / total_ledger if total_ledger > 0 else None

        for label, val, fmt, fill in [
            ("충분 건수",   sufficient,    NUMFMT_INT, FILL_CONCLUSION_OK),
            ("부분 건수",   partial,       NUMFMT_INT, FILL_CONCLUSION_PARTIAL),
            ("미해소 건수", unresolved,    NUMFMT_INT, FILL_CONCLUSION_FAIL),
            ("장부가 합계", total_ledger,  NUMFMT_INT, None),
            ("커버금액 합계", total_covered, NUMFMT_INT, None),
        ]:
            _text_cell(ws, r, 1, label, bold=True)
            _num_cell(ws, r, 2, val, fill=fill, fmt=fmt)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
            r += 1

        if overall_ratio is not None:
            _text_cell(ws, r, 1, "전체 커버리지", bold=True)
            overall_fill = (
                FILL_CONCLUSION_OK if overall_ratio >= 0.95 else
                (FILL_CONCLUSION_PARTIAL if overall_ratio >= 0.5 else FILL_CONCLUSION_FAIL)
            )
            _pct_cell(ws, r, 2, overall_ratio, fill=overall_fill)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
