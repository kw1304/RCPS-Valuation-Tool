import re
import yaml
from dataclasses import dataclass
from pathlib import Path

# 금융기관 구조 접미사 — 미등록 기관도 이 토큰을 포함/종료하면 금융기관으로 인정.
# 긴 토큰이 짧은 토큰을 포함하는 경우가 있으므로 canonical 산출엔 영향 없음(이름 그대로 유지).
# 비금융(법무법인·회계법인·날짜·숫자·회사자기이름)은 이 목록에 포함하지 않는다.
_FIN_SUFFIX_TOKENS: tuple[str, ...] = (
    "화재해상보험", "손해보험", "보증보험", "저축은행", "상호금융",
    "금융투자", "투자운용", "자산운용", "공제조합", "협동조합",
    "은행", "뱅크", "증권", "생명보험", "생명", "화재", "해상", "손보",
    "공제회", "중앙회", "카드", "캐피탈", "신탁", "렌탈", "리스",
)

# 발행기관 없는 단독 계정과목 용어 — 금융기관으로 오인 금지
_GENERIC_ACCOUNT_TERMS: frozenset[str] = frozenset({
    "카드", "신용카드", "법인카드", "체크카드", "직불카드", "선불카드",
    "리스", "신탁", "렌탈", "보험", "예금", "적금", "보통예금", "당좌예금",
    "정기예금", "정기적금", "퇴직연금", "차입금", "대출", "사채", "보증금",
})

# 회사명 앞뒤 법인격 표기 제거용
_LEGAL_PREFIX_RE = re.compile(r"^(주식회사|유한회사|\(주\)|（주）|\(유\)|（유）)\s*")
_LEGAL_SUFFIX_RE = re.compile(r"\s*(주식회사|유한회사|\(주\)|（주）|\(유\)|（유）)$")
_WS_RE = re.compile(r"\s+")

@dataclass(frozen=True)
class NormalizedParty:
    canonical: str          # 국민은행
    branch: str | None      # None | "도쿄지점"
    is_foreign: bool
    raw: str
    matched: bool = False   # True iff canonical came from bank_aliases lookup

    def entity_key(self) -> str:
        return f"{self.canonical}|{self.branch or ''}"

