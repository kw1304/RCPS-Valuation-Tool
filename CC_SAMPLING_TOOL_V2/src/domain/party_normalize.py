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
    # exact 매칭 우선
    for c in candidates:
        if normalize_party_name(c) == target:
            return c
    # partial — 긴 candidate 우선 (짧은 prefix가 긴 이름 가로채기 방지)
    # 예: "코스맥스" candidate가 "코스맥스펫(주)" filename에 매칭되어 잘못 잡히는 경우 방지
    sorted_cands = sorted(
        candidates,
        key=lambda c: -len(normalize_party_name(c) or "")
    )
    for c in sorted_cands:
        norm_c = normalize_party_name(c)
        if norm_c and norm_c in target:
            return c
    return None


def build_synonym_groups(party_lists: list[list[str]]) -> dict[str, str]:
    """동의어 그룹 — 한·영 같은 회사 매핑.

    Args:
        party_lists: 동일 회사로 간주할 이름 group의 list.
                      예: [["코스맥스비티아이", "Cosmax BTI"],
                            ["코스맥스", "Cosmax"], ...]

    Returns:
        정규화된 이름 → 그룹 대표 정규화 이름 dict.
        예: {"코스맥스비티아이": "코스맥스비티아이", "cosmaxbti": "코스맥스비티아이"}
    """
    out: dict[str, str] = {}
    for group in party_lists:
        if not group:
            continue
        # 한글 이름 우선 대표
        rep_norm = None
        for name in group:
            n = normalize_party_name(name)
            if not n:
                continue
            # 한글 포함 이름 우선
            if any('가' <= ch <= '힯' for ch in n):
                rep_norm = n
                break
        if rep_norm is None:
            rep_norm = normalize_party_name(group[0])
        for name in group:
            n = normalize_party_name(name)
            if n:
                out[n] = rep_norm
    return out


def canonical_party_key(
    name: str,
    business_number: Optional[str],
    synonym_map: dict[str, str],
) -> str:
    """거래처 매칭용 canonical key.

    우선순위:
    1. 사업자번호 있으면 그 번호 사용 (가장 신뢰성 높음)
    2. 정규화 이름이 synonym_map에 있으면 그룹 대표
    3. 정규화 이름 그대로
    """
    if business_number:
        return f"BN:{business_number}"
    n = normalize_party_name(name) if name else ""
    return synonym_map.get(n, n) if n else ""
