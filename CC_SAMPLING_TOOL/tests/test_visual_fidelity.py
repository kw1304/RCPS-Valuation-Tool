"""
test_visual_fidelity.py — Toss 디자인 시각 정합성 검증

검증 항목:
  1. 모든 시트의 데이터 셀 폰트가 "맑은 고딕"
  2. 수행중요성(PM) 강조 — 파란 bold 글씨 (TOSS_ACCENT = 3182F6)
  3. 조회서 헤더 행 — 흰 배경 + 파란 bottom border (Toss 스타일)
  4. 컬럼 너비 — 표본규모 산출 A열 ≈ 35
  5. 조서번호 셀 I2 — accent bold 파란색 (3182F6)
  6. 소제목 행 — F9FAFB 옅은 회색 배경
  7. Key item 거래처 — 좌측 GOLD border (FFD966) 표시
  8. MUS hit 거래처 — 파란 bold 또는 초록 좌측 border
  9. 합계 행 — F9FAFB 배경 + bold + 상단 굵은 border
 10. 발송제외 거래처 — strikethrough 폰트
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openpyxl
import pytest

from src.infrastructure.report.generic_reporter import (
    AlternativeProcedureEntry,
    ConfirmationReplyInfo,
    ExclusionRow,
    PartyContactInfo,
    ReportContext,
    build_generic_report,
    FONT_NAME,
    TOSS_ACCENT,
    TOSS_BG_SUB,
    TOSS_GOLD,
    TOSS_GREEN,
)
from src.domain.mus import MUSResult, MUSSelection
from src.domain.population import CompletenessCheck, PartyDecision
from src.domain.sample_size import SampleSizeResult


# ─────────────────────────────────────────────────────────────
# 공통 픽스처
# ─────────────────────────────────────────────────────────────

def _ctx() -> ReportContext:
    return ReportContext(
        company_name="시각테스트회사",
        period_end=date(2025, 12, 31),
        kind="receivable",
        preparer="홍길동",
        reviewer="이검토",
        prep_date=date(2026, 1, 10),
        review_date=date(2026, 1, 15),
        workpaper_no_prefix="C100",
    )


def _completeness() -> CompletenessCheck:
    return CompletenessCheck(
        by_group=[
            {"group": "외상매출금", "ledger": 5_000_000, "fs": 5_000_000, "diff": 0, "note": ""},
        ],
        total_ledger=5_000_000,
        total_fs=5_000_000,
        total_diff=0,
    )


def _size_result() -> SampleSizeResult:
    return SampleSizeResult(
        key_item_threshold=500_000,
        key_item_ratio=0.5,
        confidence_factor=1.4,
        base_sample_size=8,
        final_sample_size=8,
        sample_interval=600_000,
        remaining_population=4_000_000,
    )


def _decisions() -> list[PartyDecision]:
    return [
        PartyDecision(
            name="대형거래처A", balance=1_200_000,
            is_key_item=True, is_representative=False,
            is_related_party=False, is_excluded=False,
            final_sampled=True,
            by_account={"외상매출금": 1_200_000},
        ),
        PartyDecision(
            name="대형거래처B", balance=800_000,
            is_key_item=True, is_representative=False,
            is_related_party=False, is_excluded=False,
            final_sampled=True,
            by_account={"외상매출금": 800_000},
        ),
        PartyDecision(
            name="중소거래처C", balance=350_000,
            is_key_item=False, is_representative=True,
            is_related_party=False, is_excluded=False,
            final_sampled=True,
            by_account={"미수금": 350_000},
        ),
        PartyDecision(
            name="제외거래처D", balance=100_000,
            is_key_item=False, is_representative=False,
            is_related_party=False, is_excluded=True,
            final_sampled=False,
            exclusion_reason="해산",
            by_account={"외상매출금": 100_000},
        ),
    ]


def _mus_result() -> MUSResult:
    return MUSResult(
        sample_interval=600_000,
        random_start=150_000,
        selections=[
            MUSSelection(
                name="중소거래처C", balance=350_000, cumulative=350_000,
                selections=1, remainder_after=200_000, hit=True,
            ),
            MUSSelection(
                name="소형거래처E", balance=80_000, cumulative=430_000,
                selections=0, remainder_after=120_000, hit=False,
            ),
        ],
        sampled_names=["중소거래처C"],
    )


def _build(tmp_path: Path) -> openpyxl.Workbook:
    out = tmp_path / "visual_test.xlsx"
    build_generic_report(
        out_path=out,
        ctx=_ctx(),
        completeness=_completeness(),
        size_result=_size_result(),
        decisions=_decisions(),
        mus_result=_mus_result(),
        performance_materiality=1_000_000,
        population_amount=5_000_000,
        contacts=[
            PartyContactInfo(
                name="대형거래처A",
                country="KR",
                contact_person="김담당",
                email="a@example.com",
            )
        ],
    )
    return openpyxl.load_workbook(out)


# ─────────────────────────────────────────────────────────────
# 1. 폰트 이름 검증 — 맑은 고딕
# ─────────────────────────────────────────────────────────────

def test_all_data_cells_use_malgun_gothic(tmp_path):
    """생성된 모든 시트 데이터 셀의 폰트 이름이 '맑은 고딕'이어야 한다."""
    wb = _build(tmp_path)
    violations = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and cell.font and cell.font.name:
                    if cell.font.name != FONT_NAME:
                        violations.append(
                            f"{sheet_name}!{cell.coordinate}: font={cell.font.name}"
                        )
    assert not violations, f"비맑은고딕 셀 발견: {violations[:10]}"


# ─────────────────────────────────────────────────────────────
# 2. PM 강조 — 파란 bold (TOSS_ACCENT)
# ─────────────────────────────────────────────────────────────

def test_pm_cell_has_accent_blue_font(tmp_path):
    """표본규모 산출 시트: PM 값 셀이 파란(3182F6) bold 글씨이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    found = False
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == "수행중요성 (PM)":
                val_cell = ws.cell(cell.row, 2)
                assert val_cell.font.bold, "PM 값 셀이 bold가 아님"
                assert val_cell.font.color.rgb.upper().endswith(TOSS_ACCENT.upper()), (
                    f"PM 셀 글씨색 불일치: {val_cell.font.color.rgb}"
                )
                found = True
    assert found, "표본규모 산출 시트에 '수행중요성 (PM)' 라벨이 없음"


