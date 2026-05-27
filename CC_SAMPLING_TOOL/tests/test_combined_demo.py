"""
test_combined_demo.py — kind=both 통합 9시트 조서 검증 (Toss 디자인 재설계 후)

검증 항목:
  1. build_combined_report → 9개 시트 단일 파일
  2. 1번 시트 = "요약"
  3. 조회서 시트에 채권·채무 거래처 통합
  4. 표본규모 산출 시트에 채권/채무 각 데이터
  5. 모집단 완전성 시트에 데이터
  6. 채권·채무 합산 모집단 요약 반영
  7. 조서번호 셀 accent 파란색
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
    KindData,
    PartyContactInfo,
    ReportContext,
    EXPECTED_GENERIC_SHEETS,
    EXPECTED_SHEET_COUNT,
    TOSS_ACCENT,
    build_combined_report,
)
from src.domain.mus import MUSResult, MUSSelection
from src.domain.population import CompletenessCheck, PartyDecision
from src.domain.sample_size import SampleSizeResult


# ─────────────────────────────────────────────────────────────
# 픽스처
# ─────────────────────────────────────────────────────────────

def _completeness() -> CompletenessCheck:
    return CompletenessCheck(
        by_group=[
            {"group": "외상매출금", "ledger": 3_000_000, "fs": 3_000_000, "diff": 0, "note": ""},
        ],
        total_ledger=3_000_000,
        total_fs=3_000_000,
        total_diff=0,
    )


def _size_result() -> SampleSizeResult:
    return SampleSizeResult(
        key_item_threshold=400_000,
        key_item_ratio=0.5,
        confidence_factor=1.4,
        base_sample_size=7,
        final_sample_size=7,
        sample_interval=400_000,
        remaining_population=2_000_000,
    )


def _mus(name: str) -> MUSResult:
    return MUSResult(
        sample_interval=400_000,
        random_start=100_000,
        selections=[
            MUSSelection(
                name=name, balance=300_000, cumulative=300_000,
                selections=1, remainder_after=100_000, hit=True,
            ),
        ],
        sampled_names=[name],
    )


def _receivable_kd() -> KindData:
    return KindData(
        ctx=ReportContext(
            company_name="통합테스트회사",
            period_end=date(2025, 12, 31),
            kind="receivable",
            preparer="작성자A",
            reviewer="검토자B",
            workpaper_no_prefix="C100",
        ),
        completeness=_completeness(),
        size_result=_size_result(),
        decisions=[
            PartyDecision(
                name="채권거래처X", balance=900_000,
                is_key_item=True, is_representative=False,
                is_related_party=False, is_excluded=False,
                final_sampled=True,
                by_account={"외상매출금": 900_000},
            ),
            PartyDecision(
                name="채권거래처Y", balance=300_000,
                is_key_item=False, is_representative=True,
                is_related_party=False, is_excluded=False,
                final_sampled=True,
                by_account={"미수금": 300_000},
            ),
        ],
        mus_result=_mus("채권거래처Y"),
        performance_materiality=800_000,
        population_amount=3_000_000,
        contacts=[
            PartyContactInfo(name="채권거래처X", country="KR",
                             contact_person="김담당", email="x@test.com"),
        ],
    )


def _payable_kd() -> KindData:
    return KindData(
        ctx=ReportContext(
            company_name="통합테스트회사",
            period_end=date(2025, 12, 31),
            kind="payable",
            preparer="작성자A",
            reviewer="검토자B",
            workpaper_no_prefix="AA100",
        ),
        completeness=_completeness(),
        size_result=_size_result(),
        decisions=[
            PartyDecision(
                name="채무거래처P", balance=600_000,
                is_key_item=True, is_representative=False,
                is_related_party=False, is_excluded=False,
                final_sampled=True,
                by_account={"외상매입금": 600_000},
            ),
            PartyDecision(
                name="채무거래처Q", balance=250_000,
                is_key_item=False, is_representative=True,
                is_related_party=False, is_excluded=False,
                final_sampled=True,
                by_account={"미지급금": 250_000},
            ),
        ],
        mus_result=_mus("채무거래처Q"),
        performance_materiality=800_000,
        population_amount=2_500_000,
    )


def _build_combined(tmp_path: Path) -> openpyxl.Workbook:
    out = tmp_path / "combined_test.xlsx"
    build_combined_report(
        out_path=out,
        receivable=_receivable_kd(),
        payable=_payable_kd(),
    )
    return openpyxl.load_workbook(out)


# ─────────────────────────────────────────────────────────────
# 1. 시트 수 — 9개
# ─────────────────────────────────────────────────────────────

def test_combined_has_9_sheets(tmp_path):
    """build_combined_report → 정확히 EXPECTED_SHEET_COUNT(10)개 시트."""
    wb = _build_combined(tmp_path)
    assert len(wb.sheetnames) == EXPECTED_SHEET_COUNT, (
        f"시트 수 불일치: {len(wb.sheetnames)} — {wb.sheetnames}"
    )


# ─────────────────────────────────────────────────────────────
# 2. 1번 시트 = 요약
# ─────────────────────────────────────────────────────────────

def test_first_sheet_is_summary(tmp_path):
    """첫 번째 시트가 '요약'이어야 한다."""
    wb = _build_combined(tmp_path)
    assert wb.sheetnames[0] == "요약", f"첫 시트 불일치: {wb.sheetnames[0]}"


# ─────────────────────────────────────────────────────────────
# 3. 시트 이름 집합
# ─────────────────────────────────────────────────────────────

def test_sheet_names_match_expected(tmp_path):
    """10개 시트 이름이 EXPECTED_GENERIC_SHEETS와 일치해야 한다."""
    wb = _build_combined(tmp_path)
    actual = set(wb.sheetnames)
    missing = EXPECTED_GENERIC_SHEETS - actual
    extra   = actual - EXPECTED_GENERIC_SHEETS
    assert not missing, f"누락 시트: {missing}"
    assert not extra,   f"예상 외 시트: {extra}"


# ─────────────────────────────────────────────────────────────
# 4. 조회서 — 채권·채무 통합 (한 시트에 모두)
# ─────────────────────────────────────────────────────────────

def test_confirmation_sheet_has_both_ar_ap_parties(tmp_path):
    """샘플링 거래처 내역 시트에 채권·채무 거래처 모두 포함되어야 한다."""
    wb = _build_combined(tmp_path)
    ws = wb["샘플링 거래처 내역"]
    all_values = {
        str(cell.value)
        for row in ws.iter_rows()
        for cell in row
        if cell.value is not None
    }
    assert "채권거래처X" in all_values, "샘플링 거래처 내역에 채권거래처X 없음"
    assert "채무거래처P" in all_values, "샘플링 거래처 내역에 채무거래처P 없음"


def test_no_separate_c100_sheet(tmp_path):
    """구버전 'C100 조회서' 별도 시트가 없어야 한다 (통합 조회서로 대체)."""
    wb = _build_combined(tmp_path)
    assert "C100 조회서" not in wb.sheetnames, "구버전 C100 조회서 시트가 잔존"
    assert "AA100 조회서" not in wb.sheetnames, "구버전 AA100 조회서 시트가 잔존"


# ─────────────────────────────────────────────────────────────
# 5. 표본규모 산출 — 채권/채무 각 데이터
# ─────────────────────────────────────────────────────────────

def test_sample_size_sheet_has_ar_population(tmp_path):
    """표본규모 산출 시트에 채권 모집단 금액(3,000,000)이 반영되어야 한다."""
    wb = _build_combined(tmp_path)
    ws = wb["표본규모 산출"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row]
    assert 3_000_000 in all_values, "표본규모 산출에 채권 모집단 금액 없음"


def test_sample_size_sheet_has_ap_population(tmp_path):
    """표본규모 산출 시트에 채무 모집단 금액(2,500,000)이 반영되어야 한다."""
    wb = _build_combined(tmp_path)
    ws = wb["표본규모 산출"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row]
    assert 2_500_000 in all_values, "표본규모 산출에 채무 모집단 금액 없음"


# ─────────────────────────────────────────────────────────────
# 6. 요약 시트 — 합산 모집단
# ─────────────────────────────────────────────────────────────

def test_summary_sheet_contains_total_population(tmp_path):
    """요약 시트: 채권+채무 합산 모집단(5,500,000)이 반영되어야 한다."""
    wb = _build_combined(tmp_path)
    ws = wb["요약"]
    all_values = [cell.value for row in ws.iter_rows() for cell in row]
    # 3,000,000 + 2,500,000 = 5,500,000
    assert 5_500_000 in all_values, (
        f"요약 시트에 합산 모집단 5,500,000 없음. 수치 값: "
        f"{[v for v in all_values if isinstance(v, (int, float))][:10]}"
    )


# ─────────────────────────────────────────────────────────────
# 7. 조서번호 셀 — Toss accent 파란색
# ─────────────────────────────────────────────────────────────

def test_workpaper_no_cell_accent_blue(tmp_path):
    """표본규모 산출 I2 셀: 조서번호가 파란(3182F6) bold이어야 한다."""
    wb = _build_combined(tmp_path)
    ws = wb["표본규모 산출"]
    cell = ws["I2"]
    assert cell.value is not None, "I2 셀 값 없음"
    assert cell.font.bold, "조서번호 셀 bold 아님"
    assert cell.font.color.rgb.upper().endswith(TOSS_ACCENT.upper()), (
        f"조서번호 글씨색 불일치 (3182F6이어야): {cell.font.color.rgb}"
    )


# ─────────────────────────────────────────────────────────────
# 8. 주소 적정성 — 연락처 반영
# ─────────────────────────────────────────────────────────────

def test_address_sheet_has_contact(tmp_path):
    """주소 적정성 시트에 채권거래처X 이메일이 반영되어야 한다."""
    wb = _build_combined(tmp_path)
    ws = wb["주소 적정성"]
    all_values = {cell.value for row in ws.iter_rows() for cell in row}
    assert "x@test.com" in all_values, "채권거래처X 이메일 미반영"


# ─────────────────────────────────────────────────────────────
# 9. 대체적 절차 시트 존재
# ─────────────────────────────────────────────────────────────

def test_alt_procedure_sheet_exists(tmp_path):
    """대체적 절차 시트가 존재해야 한다."""
    wb = _build_combined(tmp_path)
    assert "대체적 절차" in wb.sheetnames
