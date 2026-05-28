"""Excel 원장·시트 자동감지·로드.

설계서 §6.1 [2]. confidence < 0.95이면 UI 매핑확인 차단 (호출자 책임).
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Literal
import yaml
import openpyxl
from src.domain.entities import Account


MappingConfidence = float
_CFG_PATH = Path(__file__).resolve().parent.parent.parent.parent / \
    "configs" / "schema_mapping" / "default_aliases.yaml"


def _load_aliases() -> dict:
    with open(_CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


_ALIASES = _load_aliases()


def detect_sheet_kind(sheet_name: str) -> Optional[Literal["AR","AP","FS","RP","ALLOWANCE"]]:
    """시트명에서 종류 추정. alias 정확 or 포함 매칭."""
    name = sheet_name.strip().lower()
    for kind, aliases in _ALIASES["sheets"].items():
        for a in aliases:
            if a.lower() == name or a.lower() in name:
                return kind
    return None


def detect_columns(headers: list[Optional[str]]) -> tuple[dict[str, int], MappingConfidence]:
    """헤더 행에서 컬럼명 → index 매핑.

    2-pass 알고리즘:
      1차 — exact match (alias == header) 우선 배정. 짧은 alias가 긴 헤더에
           오매칭되는 문제 방지 (예: "거래처" alias가 "거래처코드" 헤더에).
      2차 — 1차에서 미배정된 필드를 partial(substring) match로 채움.
           단, 이미 다른 필드가 차지한 column index는 재사용 금지.

    Returns:
        (mapping, confidence). confidence = 발견된 필수컬럼 / 총 필수 (5개).
    """
    required = ["party_id", "name", "gl_account", "balance", "ccy"]
    mapping: dict[str, int] = {}
    used_idx: set[int] = set()
    norm_headers = [(h or "").strip().lower() for h in headers]

    # 1차: exact match
    for field, aliases in _ALIASES["columns"].items():
        norm_aliases = [a.lower() for a in aliases]
        for idx, h in enumerate(norm_headers):
            if idx in used_idx or not h:
                continue
            if any(a == h for a in norm_aliases):
                mapping[field] = idx
                used_idx.add(idx)
                break

    # 2차: partial match (substring) — 1차 누락 보완
    for field, aliases in _ALIASES["columns"].items():
        if field in mapping:
            continue
        norm_aliases = [a.lower() for a in aliases]
        for idx, h in enumerate(norm_headers):
            if idx in used_idx or not h:
                continue
            if any(a in h for a in norm_aliases):
                mapping[field] = idx
                used_idx.add(idx)
                break

    found_required = sum(1 for f in required if f in mapping)
    confidence = found_required / len(required)
    return mapping, confidence


def load_account_sheet(
    path: Path,
    sheet_name: str,
) -> tuple[list[Account], dict]:
    """엑셀 시트에서 Account 목록 + meta 반환.

    Returns:
        (accounts, meta). meta = {sheet_kind, confidence, mapping}.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"sheet {sheet_name!r} not found in {path}")
    ws = wb[sheet_name]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], {"sheet_kind": None, "confidence": 0.0, "mapping": {}}

    headers = list(rows[0])
    mapping, confidence = detect_columns(headers)
    sheet_kind = detect_sheet_kind(sheet_name)

    accounts: list[Account] = []
    for r_idx, row in enumerate(rows[1:], start=2):
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
            continue
        if "balance" not in mapping:
            break
        # name 또는 party_id 둘 중 하나는 있어야 매칭 가능
        if "party_id" not in mapping and "name" not in mapping:
            break

        def cell(field, default=None):
            i = mapping.get(field)
            if i is None or i >= len(row):
                return default
            v = row[i]
            return default if v is None else v

        party_id = str(cell("party_id", "")).strip()
        name = str(cell("name", "")).strip()
        # party_id 없으면 name으로 식별 (fuzzy 집계 단계에서 통합 매칭됨)
        if not party_id and not name:
            continue
        # skip summary/subtotal rows
        if party_id in {"합계", "소계", "계", "Total", "total", "TOTAL", "Subtotal", "subtotal"}:
            continue
        if name in {"합계", "소계", "계", "Total", "total", "TOTAL", "Subtotal", "subtotal"}:
            continue
        gl_account = str(cell("gl_account", "")).strip()
        balance_orig = float(cell("balance", 0) or 0)
        business_number = str(cell("business_number", "") or "").strip() or None
        ccy = str(cell("ccy", "KRW")).strip() or "KRW"
        fx_rate = float(cell("fx_rate", 1.0) or 1.0)
        balance_krw = balance_orig * fx_rate
        debit_amt = float(cell("debit", 0) or 0) * fx_rate
        credit_amt = float(cell("credit", 0) or 0) * fx_rate

        accounts.append(Account(
            party_id=party_id, name=name, gl_account=gl_account,
            balance_orig=balance_orig, ccy=ccy, fx_rate=fx_rate,
            balance_krw=balance_krw,
            aging_bucket=str(cell("aging", "")).strip() or None,
            allowance_amt=float(cell("allowance", 0) or 0),
            src_sheet=sheet_name, src_row=r_idx,
            debit_amt=debit_amt, credit_amt=credit_amt,
            business_number=business_number,
            account_breakdowns={sheet_name: balance_krw},
        ))

    return accounts, {
        "sheet_kind": sheet_kind,
        "confidence": confidence,
        "mapping": mapping,
    }
