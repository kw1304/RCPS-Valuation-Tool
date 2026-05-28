import json
import shutil
from datetime import datetime
from pathlib import Path
from sqlmodel import Session, select
import openpyxl
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


def _fill_control_sheet(wb, cps: list[Counterparty]):
    """Fill AC control sheet with counterparty summary."""
    sheet = next((wb[s] for s in wb.sheetnames if "control sheet" in s.lower()), None)
    if sheet is None:
        return

    for i, cp in enumerate(cps):
        r = 6 + i
        sheet[f"B{r}"] = cp.bc_no
        sheet[f"C{r}"] = cp.canonical_name
        if cp.branch:
            sheet[f"D{r}"] = cp.branch
        sheet[f"E{r}"] = cp.channel or ""
        sheet[f"F{r}"] = cp.address or ""
        sheet[f"J{r}"] = "회신" if cp.response_arrived else "미회신"


def _fill_ac0(wb, cps: list[Counterparty]):
    """Fill AC0 summary sheet with counterparty flags."""
    sheet = next((wb[s] for s in wb.sheetnames if s.startswith("AC0.")), None)
    if sheet is None:
        return

    for i, cp in enumerate(cps):
        r = 12 + i
        sheet[f"C{r}"] = cp.bc_no
        sheet[f"D{r}"] = cp.canonical_name + (f" {cp.branch}" if cp.branch else "")
        sheet[f"E{r}"] = "Y" if cp.cs_present else "N"
        sheet[f"F{r}"] = "Y" if cp.prior_present else "N"
        sheet[f"G{r}"] = "Y" if cp.union_listed else "N"
        sheet[f"H{r}"] = ("담보 Y/" if cp.collateral_listed else "담보 N/") + ("보증 Y" if cp.guarantee_listed else "보증 N")
        sheet[f"I{r}"] = "✓" if cp.response_arrived else ""
