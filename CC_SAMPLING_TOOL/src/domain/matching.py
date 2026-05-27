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
    # 공백·특수문자
    r"[\s\-_]"
    # 한국 법인 접미사
    r"|㈜|\(주\)|주식회사|주식\s*회사|주식$|회사$"
    # 영문 법인 접미사 (순서 중요: 긴 패턴 먼저)
    r"|CO\.,?\s*LTD\.?|CO\s*,\s*LTD\.?"        # Co., Ltd. / Co.,Ltd / CO, LTD
    r"|CORPORATION|COMPANY"
    r"|LIMITED"
    r"|Co\.|Ltd\.|Inc\.|Corp\.|LLC|LLP"
    r"|Sdn\.|Bhd\.|SDN\.|BHD\.|Pty\.|PTY\."
    r"|Ltd$|Co$|Inc$|Corp$"
    # 점·쉼표 (법인 접미사 제거 후 남는 고립된 구두점)
    r"|[.,]",
    re.IGNORECASE,
)

# 별칭 사전 캐시
# normalized_alias → list[canonical_name]
# 동일 normalize key에 여러 canonical이 매핑될 수 있음 (예: "cosmax" → ["코스맥스㈜", "COSMAX INC", ...])
_ALIAS_CACHE: dict[str, list[str]] | None = None
# 직접 alias 역방향: normalized_alias → canonical (alias_list에 명시적으로 등록된 경우만)
# canonical 자신의 normalized key는 여기에 포함되지 않음
_ALIAS_DIRECT_CACHE: dict[str, str] | None = None
# 직접 alias 원문 길이 추적 (충돌 해소용): normalized_alias → len(alias_raw)
_ALIAS_DIRECT_LEN_CACHE: dict[str, int] | None = None
_ALIAS_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "party_aliases.yaml"


def _load_aliases() -> dict[str, list[str]]:
    """alias 사전 로드 — {normalized_alias: [canonical_name, ...]} 매핑 반환.

    동일 normalized key에 여러 canonical이 존재할 수 있으므로 list로 보관.
    candidates와 교집합으로 disambiguation.
    파일 없으면 빈 dict 반환 (graceful).
    """
    global _ALIAS_CACHE, _ALIAS_DIRECT_CACHE, _ALIAS_DIRECT_LEN_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE

    _ALIAS_CACHE = {}
    _ALIAS_DIRECT_CACHE = {}
    _ALIAS_DIRECT_LEN_CACHE = {}
    if not _ALIAS_CONFIG_PATH.exists():
        return _ALIAS_CACHE

    try:
        with open(_ALIAS_CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        aliases_section = config.get("aliases", {}) if config else {}
        for canonical, alias_list in aliases_section.items():
            if not alias_list:
                continue
            # canonical 자신도 등록 (일반 캐시에만)
            norm_c = _normalize(canonical)
            if norm_c not in _ALIAS_CACHE:
                _ALIAS_CACHE[norm_c] = []
            if canonical not in _ALIAS_CACHE[norm_c]:
                _ALIAS_CACHE[norm_c].append(canonical)
            for alias in alias_list:
                norm_a = _normalize(str(alias))
                if norm_a not in _ALIAS_CACHE:
                    _ALIAS_CACHE[norm_a] = []
                if canonical not in _ALIAS_CACHE[norm_a]:
                    _ALIAS_CACHE[norm_a].append(canonical)
                # 직접 alias 역방향 (canonical 자신 제외)
                if norm_a != norm_c:
                    alias_raw_len = len(str(alias))
                    if norm_a not in _ALIAS_DIRECT_CACHE:
                        _ALIAS_DIRECT_CACHE[norm_a] = canonical
                        _ALIAS_DIRECT_LEN_CACHE[norm_a] = alias_raw_len
                    else:
                        # 충돌 시: 더 긴 alias 원문 = 더 구체적 매핑 → 우선
                        prev_len = _ALIAS_DIRECT_LEN_CACHE.get(norm_a, 0)
                        if alias_raw_len > prev_len:
                            _ALIAS_DIRECT_CACHE[norm_a] = canonical
                            _ALIAS_DIRECT_LEN_CACHE[norm_a] = alias_raw_len
    except Exception:
        pass  # 파싱 실패 → 빈 사전으로 진행

    return _ALIAS_CACHE


def _load_direct_aliases() -> dict[str, str]:
    """직접 alias 역방향 사전 — alias_list에 명시된 항목만."""
    _load_aliases()  # 사이드 이펙트로 _ALIAS_DIRECT_CACHE 초기화
    return _ALIAS_DIRECT_CACHE or {}


def _lookup_alias(norm_query: str, candidates: list[str]) -> Optional[str]:
    """alias 사전에서 norm_query와 일치하는 canonical을 candidates 중에서 찾는다.

    전략:
    1. norm_query → canonicals 목록 조회
    2. 각 candidate를 역방향 조회: candidate의 모든 alias canonical이 norm_query 집합과 교집합이면 매칭
    3. candidates 중 원본 문자열이 canonical list에 있는 경우 우선 반환

    이렇게 하면 "COSMAX USA Corp." → candidates["COSMAX USA CORP", "코스맥스USA"] 중
    "COSMAX USA CORP"가 "COSMAX USA Corp."를 alias로 직접 보유하므로 우선 매칭.
    """
    aliases = _load_aliases()
    canonicals = aliases.get(norm_query)
    if not canonicals:
        return None

    norm_map = {c: _normalize(c) for c in candidates}
    canonical_norms = {_normalize(c) for c in canonicals}

    # 역방향: 각 candidate에서 해당 candidate가 보유한 canonical set과 교집합 확인
    # 동시에 candidate 자신이 canonical_norms에 있는지도 확인
    matched_cands: list[tuple[int, str]] = []  # (priority_score, candidate)

    for cand, norm_cand in norm_map.items():
        # candidate의 norm이 canonical_norms에 있으면 매칭
        if norm_cand in canonical_norms:
            # 우선순위: norm_query가 candidate_aliases에 직접 포함되어 있으면 score 높음
            cand_aliases = aliases.get(norm_cand, [])
            cand_alias_norms = set()
            for cc in cand_aliases:
                cand_alias_norms.add(_normalize(cc))

            # candidate 자신의 alias set이 norm_query를 포함하면 직접 매칭 (highest priority)
            if norm_query in cand_alias_norms:
                # candidate가 norm_query를 own alias로 가짐 → 가장 구체적
                matched_cands.append((2, cand))
            else:
                # candidate의 norm이 그냥 canonical_norms에 포함
                matched_cands.append((1, cand))

    if matched_cands:
        matched_cands.sort(key=lambda x: x[0], reverse=True)
        return matched_cands[0][1]

    return None


def reload_aliases() -> None:
    """별칭 사전 캐시 초기화 (파일 수정 후 리로드용)."""
    global _ALIAS_CACHE, _ALIAS_DIRECT_CACHE, _ALIAS_DIRECT_LEN_CACHE
    _ALIAS_CACHE = None
    _ALIAS_DIRECT_CACHE = None
    _ALIAS_DIRECT_LEN_CACHE = None


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

    norm_query = _normalize(extracted_name)
    norm_map = {c: _normalize(c) for c in candidates}

    # ── 2. 정적 alias 사전 ───────────────────────────────────────────────
    matched_from_alias = _lookup_alias(norm_query, candidates)
    if matched_from_alias:
        return MatchResult(matched_name=matched_from_alias, confidence=1.0, method="alias")

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
