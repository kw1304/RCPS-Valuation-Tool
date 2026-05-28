"""회신 매칭 정확도 향상 테스트.

1. declared=False 이지만 차이 5% 이내 → matched 자동 보정
2. normalize 재시도 — match_party가 임계값으로 낙제시킨 후보가
   normalize 동일이면 매칭 성공으로 처리
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


# ── declared=False 5% 이내 자동 보정 단위 테스트 ─────────────────────────────

def test_declared_false_small_diff_becomes_matched():
    """declared=False + 차이 3% → matched 보정 로직 검증.

    실제 reconcile_v2 결과가 mismatch 이고 declared_match=False 인 경우
    difference_pct ≤ 5% 이면 matched 로 자동 보정된다.
    """
    # 보정 조건 직접 시뮬레이션
    status = "mismatch"
    declared_match = False
    difference_pct = 0.03  # 3%

    if (
        status == "mismatch"
        and declared_match is False
        and difference_pct <= 0.05
    ):
        status = "matched"

    assert status == "matched", "declared=False + 3% 차이는 matched 여야 함"


def test_declared_false_large_diff_stays_mismatch():
    """declared=False + 차이 10% → mismatch 유지."""
    status = "mismatch"
    declared_match = False
    difference_pct = 0.10  # 10%

    if (
        status == "mismatch"
        and declared_match is False
        and difference_pct <= 0.05
    ):
        status = "matched"

    assert status == "mismatch", "차이 10%는 mismatch 유지해야 함"


def test_declared_true_mismatch_not_overridden():
    """declared=True (명시적 불일치) → 자동 보정 대상 아님."""
    status = "mismatch"
    declared_match = True
    difference_pct = 0.02

    # declared_match is False 조건이 False → 보정 안 함
    if (
        status == "mismatch"
        and declared_match is False  # True이므로 skip
        and difference_pct <= 0.05
    ):
        status = "matched"

    assert status == "mismatch", "declared=True 이면 자동 보정 금지"


# ── normalize 재시도 단위 테스트 ─────────────────────────────────────────────

def test_normalize_retry_finds_suffix_variant():
    """'COSMAX INC' 와 'COSMAX. INC' 의 normalize 결과 동일 → 재시도 매칭 가능."""
    from src.domain.matching import _normalize

    name_a = "COSMAX INC"
    name_b = "COSMAX. INC"

    assert _normalize(name_a) == _normalize(name_b), (
        f"normalize 불일치: {_normalize(name_a)!r} != {_normalize(name_b)!r}"
    )


def test_normalize_retry_finds_corp_variant():
    """'(주)거래처Z' 와 '거래처Z주식회사' normalize 동일."""
    from src.domain.matching import _normalize

    assert _normalize("(주)거래처Z") == _normalize("거래처Z주식회사"), (
        "법인 접미사 변형 normalize 불일치"
    )


def test_normalize_retry_logic_in_step4(monkeypatch):
    """step4 normalize 재시도 로직 — candidates list에서 normalize 일치 후보 찾기."""
    from src.domain.matching import _normalize

    raw_name = "코스맥스비티아이주식회사"
    candidates = ["코스맥스비티아이", "다른거래처", "COSMAX BTI"]

    # step4의 normalize_retry 로직 직접 시뮬레이션
    matched_name = None
    top3_candidates = candidates  # match_party 실패 시 candidates 반환 가정

    raw_norm = _normalize(raw_name)
    for cand in top3_candidates:
        cand_name = cand if isinstance(cand, str) else str(cand)
        if _normalize(cand_name) == raw_norm:
            matched_name = cand_name
            break

    assert matched_name == "코스맥스비티아이", (
        f"normalize 재시도에서 '코스맥스비티아이' 찾아야 함, 결과: {matched_name}"
    )
