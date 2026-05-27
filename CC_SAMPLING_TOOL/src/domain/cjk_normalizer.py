"""CJK(한자·중국어·일본어) 문자 처리 — 거래처명 매칭 보조.

한자 거래처 (科丝美诗·山东 등) 가 PDF/파일명에서 추출될 때
candidates 목록의 한국어·영문 표기와 매칭하기 위한 유틸리티.

설계 원칙:
  - 음독(音読) 변환은 코스맥스 그룹 특화 사전만 포함 (오탐 최소화)
  - 외부 라이브러리 의존 없이 순수 정규식 기반
  - CJK 비율 계산으로 "이 이름이 한자인지" 빠르게 판별
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


# ── CJK 유니코드 범위 ──────────────────────────────────────────────────────────
# CJK Unified Ideographs (4E00–9FFF) + Extension A (3400–4DBF)
# + Compatibility Ideographs (F900–FAFF)
_CJK_RANGES = [
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),  # CJK Extension B
]


def _is_cjk_char(char: str) -> bool:
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def extract_cjk_block(name: str) -> str:
    """이름에서 CJK 문자만 추출 (공백·괄호·알파벳 제거)."""
    return "".join(c for c in name if _is_cjk_char(c))


def looks_like_chinese(name: str) -> bool:
    """이름의 CJK 문자 비율이 30% 이상이면 한자/중문 이름으로 판정."""
    if not name:
        return False
    total = len(name.replace(" ", ""))
    if total == 0:
        return False
    cjk_count = sum(1 for c in name if _is_cjk_char(c))
    return (cjk_count / total) >= 0.30


# ── 코스맥스 그룹 특화 음독 사전 ───────────────────────────────────────────────
# key: CJK 원문(정규화 후) → value: 한국어/영문 힌트 목록
_CJK_HINT_MAP: dict[str, list[str]] = {
    # 科丝美诗 = 코스맥스(COSMAX)의 중국어 음역
    "科丝美诗": ["코스맥스", "COSMAX", "cosmax"],
    "科絲美詩": ["코스맥스", "COSMAX"],
    # 国 variants
    "中国": ["중국", "China"],
    "广州": ["광주", "Guangzhou"],
    # 山东昆达 = 산둥쿤다
    "山东昆达": ["산둥쿤다", "산동쿤다"],
    "山東昆達": ["산둥쿤다", "산동쿤다"],
    "昆达": ["쿤다"],
    # 山东瑞诺 = 산둥루이눠
    "山东瑞诺": ["산둥루이눠", "산동루이놔"],
    "瑞诺": ["루이눠", "루이놔"],
    # 有限公司 = 유한공사
    "有限公司": ["유한공사", "Co.,Ltd"],
    "化妆品": ["화장품", "cosmetics"],
    "化妝品": ["화장품", "cosmetics"],
    "生物科技": ["바이오텍", "biotech"],
}


def cjk_to_korean_hint(name: str) -> Optional[str]:
    """CJK 이름에서 한국어/영문 힌트 문자열 반환.

    사전에 등록된 키워드가 포함되어 있으면 해당 힌트들을 공백으로 이어 반환.
    매핑 없으면 None.
    """
    hints: list[str] = []
    for cjk_key, hint_list in _CJK_HINT_MAP.items():
        if cjk_key in name:
            hints.extend(hint_list)
    return " ".join(hints) if hints else None


def normalize_for_cjk_match(name: str) -> str:
    """CJK 매칭용 정규화 — 괄호·공백·법인 접미사 제거 후 NFKC 정규화."""
    # 전각 괄호 → 반각
    name = name.replace("（", "(").replace("）", ")")
    # 법인 접미사 제거
    name = re.sub(
        r"有限公司|株式会社|유한공사|주식회사|\(주\)|㈜|Co\.,\s*Ltd\.?|Ltd\.?|Inc\.?",
        "",
        name,
        flags=re.IGNORECASE,
    )
    # 괄호 내용 포함 제거 (회사명 본체만 남기기)
    # 단, 国·州 등 지명은 유지
    name = re.sub(r"\([^)]{6,}\)", "", name)  # 6자 이상 괄호 내용 제거
    # NFKC 정규화 (전각→반각, 호환 한자 통일)
    name = unicodedata.normalize("NFKC", name)
    return name.strip()
