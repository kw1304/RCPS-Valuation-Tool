from pathlib import Path
from src.infrastructure.gl_loader import GLLoader

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mini_gl.xlsx"

def test_iter_rows_yields_dicts():
    rows = list(GLLoader(FIX).iter_rows())
    assert len(rows) == 4
    assert rows[0]["계정 과목"] == "보통예금"
    assert rows[0]["금액"] == 1000000
    assert rows[1]["거래처"] == "신한은행 도쿄지점"

def test_iter_filters_empty():
    # 빈 row 무시
    rows = list(GLLoader(FIX).iter_rows())
    assert all(r.get("계정 과목") for r in rows)
