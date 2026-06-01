import re
import yaml
from dataclasses import dataclass
from pathlib import Path

# 금융기관 구조 접미사 — 미등록 기관도 이 토큰을 포함/종료하면 금융기관으로 인정.
# 긴 토큰이 짧은 토큰을 포함하는 경우가 있으므로 canonical 산출엔 영향 없음(이름 그대로 유지).
# 비금융(법무법인·회계법인·날짜·숫자·회사자기이름)은 이 목록에 포함하지 않는다.
_FIN_SUFFIX_TOKENS: tuple[str, ...] = (
    "화재해상보험", "손해보험", "보증보험", "저축은행", "상호금융",
    "금융투자", "투자운용", "자산운용", "공제조합",
    "은행", "증권", "생명보험", "생명", "화재해상", "화재", "손보",
    "공제회", "중앙회", "카드", "캐피탈", "신탁",
)
# 제거된 과광범 토큰: '뱅크'(인포뱅크·이씨뱅크 등 IT/SMS사) → 인터넷은행은 등록 alias로,
# '렌탈'(기창렌탈 등 장비렌탈), '협동조합'(언론·일반 협동조합) — 금융기관 아닌 오인 다수.

# 발행기관 없는 단독 계정과목 용어 — 금융기관으로 오인 금지
_GENERIC_ACCOUNT_TERMS: frozenset[str] = frozenset({
    "카드", "신용카드", "법인카드", "체크카드", "직불카드", "선불카드",
    "리스", "신탁", "렌탈", "보험", "예금", "적금", "보통예금", "당좌예금",
    "정기예금", "정기적금", "퇴직연금", "차입금", "대출", "사채", "보증금",
})

# 비금융 상호 표지 — 짧은 alias(국민/우리/하나/신한/KB 등)가 비금융 회사명에
# 부분일치(국민연금공단·우리들병원·하나투어·신한금융지주·KB부동산)하는 오탐 차단.
# 짧은 alias 매칭 시 이 토큰이 텍스트에 있으면 금융기관 인정을 기각한다.
# (긴 정식명 '국민은행'이 같이 있으면 longest-first로 그게 먼저 매칭되어 veto 안 탐)
_NONFINANCIAL_VETO: tuple[str, ...] = (
    "연금공단", "공단", "병원", "의원", "약국", "투어", "여행사", "항공",
    "지주", "홀딩스", "부동산", "건설", "산업개발", "서비스", "시스템",
    "텔레콤", "전자", "화학", "제약", "바이오", "물산", "상사", "유통",
    "백화점", "마트", "대학교", "학교", "재단", "협회", "교회", "호텔", "리조트",
)

# 짧은 은행 alias가 매칭됐으나 텍스트가 은행 아닌 금융 접미사로 끝나면(예: 'JB우리캐피탈')
# 본점 은행으로 오병합 말고 구조매칭(별도 entity)에 양보할 토큰.
_NON_BANK_FIN_SUFFIX: tuple[str, ...] = (
    "캐피탈", "캐피털", "카드", "저축은행", "증권", "생명", "화재", "손해보험",
)