def test_key_item_threshold_has_accent_font(tmp_path):
    """표본규모 산출: Key item 기준금액 셀이 파란(3182F6) bold이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    found = False
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and "Key item 기준금액" in str(cell.value):
                val_cell = ws.cell(cell.row, 2)
                assert val_cell.font.bold, "Key item 기준금액 셀 bold 아님"
                assert val_cell.font.color.rgb.upper().endswith(TOSS_ACCENT.upper()), (
                    f"Key item 기준금액 글씨색 불일치: {val_cell.font.color.rgb}"
                )
                found = True
    assert found, "표본규모 산출에 'Key item 기준금액' 라벨이 없음"


# ─────────────────────────────────────────────────────────────
# 3. 조회서 헤더 — 흰 배경 + 파란 bottom border
# ─────────────────────────────────────────────────────────────

def test_confirmation_sheet_header_has_accent_bottom_border(tmp_path):
    """조회서: 테이블 헤더 행이 파란(3182F6) bottom border를 가져야 한다."""
    wb = _build(tmp_path)
    ws = wb["샘플링 거래처 내역"]

    accent_border_found = False
    for row in ws.iter_rows():
        for cell in row:
            if (cell.border and cell.border.bottom
                    and cell.border.bottom.color
                    and cell.border.bottom.color.rgb.upper().endswith(TOSS_ACCENT.upper())):
                accent_border_found = True
                # 흰 배경 확인
                if cell.fill and cell.fill.fgColor:
                    assert cell.fill.fgColor.rgb.upper().endswith("FFFFFF"), (
                        f"헤더 배경 불일치 (흰색이어야 함): {cell.fill.fgColor.rgb}"
                    )
    assert accent_border_found, "조회서 헤더에 파란 bottom border가 없음"


# ─────────────────────────────────────────────────────────────
# 4. 컬럼 너비 검증
# ─────────────────────────────────────────────────────────────

def test_sample_size_sheet_col_a_width(tmp_path):
    """표본규모 산출: A열(항목) 너비 ≈ 35 (오차 ±1)."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]
    w_a = ws.column_dimensions["A"].width
    assert abs(w_a - 35) < 1, f"A열 너비 불일치: {w_a}"


