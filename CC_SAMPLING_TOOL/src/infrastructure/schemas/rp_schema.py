"""특관자리스트 시트명 자동 감지"""
from __future__ import annotations

from typing import Optional


_RP_SHEET_CANDIDATES = [
    "특관자리스트", "특수관계자리스트", "관계회사", "Related Parties", "RelatedParties",
    "특관자", "관계사",
]


def detect_rp_sheet(sheetnames: list[str]) -> Optional[str]:
    """특관자리스트 시트 감지. 정확매칭 우선."""
    normalized = {s.strip().lower().replace(" ", ""): s for s in sheetnames}

    for candidate in _RP_SHEET_CANDIDATES:
        key = candidate.lower().replace(" ", "")
        if key in normalized:
            return normalized[key]

    # 부분매칭
    for candidate in _RP_SHEET_CANDIDATES:
        key = candidate.lower().replace(" ", "")
        for norm, orig in normalized.items():
            if key in norm:
                return orig
    return None
