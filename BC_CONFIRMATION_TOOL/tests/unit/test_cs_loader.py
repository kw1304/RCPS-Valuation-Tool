from pathlib import Path
from src.infrastructure.cs_loader import ControlSheetLoader

FIX_DIR = Path(__file__).resolve().parents[1] / "fixtures"

def test_load_control_sheet_extracts_bc_rows(tmp_path):
    src = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT/4150_AC 금융기관 조회_코스맥스비티아이_FY2025_V1.xlsx")
    if not src.exists():
        import pytest
        pytest.skip("INPUT 파일 없음")
    rows = ControlSheetLoader(src).load_bc_rows()
    assert len(rows) > 0
    assert any(r["bc_no"].startswith("BC-") for r in rows)
    # 최소 컬럼: bc_no, name, branch, channel, address, contact, phone
    sample = rows[0]
    for k in ("bc_no","name","channel"):
        assert k in sample
