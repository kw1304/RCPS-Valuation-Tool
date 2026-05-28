from pathlib import Path
from typing import Iterator
import openpyxl


class GLLoader:
    """대용량 G/L Excel을 stream으로 읽음. read_only=True로 메모리 절약.

    두 가지 포맷 지원:
    1. 표준 포맷: 컬럼 "계정 과목", "거래처", "금액"
    2. SAP 보조부원장 포맷: 컬럼 "계정", "계정명", "차변금액(현지통화)", "대변금액(현지통화)"
       - 금융계정에서 거래처는 계정명에 내재 (예: "기업은행 257-... 보통예금")
       - 출력 시 "계정 과목" → 계정명, "거래처" → 계정명, "금액" → 차변-대변
    """

    def __init__(self, path: Path):
        self.path = path

    def iter_rows(self, sheet: str | None = None) -> Iterator[dict]:
        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if not header:
            wb.close()
            return
        cols = [str(h).strip() if h is not None else "" for h in header]
        is_sap = "계정명" in cols and "계정 과목" not in cols
        for row in it:
            if not any(v not in (None, "") for v in row):
                continue
            d = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
            if is_sap:
                acc_nm = str(d.get("계정명") or "").strip()
                if not acc_nm:
                    continue
                # SAP: 금액 = 차변 - 대변 (현지통화 기준)
                debit = self._to_float(d.get("차변금액(현지통화)"))
                credit = self._to_float(d.get("대변금액(현지통화)"))
                amount = debit - credit
                # 표준 포맷으로 정규화하여 yield
                yield {
                    "계정 과목": acc_nm,
                    "거래처": acc_nm,   # 금융계정에서 거래처=계정명 (은행명 포함)
                    "금액": amount,
                    # 원본 필드도 보존
                    **{k: v for k, v in d.items()},
                }
            else:
                if not d.get("계정 과목"):
                    continue
                yield d
        wb.close()

    @staticmethod
    def _to_float(v) -> float:
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
