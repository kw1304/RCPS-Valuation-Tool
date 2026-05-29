"""우편/unknown 양식 best-effort 파서. 모든 레코드 needs_manual_review=True.

억지 자동화로 틀린 숫자를 넣지 않는다 — 감사인 직접 확인용 후보만 추출.
"""
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

_AC_KEYWORDS = {
    "AC1": ["예금", "deposit", "잔액", "balance", "유가증권", "주식", "펀드"],
    "AC2": ["대출", "차입", "loan", "borrowing"],
    "AC4": ["지급보증", "보증", "guarantee", "L/C"],
    "AC5": ["담보", "근저당", "collateral"],
    "AC6": ["어음", "수표", "당좌"],
    "AC7": ["보험", "insurance"],
}


def fallback_parse(text: str, bc_no: str, bank: str) -> list[dict]:
    out: list[dict] = []
    for line in text.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        ac = "AC1"
        for cand, kws in _AC_KEYWORDS.items():
            if any(k in s for k in kws):
                ac = cand
                break
        out.append({
            "ac_section": ac,
            "payload": {"bc_no": bc_no, "bank": bank, "raw": s[:120],
                        "amounts": [str(a) for a in t.amounts],
                        "currency": t.currency},
            "needs_manual_review": True,
        })
    return out
