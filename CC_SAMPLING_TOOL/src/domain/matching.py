"""거래처명 매칭 — 별칭 사전 → 정규화 exact → fuzzy partial → fuzzy token_set.

정규화 대상:
  - 공백, 특수문자
  - ㈜, (주), 주식회사
  - 영문 법인 접미사: Co., Ltd., Inc., Corp., LLC, LLP, Sdn., Bhd., Pty., PTY., SDN., BHD.
  - 대소문자 통일

별칭 사전 (configs/party_aliases.yaml):
  - 한자·중국어 거래처명, 약칭, 복합 표기 등 포함
  - alias 매핑 → confidence 1.0 exact 처리
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml  # type: ignore


@dataclass
class MatchResult:
    matched_name: Optional[str]    # 최종 매칭된 이름 (candidates 중 하나), 실패 시 None
    confidence: float              # 0.0 ~ 1.0
    method: str                    # "alias" | "exact" | "fuzzy_partial" | "fuzzy_token" | "failed"
    candidates: list[str] = field(default_factory=list)  # top-3 후보 (failed 시 유용)


_STRIP_PATTERN = re.compile(
    r"[\s\-_]|㈜|\(주\)|주식회사|Co\.|Ltd\.|Inc\.|Corp\.|LLC|LLP"
    r"|Sdn\.|Bhd\.|SDN\.|BHD\.|Pty\.|PTY\.|Ltd$|Co$",
    re.IGNORECASE,
)

# 별칭 사전 캐시
_ALIAS_CACHE: dict[str, dict[str, str]] | None = None  # normalized_alias → canonical_name
_ALIAS_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "party_aliases.yaml"


def _load_aliases() -> dict[str, str]:
    """alias 사전 로드 — {normalized_alias: canonical_name} 매핑 반환.

    파일 없으면 빈 dict 반환 (graceful).
    """
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE

    _ALIAS_CACHE = {}
    if not _ALIAS_CONFIG_PATH.exists():
        return _ALIAS_CACHE

    try:
        with open(_ALIAS_CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        aliases_section = config.get("aliases", {}) if config else {}
        for canonical, alias_list in aliases_section.items():
            if not alias_list:
                continue
            # canonical 자신도 등록
            _ALIAS_CACHE[_normalize(canonical)] = canonical
            for alias in alias_list:
                _ALIAS_CACHE[_normalize(str(alias))] = canonical
    except Exception:
        pass  # 파싱 실패 → 빈 사전으로 진행

    return _ALIAS_CACHE


def reload_aliases() -> None:
    """별칭 사전 캐시 초기화 (파일 수정 후 리로드용)."""
    global _ALIAS_CACHE
    _ALIAS_CACHE = None


def _normalize(name: str) -> str:
    """매칭용 정규화 — 공백·법인 접미사 제거, 소문자."""
    normalized = _STRIP_PATTERN.sub("", name)
    return normalized.lower().strip()


def match_party(extracted_name: str, candidates: list[str]) -> MatchResult:
    """extracted_name과 가장 유사한 후보를 candidates 중에서 찾는다.

    단계:
    1. alias 사전 조회 — canonical 이름이 candidates에 있으면 confidence 1.0
    2. 정규화 exact match → confidence 1.0
    3. rapidfuzz partial_ratio ≥ 90 → confidence = score / 100
    4. rapidfuzz token_set_ratio ≥ 85 → confidence = score / 100
    5. 모두 실패 → top-3 후보 + 최고 score 반환 (confidence < 0.85)
    """
    if not candidates:
        return MatchResult(matched_name=None, confidence=0.0, method="failed")

    aliases = _load_aliases()
    norm_query = _normalize(extracted_name)
    norm_map = {c: _normalize(c) for c in candidates}

    # 1. alias 사전
    canonical = aliases.get(norm_query)
    if canonical:
        # canonical이 candidates에 직접 있는지 확인
        for cand in candidates:
            if _normalize(cand) == _normalize(canonical):
                return MatchResult(matched_name=cand, confidence=1.0, method="alias")
        # candidates에 canonical이 없어도 alias 자체를 정규화 exact로 추가 시도
        # (사전의 canonical이 candidates의 표기와 약간 다를 수 있음)
        for cand in candidates:
            cand_aliases_canonical = aliases.get(_normalize(cand))
            if cand_aliases_canonical and _normalize(cand_aliases_canonical) == _normalize(canonical):
                return MatchResult(matched_name=cand, confidence=1.0, method="alias")

    # candidates에서 alias를 통한 매핑 확인 (추출명이 alias고 candidates가 canonical)
    for cand, norm_cand in norm_map.items():
        cand_canonical = aliases.get(norm_cand)
        if cand_canonical:
            # cand의 canonical이 extracted_name과 매칭되는지
            if aliases.get(norm_query) and _normalize(aliases.get(norm_query, "")) == _normalize(cand_canonical):
                return MatchResult(matched_name=cand, confidence=1.0, method="alias")

    # 2. Exact
    for original, norm in norm_map.items():
        if norm == norm_query:
            return MatchResult(matched_name=original, confidence=1.0, method="exact")

    # rapidfuzz
    try:
        from rapidfuzz import fuzz  # type: ignore
    except ImportError:
        return MatchResult(
            matched_name=None, confidence=0.0, method="failed",
            candidates=candidates[:3],
        )

    # 3. Partial ratio
    scores_partial = [
        (cand, fuzz.partial_ratio(norm_query, _normalize(cand)))
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

    # 4. Token set ratio
    scores_token = [
        (cand, fuzz.token_set_ratio(norm_query, _normalize(cand)))
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

    # 5. 실패 — top-3 반환
    top3 = [c for c, _ in scores_partial[:3]]
    best_score = scores_partial[0][1] if scores_partial else 0
    return MatchResult(
        matched_name=None,
        confidence=round(best_score / 100, 4),
        method="failed",
        candidates=top3,
    )
