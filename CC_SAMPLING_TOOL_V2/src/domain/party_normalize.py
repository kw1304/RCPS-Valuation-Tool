"""거래처명 정규화 + fuzzy 매칭.

회신서 양식에 흔한 (주)·주식회사 prefix·공백·대소문자 차이 흡수.
"""
from __future__ import annotations
import re
from typing import Optional


_CORP_PREFIXES = ["(주)", "(유)", "(합)", "주식회사", "유한회사", "합자회사"]


def normalize_party_name(name: str) -> str:
    """거래처명 정규화: corp prefix 제거 + 모든 공백 제거 + 영문 소문자."""
    s = name
    for p in _CORP_PREFIXES:
        s = s.replace(p, "")
    s = re.sub(r"\s+", "", s)
    s = s.lower()
    return s


def match_party(
    text_party: str,
    candidates: list[str],
) -> Optional[str]:
    """text_party (PDF에서 추출된 거래처명)를 candidates 중 매칭.

    Returns:
        매칭된 원본 candidate (정규화 X). 매칭 안 되면 None.
    """
    target = normalize_party_name(text_party)
    if not target:
        return None
    for c in candidates:
        if normalize_party_name(c) == target:
            return c
    for c in candidates:
        norm_c = normalize_party_name(c)
        if norm_c and norm_c in target:
            return c
    return None