class PartyNormalizer:
    def __init__(self, aliases: list[dict], domestic_locs: list[str], foreign_cities: dict):
        # aliases: [{canonical, aliases: [...]}, ...]
        # 긴 candidate 우선: canonical과 alias 모두를 길이순 정렬
        self._lookup: list[tuple[str, str]] = []
        for item in aliases:
            canon = item["canonical"]
            self._lookup.append((canon, canon))
            for a in item.get("aliases", []) or []:
                self._lookup.append((a, canon))
        self._lookup.sort(key=lambda t: len(t[0]), reverse=True)
        self._domestic = set(domestic_locs)
        self._foreign_ko = set(foreign_cities.get("ko", []))
        self._foreign_en = set(foreign_cities.get("en", []))
        self._foreign_generic = set(foreign_cities.get("generic", []))

    @classmethod
    def load(cls, cfg_dir: Path) -> "PartyNormalizer":
        with open(cfg_dir / "bank_aliases.yaml", encoding="utf-8") as f:
            aliases = yaml.safe_load(f)["financial_institutions"]
        with open(cfg_dir / "domestic_locations.yaml", encoding="utf-8") as f:
            domestic = yaml.safe_load(f)["domestic_locations"]
        with open(cfg_dir / "foreign_cities.yaml", encoding="utf-8") as f:
            foreign = yaml.safe_load(f)["foreign_cities"]
        return cls(aliases, domestic, foreign)

    def _match_canonical(self, text: str) -> str | None:
        for key, canon in self._lookup:
            if key in text:
                return canon
        return None

    @staticmethod
    def _clean_name(text: str) -> str:
        """법인격 표기(주식회사·(주)·（주） 등) 제거 + 내부 공백 1칸으로 정리."""
        s = _LEGAL_PREFIX_RE.sub("", text)
        s = _LEGAL_SUFFIX_RE.sub("", s)
        s = _WS_RE.sub(" ", s).strip()
        return s

    @staticmethod
    def _structural_canonical(text: str) -> str | None:
        """미등록 이름이 금융기관 접미사 토큰을 포함/종료하면 정리된 이름을 canonical로 반환.

        비금융(법무법인·회계법인·날짜·순수숫자)은 None.
        """
        cleaned = PartyNormalizer._clean_name(text)
        if not cleaned:
            return None
        # 비금융 배제: 법무법인/회계법인/세무법인, 날짜(2024-12-31), 순수 숫자
        if any(x in cleaned for x in ("법무법인", "회계법인", "세무법인", "노무법인", "특허법인")):
            return None
        if re.fullmatch(r"[\d\s.\-/]+", cleaned):
            return None
        # 일반 계정과목 단어(발행기관 없는 단독 용어) 배제 — 금융기관 아님
        if cleaned in _GENERIC_ACCOUNT_TERMS:
            return None
        # 구조매칭은 '이름 전체가 금융기관'일 때만 인정 — 적요(거래 메모) 오인 방지.
        # 조건: (1) 접미사 토큰으로 끝남, (2) 숫자 없음(날짜·금액 메모 배제),
        #       (3) 짧음(≤16자) + 공백 ≤1 (문장형 메모 배제).
        # 'OO은행 홍콩지점' 등 지점형은 _detect_foreign/_detect_domestic_branch + 등록 alias가 먼저 처리.
        if any(ch.isdigit() for ch in cleaned):
            return None
        if len(cleaned) > 16 or cleaned.count(" ") > 1:
            return None
        for tok in _FIN_SUFFIX_TOKENS:
            if cleaned.endswith(tok):
                return cleaned
        return None

    def _detect_foreign(self, text: str) -> str | None:
        """Returns the foreign city/marker found, or None."""
        # Korean foreign cities
        for c in self._foreign_ko:
            if c in text:
                return c
        # English foreign cities (case-insensitive)
        upper = text.upper()
        for c in self._foreign_en:
            if c.upper() in upper:
                return c
        # generic (Branch/Overseas)
        for c in self._foreign_generic:
            if c in text:
                return c
        return None

    def _detect_domestic_branch(self, text: str) -> bool:
        # 도시명 + (지점|점)?
        for loc in self._domestic:
            if loc in text:
                return True
        # "...지점" 만 단독 (외국 표지 없을 때) → 국내로 간주
        if "지점" in text:
            return True
        return False

    def normalize(self, raw: str) -> NormalizedParty:
        s = (raw or "").strip()
        # 1) curated lookup 우선 (longest-first)
        matched_canon = self._match_canonical(s)
        if matched_canon is not None:
            canon = matched_canon
            matched = True
        else:
            # 2) 구조 접미사 fallback — 미등록 금융기관도 인정
            struct = self._structural_canonical(s)
            if struct is not None:
                canon = struct
                matched = True
            else:
                canon = s
                matched = False
        # Priority 1: foreign?
        foreign_marker = self._detect_foreign(s)
        if foreign_marker:
            # canonical + 도시지점 유지
            # branch 표현 통일: "<city>지점"
            ko_form = foreign_marker
            if foreign_marker.upper() in {c.upper() for c in self._foreign_en}:
                ko_form = foreign_marker
            branch = f"{ko_form}지점" if not ko_form.endswith("지점") else ko_form
            return NormalizedParty(canonical=canon, branch=branch, is_foreign=True, raw=raw, matched=matched)
        # Priority 2: domestic branch → collapse
        if self._detect_domestic_branch(s):
            return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw, matched=matched)
        # Priority 3: bare canonical
        return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw, matched=matched)
