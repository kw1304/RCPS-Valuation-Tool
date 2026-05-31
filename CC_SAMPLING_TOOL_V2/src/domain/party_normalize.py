"""거래처명 정규화 + fuzzy 매칭.

회신서 양식에 흔한 (주)·주식회사 prefix·공백·대소문자 차이 흡수.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional


_SEP_RE = re.compile(r"[\s\+\-_.,()/&·㈜#%@$:;'\"!?\[\]{}]+")

# 괄호형 corp 마커 — 괄호와 함께 제거 (㈜·(주)·(유)·(株) 등).
# 반드시 괄호 컨텍스트로 제거 → "(광주)"의 "주"는 보존.
_PAREN_CORP_RE = re.compile(r"[\(（]\s*(?:주|유|합|株|有|有限公司|股份有限公司)\s*[\)）]|㈜")

# 단어형 corp 마커 — 구분자 제거·소문자 후 형태. 양끝(접두·접미)에서만, 최장 우선 제거.
# 글로벌 substring 치환 금지 (예: "광주"의 "주", "incheon"의 "inc" 오삭제 방지).
_CORP_WORDS = sorted({
    "주식회사", "유한회사", "합자회사", "유한책임회사", "유한공사",
    "有限公司", "股份有限公司",
    "corporation", "coltd", "coltd.", "corp", "incorporated", "inc",
    "limited", "ltd", "llc", "plc", "gmbh", "sa", "pteltd", "nv", "bv",
}, key=len, reverse=True)


def normalize_party_name(name: str) -> str:
    """거래처명 정규화: corp 마커 제거 + 공백/구분자 제거 + 영문 소문자.

    1) 괄호형 corp 마커((주)·㈜ 등)는 괄호째 제거 — "(광주)" 같은 지명은 보존.
    2) 구분자·공백 제거 + 소문자.
    3) 단어형 corp 접미·접두(주식회사·Co.,Ltd·Inc 등)는 **양끝에서만** 최장 우선 제거.
       글로벌 치환을 피해 "주식회사"의 "주", "vinci"의 "inc" 등 오삭제 방지.
    """
    s = _PAREN_CORP_RE.sub("", str(name)).lower()
    s = _SEP_RE.sub("", s)
    changed = True
    while changed and s:
        changed = False
        for w in _CORP_WORDS:
            if len(s) > len(w) and s.endswith(w):   # 접미 (전체가 마커면 보존)
                s = s[:-len(w)]
                changed = True
            if len(s) > len(w) and s.startswith(w):  # 접두
                s = s[len(w):]
                changed = True
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


_DEFAULT_SYNONYM_CACHE: Optional[dict[str, str]] = None


def load_default_synonyms() -> dict[str, str]:
    """default_aliases.yaml의 party_synonyms 섹션 → 정규화 이름 → 대표 dict.

    한 번만 로드 후 캐싱. 한·영·중 기본 별칭 사전.
    """
    global _DEFAULT_SYNONYM_CACHE
    if _DEFAULT_SYNONYM_CACHE is not None:
        return _DEFAULT_SYNONYM_CACHE
    try:
        import yaml
        cfg_path = (Path(__file__).resolve().parent.parent.parent
                    / "configs" / "schema_mapping" / "default_aliases.yaml")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        groups = cfg.get("party_synonyms") or []
        _DEFAULT_SYNONYM_CACHE = build_synonym_groups(groups)
    except Exception:
        _DEFAULT_SYNONYM_CACHE = {}
    return _DEFAULT_SYNONYM_CACHE


def merge_synonym_maps(*maps: dict[str, str]) -> dict[str, str]:
    """여러 synonym_map 머지. 뒤쪽 우선."""
    out: dict[str, str] = {}
    for m in maps:
        if m:
            out.update(m)
    return out


def canonical_party_key(
    name: str,
    business_number: Optional[str],
    synonym_map: dict[str, str],
) -> str:
    """거래처 매칭용 canonical key.

    우선순위:
    1. 사업자번호 있으면 사업자번호 — 가장 신뢰 가능한 법인 식별자.
       번호가 다르면 정규화 이름이 같아도 별개 법인이므로 병합하지 않음
       (브랜드 공유 모·자회사, 동명 이법인 오병합 방지).
    2. 사업자번호 없으면 정규화 이름이 synonym_map에 있으면 그룹 대표 이름.
       (주)·㈜·Co.,Ltd corp prefix + 공백 + 대소문자 차이 흡수, 한·영·중 synonym 적용.
    3. 정규화 이름 그대로.
    """
    bn = (business_number or "").strip()
    if bn:
        return f"BN:{bn}"
    n = normalize_party_name(name) if name else ""
    if n:
        return synonym_map.get(n, n)
    return ""
