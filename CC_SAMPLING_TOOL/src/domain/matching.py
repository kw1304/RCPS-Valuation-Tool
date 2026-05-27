"""거래처명 매칭 — 별칭 사전 → 정규화 exact → fuzzy partial → fuzzy token_set.

정규화 대상:
  - 공백, 특수문자
  - ㈜, (주), 주식회사
  - 영문 법인 접미사: Co., Ltd., Inc., Corp., LLC, LLP, Sdn., Bhd., Pty., PTY., SDN., BHD.
  - 대소문자 통일

별칭 사전 (configs/party_aliases.yaml):
  - 한자·중국어 거래처명, 약칭, 복합 표기 등 포함
  - alias 매핑 → confidence 1.0 exact 처리

Week 5 강화:
  - UploadGuide 동적 alias (거래처 PartyContact.name ↔ candidates 자동 연결)
  - 사업자번호 exact 매칭
  - 파일명 기반 CJK 자동 매칭
  - CJK 음독 힌트 기반 fuzzy 매칭
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml  # type: ignore

if TYPE_CHECKING:
    from src.infrastructure.loaders import UploadGuideData


@dataclass
class MatchResult:
    matched_name: Optional[str]    # 최종 매칭된 이름 (candidates 중 하나), 실패 시 None
    confidence: float              # 0.0 ~ 1.0
    method: str                    # "alias" | "exact" | "fuzzy_partial" | "fuzzy_token" | "cjk" | "failed"
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


def _build_upload_guide_aliases(
    upload_guide_data,
    candidates: list[str],
) -> dict[str, str]:
    """UploadGuide.send_targets에서 candidates와 연결되는 동적 alias 구축.

    - PartyContact.name이 candidates에 있으면 → 그 이름 자체가 canonical
    - PartyContact.name이 candidates에 없으면 → 정규화 fuzzy로 찾아 연결
    반환: {normalized_alias → canonical_name}
    """
    if upload_guide_data is None:
        return {}

    result: dict[str, str] = {}
    try:
        from rapidfuzz import fuzz as _fuzz
        has_rapidfuzz = True
    except ImportError:
        has_rapidfuzz = False

    norm_cands = {c: _normalize(c) for c in candidates}

    for contact in upload_guide_data.send_targets:
        name = contact.name
        norm_name = _normalize(name)

        # 1. 직접 exact
        if norm_name in {v for v in norm_cands.values()}:
            result[norm_name] = name
            continue

        # 2. fuzzy partial ≥ 90
        if has_rapidfuzz:
            for cand, norm_cand in norm_cands.items():
                score = _fuzz.partial_ratio(norm_name, norm_cand)
                if score >= 90:
                    result[norm_name] = cand
                    break

    return result


def _build_filename_cjk_aliases(filename_hint: str, candidates: list[str]) -> dict[str, str]:
    """파일명에서 CJK 블록을 추출 → candidates 중 CJK 포함 거래처와 매핑.

    예: "CC-19_科丝美诗（中国）化妆品有限公司.pdf"
        → CJK block = "科丝美诗中国化妆品有限公司"
        → candidates 중 "科丝美诗" 포함 거래처와 매핑
    """
    from .cjk_normalizer import extract_cjk_block, looks_like_chinese

    if not filename_hint:
        return {}

    fname_cjk = extract_cjk_block(filename_hint)
    if not fname_cjk or len(fname_cjk) < 3:
        return {}

    result: dict[str, str] = {}
    for cand in candidates:
        cand_cjk = extract_cjk_block(cand)
        if not cand_cjk:
            continue
        # CJK 블록의 공통 부분 비율
        shorter = min(len(fname_cjk), len(cand_cjk))
        if shorter < 2:
            continue
        common = sum(1 for c in cand_cjk if c in fname_cjk)
        ratio = common / max(len(cand_cjk), 1)
        if ratio >= 0.6:
            result[_normalize(fname_cjk)] = cand
            result[_normalize(filename_hint)] = cand
    return result


def match_party(
    extracted_name: str,
    candidates: list[str],
    upload_guide_data=None,
    business_no: Optional[str] = None,
    filename_hint: Optional[str] = None,
) -> MatchResult:
    """extracted_name과 가장 유사한 후보를 candidates 중에서 찾는다.

    단계 (우선순위순):
    1. business_no exact → UploadGuide.send_targets 에서 사업자번호 역조회
    2. alias 사전 조회 — canonical 이름이 candidates에 있으면 confidence 1.0
    3. UploadGuide 동적 alias (PartyContact.name ↔ candidates 자동 연결)
    4. filename 기반 CJK 자동 alias (한자 파일명 → CJK 포함 candidates 매핑)
    5. 정규화 exact match → confidence 1.0
    6. rapidfuzz partial_ratio ≥ 90 → confidence = score / 100
    7. rapidfuzz token_set_ratio ≥ 85 → confidence = score / 100
    8. CJK 음독 힌트 기반 fuzzy (한자 거래처 전용)
    9. 모두 실패 → top-3 후보 + 최고 score 반환 (confidence < 0.85)

    Args:
        extracted_name:    PDF/텍스트에서 추출된 거래처명
        candidates:        Step 1 final_sampled 거래처명 목록
        upload_guide_data: UploadGuideData (선택 — 동적 alias 및 사업자번호 역조회용)
        business_no:       PDF에서 추출된 사업자번호 (선택)
        filename_hint:     PDF 파일명 (CJK 자동 매핑용, 선택)
    """
    if not candidates:
        return MatchResult(matched_name=None, confidence=0.0, method="failed")

    # ── 1. 사업자번호 exact ───────────────────────────────────────────────
    if business_no and upload_guide_data is not None:
        bn_clean = re.sub(r"[-\s]", "", business_no)
        for contact in upload_guide_data.send_targets:
            contact_bn = re.sub(r"[-\s]", "", contact.business_no or "")
            if contact_bn and contact_bn == bn_clean:
                # contact.name이 candidates에 있는지 확인
                for cand in candidates:
                    if _normalize(cand) == _normalize(contact.name):
                        return MatchResult(matched_name=cand, confidence=1.0, method="alias")

    aliases = _load_aliases()
    norm_query = _normalize(extracted_name)
    norm_map = {c: _normalize(c) for c in candidates}

    # ── 2. 정적 alias 사전 ───────────────────────────────────────────────
    canonical = aliases.get(norm_query)
    if canonical:
        for cand in candidates:
            if _normalize(cand) == _normalize(canonical):
                return MatchResult(matched_name=cand, confidence=1.0, method="alias")
        for cand in candidates:
            cand_aliases_canonical = aliases.get(_normalize(cand))
            if cand_aliases_canonical and _normalize(cand_aliases_canonical) == _normalize(canonical):
                return MatchResult(matched_name=cand, confidence=1.0, method="alias")

    # candidates에서 alias를 통한 매핑 확인
    for cand, norm_cand in norm_map.items():
        cand_canonical = aliases.get(norm_cand)
        if cand_canonical:
            if aliases.get(norm_query) and _normalize(aliases.get(norm_query, "")) == _normalize(cand_canonical):
                return MatchResult(matched_name=cand, confidence=1.0, method="alias")

    # ── 3. UploadGuide 동적 alias ────────────────────────────────────────
    if upload_guide_data is not None:
        dyn_aliases = _build_upload_guide_aliases(upload_guide_data, candidates)
        dyn_canonical = dyn_aliases.get(norm_query)
        if dyn_canonical:
            return MatchResult(matched_name=dyn_canonical, confidence=0.95, method="alias")

    # ── 4. 파일명 CJK 자동 alias ─────────────────────────────────────────
    if filename_hint:
        fname_aliases = _build_filename_cjk_aliases(filename_hint, candidates)
        # extracted_name 기반 조회
        fn_cand = fname_aliases.get(norm_query)
        if fn_cand:
            return MatchResult(matched_name=fn_cand, confidence=0.92, method="alias")
        # 파일명 직접 조회
        fn_cand2 = fname_aliases.get(_normalize(filename_hint))
        if fn_cand2:
            return MatchResult(matched_name=fn_cand2, confidence=0.90, method="alias")

    # ── 5. Exact ─────────────────────────────────────────────────────────
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

    # ── 6. Partial ratio ────────────────────────────────────────────────
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

    # ── 7. Token set ratio ──────────────────────────────────────────────
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

    # ── 8. CJK 음독 힌트 기반 fuzzy ─────────────────────────────────────
    from .cjk_normalizer import looks_like_chinese, cjk_to_korean_hint

    if looks_like_chinese(extracted_name):
        hint_str = cjk_to_korean_hint(extracted_name)
        if hint_str:
            norm_hint = _normalize(hint_str)
            hint_scores = [
                (cand, fuzz.partial_ratio(norm_hint, _normalize(cand)))
                for cand in candidates
            ]
            hint_scores.sort(key=lambda x: x[1], reverse=True)
            best_hint_name, best_hint_score = hint_scores[0]
            if best_hint_score >= 80:
                return MatchResult(
                    matched_name=best_hint_name,
                    confidence=round(best_hint_score / 100 * 0.9, 4),  # 신뢰도 10% 할인
                    method="cjk",
                    candidates=[c for c, _ in hint_scores[:3]],
                )

    # ── 9. 실패 — top-3 반환 ────────────────────────────────────────────
    top3 = [c for c, _ in scores_partial[:3]]
    best_score = scores_partial[0][1] if scores_partial else 0
    return MatchResult(
        matched_name=None,
        confidence=round(best_score / 100, 4),
        method="failed",
        candidates=top3,
    )
