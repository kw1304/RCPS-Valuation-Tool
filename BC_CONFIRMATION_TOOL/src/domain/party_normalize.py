import re
import yaml
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class NormalizedParty:
    canonical: str          # 국민은행
    branch: str | None      # None | "도쿄지점"
    is_foreign: bool
    raw: str

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
        canon = self._match_canonical(s) or s
        # Priority 1: foreign?
        foreign_marker = self._detect_foreign(s)
        if foreign_marker:
            # canonical + 도시지점 유지
            # branch 표현 통일: "<city>지점"
            ko_form = foreign_marker
            if foreign_marker.upper() in {c.upper() for c in self._foreign_en}:
                # English → 한글 변환 매핑 단순화 (City + 지점)
                # 한글 대응 없을 시 원문 + 지점
                ko_form = foreign_marker
            branch = f"{ko_form}지점" if not ko_form.endswith("지점") else ko_form
            return NormalizedParty(canonical=canon, branch=branch, is_foreign=True, raw=raw)
        # Priority 2: domestic branch → collapse
        if self._detect_domestic_branch(s):
            return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw)
        # Priority 3: bare canonical
        return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw)
