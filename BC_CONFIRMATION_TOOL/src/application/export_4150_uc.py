import json
import shutil
from datetime import datetime
from pathlib import Path
from sqlmodel import Session, select
import openpyxl
from openpyxl.cell.cell import MergedCell
from src.infrastructure.db.models import Project, Counterparty, ExtractedRecord
from src.infrastructure.excel_writer.ac_filler import ACFiller, SHEET_CONFIG
from src.infrastructure.excel_writer.color_swap import apply_toss_palette, mark_low_confidence
from src.domain.ac_models import (
    FinancialAsset, Borrowing, Derivative, Guarantee,
    Collateral, BillCheck, Insurance, GeneralDeal,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "4150_AC_template.xlsx"
OUTPUT_DIR = ROOT / "OUTPUT"

MODEL_BY_SECTION = {
    "AC1": FinancialAsset, "AC2": Borrowing, "AC3": Derivative,
    "AC4": Guarantee, "AC5": Collateral, "AC6": BillCheck,
    "AC7": Insurance, "AC8": GeneralDeal,
}


def export_4150(session: Session, project_id: int) -> Path:
    """Export 4150 AC workpaper from extracted records and counterparty data."""
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fy = project.fiscal_date[:4]
    out_path = OUTPUT_DIR / f"4150_AC_금융기관조회_{project.name}_FY{fy}_{ts}.xlsx"

    # Copy template
    shutil.copy(TEMPLATE, out_path)
    filler = ACFiller(out_path)

    # Stamp project info (회사명·기준일) — propagates via formulas to AC1~AC10
    _stamp_project_info(filler.wb, project.name, project.fiscal_date)

    # Clear V1 example data rows (예: V1엔 코스맥스비티아이 전기 데이터가 채워져 있음)
    _clear_data_rows(filler.wb)

    # Get counterparties
    cps = list(session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ).all())

    # Fill AC control sheet + AC0
    _fill_control_sheet(filler.wb, cps)
    _fill_ac0(filler.wb, cps)

    # Fill AC1~AC8: ExtractedRecord
    for ac in MODEL_BY_SECTION:
        records_raw = session.exec(
            select(ExtractedRecord).where(
                ExtractedRecord.project_id == project_id,
                ExtractedRecord.ac_section == ac,
            )
        ).all()

        Model = MODEL_BY_SECTION[ac]
        models = [Model.model_validate_json(r.payload_json) for r in records_raw]

        filler.fill_section(ac, models)

        cfg = SHEET_CONFIG[ac]
        ws = filler.wb[cfg["sheet_name"]] if cfg["sheet_name"] in filler.wb.sheetnames else None
        if ws:
            for idx, raw in enumerate(records_raw):
                if raw.confidence == "low":
                    for col in cfg["cols"].keys():
                        mark_low_confidence(ws, cfg["start_row"] + idx, col)

    # Apply Toss palette
    apply_toss_palette(filler.wb)
    filler.save()

    return out_path


def _safe_write(sheet, cell_ref: str, value) -> None:
    """Merged cell 에 쓰기 시도 시 조용히 skip."""
    cell = sheet[cell_ref]
    if isinstance(cell, MergedCell):
        return
    cell.value = value


def _fill_control_sheet(wb, cps: list[Counterparty]):
    """Fill AC control sheet with counterparty summary."""
    sheet = next((wb[s] for s in wb.sheetnames if "control sheet" in s.lower()), None)
    if sheet is None:
        return

    for i, cp in enumerate(cps):
        r = 6 + i
        _safe_write(sheet, f"B{r}", cp.bc_no)
        _safe_write(sheet, f"C{r}", cp.canonical_name)
        if cp.branch:
            _safe_write(sheet, f"D{r}", cp.branch)
        _safe_write(sheet, f"E{r}", cp.channel or "")
        _safe_write(sheet, f"F{r}", cp.address or "")
        _safe_write(sheet, f"J{r}", "회신" if cp.response_arrived else "미회신")


def _fill_ac0(wb, cps: list[Counterparty]):
    """Fill AC0 summary sheet with counterparty flags."""
    sheet = next((wb[s] for s in wb.sheetnames if s.startswith("AC0.")), None)
    if sheet is None:
        return

    for i, cp in enumerate(cps):
        r = 12 + i
        _safe_write(sheet, f"C{r}", cp.bc_no)
        _safe_write(sheet, f"D{r}", cp.canonical_name + (f" {cp.branch}" if cp.branch else ""))
        _safe_write(sheet, f"E{r}", "Y" if cp.cs_present else "N")
        _safe_write(sheet, f"F{r}", "Y" if cp.prior_present else "N")
        _safe_write(sheet, f"G{r}", "Y" if cp.union_listed else "N")
        _safe_write(sheet, f"H{r}", ("담보 Y/" if cp.collateral_listed else "담보 N/") + ("보증 Y" if cp.guarantee_listed else "보증 N"))
        _safe_write(sheet, f"I{r}", "✓" if cp.response_arrived else "")


def _stamp_project_info(wb, company_name: str, fiscal_date: str):
    """Stamp 회사명·기준일 onto each AC sheet.
    AC control sheet의 A1·A3에 박으면 AC1~AC10은 formula로 자동 참조."""
    # 회사명: 보통 'A1' 위치. AC1~AC10은 formula로 control sheet를 참조함.
    for sheet_name in wb.sheetnames:
        if sheet_name.startswith("AC1~AC8"):
            continue  # divider sheet
        ws = wb[sheet_name]
        # A1: 회사명 (control sheet에서만 직접 stamp; 나머지는 formula 유지)
        if "control sheet" in sheet_name.lower() or sheet_name.startswith("AC0."):
            _safe_write(ws, "A1", f"{company_name} 주식회사")
        # A3: 기준일
        _safe_write(ws, "A3", fiscal_date)


# AC1~AC8 data row 영역 (start_row, footer 직전 행) — V1 예시 데이터 clear용
_DATA_REGION = {
    "AC0.": (12, 110),   # 전기 list + 검토 row
    "AC1.": (11, 128),   # 금융자산 list
    "AC2.": (12, 45),    # 차입금 list
    "AC3.": (12, 14),    # 파생상품 list (적게)
    "AC4.": (13, 65),    # 지급보증
    "AC5.": (12, 60),    # 담보제공자산
    "AC6.": (13, 43),    # 어음·수표
    "AC7.": (12, 45),    # 보험
    "AC8.": (12, 21),    # 리스
}

# 각 시트별 clear 대상 column 범위 (헤더 column 보존)
_DATA_COLS = "CDEFGHIJKLMNOPQ"  # AC sheet들 데이터 column 일반


def _clear_data_rows(wb):
    """V1 template에 들어있는 전년도 예시 데이터를 비움.
    헤더·서식·병합·footer는 보존."""
    for prefix, (start, end) in _DATA_REGION.items():
        sheet_name = next((s for s in wb.sheetnames if s.startswith(prefix)), None)
        if sheet_name is None:
            continue
        ws = wb[sheet_name]
        for r in range(start, min(end, ws.max_row) + 1):
            for col_letter in _DATA_COLS:
                try:
                    cell = ws[f"{col_letter}{r}"]
                    if isinstance(cell, MergedCell):
                        continue
                    # 셀에 값 있으면만 clear (footer 영역 보호용 휴리스틱: 굵은 글씨·합계 텍스트는 건너뜀)
                    val = cell.value
                    if val is None:
                        continue
                    if isinstance(val, str) and any(k in val for k in ("합계","계","소계","footer","Total","total")):
                        continue
                    cell.value = None
                except Exception:
                    continue