def test_confirmation_col_b_width(tmp_path):
    """조회서: B열(거래처명) 너비 ≈ 30 (오차 ±1)."""
    wb = _build(tmp_path)
    ws = wb["샘플링 거래처 내역"]
    w_b = ws.column_dimensions["B"].width
    assert abs(w_b - 30) < 1, f"B열 너비 불일치: {w_b}"


# ─────────────────────────────────────────────────────────────
# 5. 조서번호 셀 I2 — accent bold 파란색
# ─────────────────────────────────────────────────────────────

def test_workpaper_no_cell_accent_bold(tmp_path):
    """표본규모 산출 시트 I2 셀: 조서번호 값이 파란(3182F6) + bold이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    cell = ws["I2"]
    assert cell.value is not None and "규모산출" in str(cell.value), f"I2 값 불일치: {cell.value}"
    assert cell.font.bold, "조서번호 셀이 bold가 아님"
    assert cell.font.color.rgb.upper().endswith(TOSS_ACCENT.upper()), (
        f"조서번호 글씨색 불일치 (파란색이어야): {cell.font.color.rgb}"
    )


def test_summary_sheet_wp_no_accent(tmp_path):
    """요약 시트 I2 셀: 조서번호가 파란(3182F6)이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["요약"]
    cell = ws["I2"]
    assert cell.font.color.rgb.upper().endswith(TOSS_ACCENT.upper()), (
        f"요약 시트 I2 글씨색 불일치: {cell.font.color.rgb}"
    )


# ─────────────────────────────────────────────────────────────
# 6. 소제목 행 — F9FAFB 옅은 회색 배경
# ─────────────────────────────────────────────────────────────

def test_subheader_fill_toss_bg_sub(tmp_path):
    """표본규모 산출 소제목 행이 F9FAFB 배경이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    subheader_found = any(
        cell.fill and cell.fill.fgColor
        and cell.fill.fgColor.rgb.upper().endswith(TOSS_BG_SUB.upper())
        for row in ws.iter_rows()
        for cell in row
        if cell.value and ("채권" in str(cell.value) or "채무" in str(cell.value))
    )
    assert subheader_found, f"표본규모 산출 소제목 행에 {TOSS_BG_SUB} 배경 없음"


# ─────────────────────────────────────────────────────────────
# 7. Key item 거래처 — GOLD 좌측 border (FFD966)
# ─────────────────────────────────────────────────────────────

def test_key_item_row_has_gold_left_border(tmp_path):
    """조회서: Key item 거래처(대형거래처A/B)의 첫 번째 셀이 GOLD 좌측 border를 가져야 한다."""
    wb = _build(tmp_path)
    ws = wb["샘플링 거래처 내역"]

    gold_found = False
    for row in ws.iter_rows():
        for cell in row:
            if cell.value in ("대형거래처A", "대형거래처B"):
                # 같은 행 A열(No 셀) left border 확인
                no_cell = ws.cell(cell.row, 1)
                if (no_cell.border and no_cell.border.left
                        and no_cell.border.left.color
                        and no_cell.border.left.color.rgb.upper().endswith(TOSS_GOLD.upper())):
                    gold_found = True
    assert gold_found, f"조회서 Key item 행에 GOLD({TOSS_GOLD}) 좌측 border 없음"


# ─────────────────────────────────────────────────────────────
# 8. MUS hit — 초록(00C073) 이름 글씨 또는 좌측 border
# ─────────────────────────────────────────────────────────────

def test_mus_hit_row_has_green_marker(tmp_path):
    """MUS 추출 내역: hit=True 거래처(중소거래처C)가 초록(00C073) 표시이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["MUS 추출 내역"]

    green_found = False
    for row in ws.iter_rows():
        for cell in row:
            if cell.value == "중소거래처C":
                # 이름 셀 글씨색 or 좌측 border 초록
                if cell.font and cell.font.color.rgb.upper().endswith(TOSS_GREEN.upper()):
                    green_found = True
                # 같은 행 No 셀 좌측 border 초록 확인
                no_cell = ws.cell(cell.row, 1)
                if (no_cell.border and no_cell.border.left
                        and no_cell.border.left.color
                        and no_cell.border.left.color.rgb.upper().endswith(TOSS_GREEN.upper())):
                    green_found = True
    assert green_found, f"MUS hit 행에 초록({TOSS_GREEN}) 표시 없음"


