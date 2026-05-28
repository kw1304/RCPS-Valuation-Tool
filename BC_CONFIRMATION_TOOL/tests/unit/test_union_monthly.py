from src.infrastructure.union_monthly import parse_union_monthly, parse_collateral_or_guarantee
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_parse_collateral_extracts_institutions():
    src = ROOT / "INPUT" / "비티아이 제공 담보현황 251231_ok.xlsx"
    if not src.exists():
        import pytest; pytest.skip("INPUT 없음")
    names = parse_collateral_or_guarantee(src)
    assert isinstance(names, list)
    assert len(names) > 0
    # 적어도 1개 은행/금융기관 이름이 들어가야 함
    assert any("은행" in n or "보험" in n or "증권" in n for n in names)

def test_parse_guarantee_extracts_institutions():
    src = ROOT / "INPUT" / "비티아이 제공 연대보증현황 251231.xlsx"
    if not src.exists():
        import pytest; pytest.skip("INPUT 없음")
    names = parse_collateral_or_guarantee(src)
    assert len(names) > 0
