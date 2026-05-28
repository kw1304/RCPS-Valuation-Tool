from pathlib import Path
from typing import Iterator
import openpyxl


class GLLoader:
    """대용량 G/L Excel을 stream으로 읽음. read_only=True로 메모리 절약."""

    def __init__(self, path: Path):
        self.path = path

    def iter_rows(self, sheet: str | None = None) -> Iterator[dict]:
        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if not header:
            return
        cols = [str(h).strip() if h is not None else "" for h in header]
        for row in it:
            if not any(v not in (None, "") for v in row):
                continue
            d = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
            # 계정 과목 컬럼 없으면 skip
            if not d.get("계정 과목"):
                continue
            yield d
        wb.close()