# ─────────────────────────────────────────────────────────────
# 9. 합계 행 — F9FAFB 배경 + bold
# ─────────────────────────────────────────────────────────────

def test_total_row_fill_and_bold(tmp_path):
    """조회서: '총합계' 셀이 F9FAFB 배경 + bold이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["샘플링 거래처 내역"]

    for row in ws.iter_rows():
        for cell in row:
            if cell.value == "총합계":
                assert cell.font and cell.font.bold, "총합계 셀이 bold가 아님"
                assert (cell.fill and cell.fill.fgColor
                        and cell.fill.fgColor.rgb.upper().endswith(TOSS_BG_SUB.upper())), (
                    f"총합계 셀 배경 불일치 (F9FAFB이어야): {cell.fill.fgColor.rgb if cell.fill else None}"
                )
                return
    pytest.fail("조회서에 '총합계' 셀이 없음")


# ─────────────────────────────────────────────────────────────
# 10. 발송제외 거래처 — strikethrough 폰트
# ─────────────────────────────────────────────────────────────

def test_excluded_party_has_strikethrough(tmp_path):
    """조회서·Key item 매트릭스: 발송제외 거래처(제외거래처D)가 strikethrough이어야 한다."""
    wb = _build(tmp_path)
    ws = wb["샘플링 거래처 내역"]

    strike_found = any(
        cell.font and cell.font.strike
        for row in ws.iter_rows()
        for cell in row
        if cell.value == "제외거래처D"
    )
    assert strike_found, "조회서에 발송제외 거래처(제외거래처D) strikethrough 없음"


# ─────────────────────────────────────────────────────────────
# 11. 헤더 블록 구조 검증 (R1~R2)
# ─────────────────────────────────────────────────────────────

def test_doc_header_structure(tmp_path):
    """표본규모 산출: A1=회사명, A2=제목(bold), I1=조서번호 라벨, I2=파란글씨."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    assert ws["A1"].value == "시각테스트회사", f"A1 값: {ws['A1'].value}"
    assert ws["A2"].font.bold, "A2 제목 셀이 bold가 아님"
    assert ws["I1"].value == "조서번호", f"I1 값: {ws['I1'].value}"
    assert ws["I2"].font.color.rgb.upper().endswith(TOSS_ACCENT.upper()), \
        f"I2 조서번호 글씨색 불일치: {ws['I2'].font.color.rgb}"


def test_doc_header_preparer_reviewer(tmp_path):
    """표본규모 산출: E1='작성자:', F1=작성자명, E2='검토자:', F2=검토자명."""
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    assert ws["E1"].value == "작성자:", f"E1: {ws['E1'].value}"
    assert ws["E2"].value == "검토자:", f"E2: {ws['E2'].value}"
    assert ws["F1"].value == "홍길동", f"F1: {ws['F1'].value}"
    assert ws["F2"].value == "이검토", f"F2: {ws['F2'].value}"


# ─────────────────────────────────────────────────────────────
# 12. 숫자 포맷 검증
# ─────────────────────────────────────────────────────────────

def test_amount_cells_use_numfmt_int(tmp_path):
    """표본규모 산출: PM 값 셀에 NUMFMT_INT 포맷 적용 여부."""
    from src.infrastructure.report.generic_reporter import NUMFMT_INT
    wb = _build(tmp_path)
    ws = wb["표본규모 산출"]

    for row in ws.iter_rows():
        for cell in row:
            if cell.value == "수행중요성 (PM)":
                val_cell = ws.cell(cell.row, 2)
                assert val_cell.number_format == NUMFMT_INT, (
                    f"PM 셀 포맷 불일치: {val_cell.number_format}"
                )
                return
    pytest.fail("PM 셀 미발견")
