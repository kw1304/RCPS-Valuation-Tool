import pytest
from src.domain.entities import Kind
from src.domain.projection.pps import (
    tainting, project_misstatement,
)


def test_tainting_full():
    # book < interval → tainting = ms/book
    t = tainting(misstatement=500, book=1000, sampling_interval=10_000)
    assert t == 0.5


def test_tainting_key_item_full_misstatement():
    # book >= interval (key item) → 자체 추정, tainting 개념 미적용
    # 반환은 None — 구현 결정 (key item 분기 표시)
    t = tainting(misstatement=500, book=20_000, sampling_interval=10_000)
    assert t is None


def test_tainting_zero_misstatement():
    t = tainting(misstatement=0, book=1000, sampling_interval=10_000)
    assert t == 0.0


def test_project_within_tolerable():
    # 표본 1건 오차 100, book 500, interval 10000
    # tainting=0.2, projected=2000, basic_precision = 3.0 × 10000 = 30000
    # upper = 2000 + 30000 + incremental≈0 = 32000 < tolerable 50000
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=50_000,
        sampled_misstatements=[(100, 500)],  # [(ms_amt, book)]
    )
    assert result.kind == Kind.AR
    assert result.verdict == "WITHIN_TOLERABLE"
    assert result.upper_limit < 50_000


def test_project_exceeds_tolerable():
    # 큰 오차로 upper > tolerable
    result = project_misstatement(
        kind=Kind.AP,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=10_000,
        sampled_misstatements=[(500, 1000), (300, 600)],
    )
    assert result.verdict == "EXCEED"


def test_project_upper_geq_projected():
    # upper limit ≥ projected sum (basic precision 가산 보장)
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(100, 500), (50, 300)],
    )
    assert result.upper_limit >= result.projected_misstatement


def test_project_no_misstatements():
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=50_000,
        sampled_misstatements=[],
    )
    assert result.projected_misstatement == 0.0
    assert result.upper_limit == pytest.approx(30_000, abs=1)  # basic precision only
    assert result.verdict == "WITHIN_TOLERABLE"


def test_key_item_projection_uses_actual_ms():
    # book >= interval인 key item은 실제 misstatement 그대로 projected에 가산
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(5_000, 20_000)],  # key item
    )
    assert result.projected_misstatement == pytest.approx(5_000, abs=1)