# 해외도시 영문·변형 → canonical 한글 (HK지점·홍콩지점 통합 등). key는 .upper() 기준(한글은 그대로).
_CITY_CANON: dict[str, str] = {
    "HK": "홍콩", "HONGKONG": "홍콩", "HONG KONG": "홍콩", "홍콩": "홍콩",
    "SH": "상해", "SHANGHAI": "상해", "상하이": "상해", "상해": "상해",
    "SG": "싱가포르", "SINGAPORE": "싱가포르", "싱가폴": "싱가포르", "싱가포르": "싱가포르",
    "NY": "뉴욕", "NEWYORK": "뉴욕", "NEW YORK": "뉴욕", "뉴욕": "뉴욕",
    "TOKYO": "도쿄", "도쿄": "도쿄", "동경": "도쿄",
    "LONDON": "런던", "런던": "런던",
    "BJ": "베이징", "BEIJING": "베이징", "베이징": "베이징", "북경": "베이징",
    "LA": "로스앤젤레스", "로스앤젤레스": "로스앤젤레스",
    "PARIS": "파리", "파리": "파리",
    "FRANKFURT": "프랑크푸르트", "프랑크푸르트": "프랑크푸르트",
    "SYDNEY": "시드니", "시드니": "시드니", "DUBAI": "두바이", "두바이": "두바이",
    "JAKARTA": "자카르타", "자카르타": "자카르타", "HANOI": "하노이", "하노이": "하노이",
    "HO CHI MINH": "호치민", "호치민": "호치민", "BANGKOK": "방콕", "방콕": "방콕",
    "KL": "쿠알라룸푸르", "쿠알라룸푸르": "쿠알라룸푸르", "MANILA": "마닐라", "마닐라": "마닐라",
    "ZURICH": "취리히", "취리히": "취리히", "MUMBAI": "뭄바이", "뭄바이": "뭄바이",
    "ISTANBUL": "이스탄불", "이스탄불": "이스탄불", "MOSCOW": "모스크바", "모스크바": "모스크바",
    "SAO PAULO": "상파울루", "상파울루": "상파울루", "TORONTO": "토론토", "토론토": "토론토",
    "VANCOUVER": "밴쿠버", "밴쿠버": "밴쿠버",
    "OSAKA": "오사카", "오사카": "오사카", "CHICAGO": "시카고", "시카고": "시카고",
    "GUANGZHOU": "광저우", "광저우": "광저우", "QINGDAO": "칭다오", "칭다오": "칭다오",
    "TIANJIN": "톈진", "톈진": "톈진", "DANANG": "다낭", "다낭": "다낭",
    "PHNOM PENH": "프놈펜", "프놈펜": "프놈펜", "YANGON": "양곤", "양곤": "양곤",
    "CHENNAI": "첸나이", "첸나이": "첸나이", "MELBOURNE": "멜버른", "멜버른": "멜버른",
    "CHENGDU": "청두", "청두": "청두", "DALIAN": "다롄", "다롄": "다롄",
}

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
        cleaned = self._clean_name(text)
        for key, canon in self._lookup:
            if key not in text:
                continue
            # (1) 비금융 상호 표지로 끝나면 기각 (삼성생명서비스·신한금융지주·우리들병원·하나투어).
            #     긴 정식명도 적용 — '삼성생명'(O) vs '삼성생명서비스'(X) 구분.
            if cleaned.endswith(_NONFINANCIAL_VETO):
                continue
            # (2) 짧은 alias(≤3자)는 비금융 부분일치 위험 ↑ → 표지가 어디든 있으면 기각
            #     (국민연금공단·KB부동산 — veto 토큰이 끝이 아니어도 차단)
            if len(key) <= 3 and any(v in cleaned for v in _NONFINANCIAL_VETO):
                continue
            # (3) 짧은 은행 alias인데 비은행 금융 접미사로 끝나면 오병합 방지
            #     (JB우리캐피탈→우리은행 X). 구조매칭이 별도 entity로 처리하도록 양보.
            if len(key) <= 3 and canon.endswith("은행") and cleaned.endswith(_NON_BANK_FIN_SUFFIX):
                continue
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
        # English foreign cities (case-insensitive).
        # 짧은 약자(HK/SH/SG/NY/BJ/LA/KL 등 ≤3자)는 단어경계 필요 — 'SHINHAN'의 SH, 'SHB'의 SH 오탐 방지.
        upper = text.upper()
        for c in self._foreign_en:
            cu = c.upper()
            if len(cu.replace(" ", "")) <= 3:
                if re.search(r"(?<![A-Z])" + re.escape(cu) + r"(?![A-Z])", upper):
                    return c
            elif cu in upper:
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
            # branch 표현 통일: 영문·변형 도시명 → canonical 한글 (HK·홍콩 통합), "<city>지점"
            ko_form = _CITY_CANON.get(foreign_marker.upper(), foreign_marker)
            branch = f"{ko_form}지점" if not ko_form.endswith("지점") else ko_form
            return NormalizedParty(canonical=canon, branch=branch, is_foreign=True, raw=raw, matched=matched)
        # Priority 2: domestic branch → collapse
        if self._detect_domestic_branch(s):
            return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw, matched=matched)
        # Priority 3: bare canonical
        return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw, matched=matched)
