"""거래처명 매칭 — 정규화 → exact → fuzzy partial → fuzzy token_set.

정규화 대상:
  - 공백, 특수문자
  - ㈜, (주), 주식회사
  - 영문 법인 접미사: Co., Ltd., Inc., Corp., LLC, LLP
  - 대소문자 통일
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MatchResult:
    matched_name: Optional[str]    # 최종 매칭된 이름 (candidates 중 하나), 실패 시 None
    confidence: float              # 0.0 ~ 1.0
    method: str                    # "exact" | "fuzzy_partial" | "fuzzy_token" | "failed"
    candidates: list[str] = field(default_factory=list)  # top-3 후보 (failed 시 유용)


_STRIP_PATTERN = re.compile(
    r"[\s\-_]|㈜|\(주\)|주식회사|Co\.|Ltd\.|Inc\.|Corp\.|LLC|LLP",
    re.IGNORECASE,
)


def _normalize(name: str) -> str:
    """매칭용 정규화 — 공백·법인 접미사 제거, 소문자."""
    normalized = _STRIP_PATTERN.sub("", name)
    return normalized.lower().strip()


def match_party(extracted_name: str, candidates: list[str]) -> MatchResult:
    """extracted_name과 가장 유사한 후보를 candidates 중에서 찾는다.

    단계:
    1. 정규화 exact match  → confidence 1.0
    2. rapidfuzz partial_ratio ≥ 90 → confidence = score / 100
    3. rapidfuzz token_set_ratio ≥ 85 → confidence = score / 100
    4. 모두 실패 → top-3 후보 + 최고 score 반환 (confidence < 0.85)
    """
    if not candidates:
        return MatchResult(matched_name=None, confidence=0.0, method="failed")

    norm_query = _normalize(extracted_name)
    norm_map = {c: _normalize(c) for c in candidates}

    # 1. Exact
    for original, norm in norm_map.items():
        if norm == norm_query:
            return MatchResult(matched_name=original, confidence=1.0, method="exact")

    # rapidfuzz
    try:
        from rapidfuzz import fuzz, process  # type: ignore
    except ImportError:
        # rapidfuzz 미설치 — exact만 지원하고 실패 반환
        return MatchResult(
            matched_name=None, confidence=0.0, method="failed",
            candidates=candidates[:3],
        )

    # 2. Partial ratio
    scores_partial = [
        (cand, fuzz.partial_ratio(_normalize(extracted_name), _normalize(cand)))
        for cand in candidates
    ]
    scores_partial.sort(key=lambda x: x[1], reverse=True)
    best_partial_name, best_partial_score = scores_partial[0]

    if best_partial_score >= 90:
        return MatchResult(
            matched_name=best_partial_name,
            confidence=round(best_partial_score / 100, 4),
            method="fuzzy_partial",
            candidates=[c for c, _ in scores_partial[:3]],
        )

    # 3. Token set ratio
    scores_token = [
        (cand, fuzz.token_set_ratio(_normalize(extracted_name), _normalize(cand)))
        for cand in candidates
    ]
    scores_token.sort(key=lambda x: x[1], reverse=True)
    best_token_name, best_token_score = scores_token[0]

    if best_token_score >= 85:
        return MatchResult(
            matched_name=best_token_name,
            confidence=round(best_token_score / 100, 4),
            method="fuzzy_token",
            candidates=[c for c, _ in scores_token[:3]],
        )

    # 4. 실패 — top-3 반환
    all_scores = scores_partial  # partial이 더 직관적
    top3 = [c for c, _ in all_scores[:3]]
    best_score = all_scores[0][1] if all_scores else 0
    return MatchResult(
        matched_name=None,
        confidence=round(best_score / 100, 4),
        method="failed",
        candidates=top3,
    )
