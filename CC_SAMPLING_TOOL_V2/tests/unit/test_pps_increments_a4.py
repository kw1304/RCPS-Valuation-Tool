import pytest
from src.domain.entities import Kind
from src.domain.projection.pps import (
    project_misstatement, _rank_increments,
)


def test_rank_increments_95():
    inc = _rank_increments(0.95)
    assert inc[0] == pytest.approx(0.75, abs=0.01)
    assert inc[1] == pytest.approx(0.55, abs=0.01)
    assert inc[2] == pytest.approx(0.46, abs=0.01)
    assert inc[3] == pytest.approx(0.40, abs=0.01)
    assert inc[4] == pytest.approx(0.35, abs=0.01)
    assert inc[5] == pytest.approx(0.30, abs=0.01)
    assert inc[6] == pytest.approx(0.30, abs=0.01)


def test_rank_increments_decreasing():
    for conf in (0.80, 0.90, 0.95, 0.99):
        inc = _rank_increments(conf)
        for i in range(len(inc) - 1):
            assert inc[i] >= inc[i + 1] - 1e-9


def test_projection_with_multiple_taintings_uses_rank():
    result = project_misstatement(
        kind=Kind.AR, confidence=0.95,
        sampling_interval=10_000, tolerable=1_000_000,
        sampled_misstatements=[
            (5000, 10000),
        ],
    )
    assert result.upper_limit > result.projected_misstatement


def test_projection_three_partial_taintings():
    # book=500, ms=250 → tainting=0.5
    # book=600, ms=180 → tainting=0.3
    # book=700, ms=140 → tainting=0.2
    result = project_misstatement(
        kind=Kind.AR, confidence=0.95,
        sampling_interval=10_000, tolerable=1_000_000,
        sampled_misstatements=[(250, 500), (180, 600), (140, 700)],
    )
    # projected = (0.5 + 0.3 + 0.2) * 10000 = 10000
    # basic_precision = 3.0 * 10000 = 30000
    # incremental = (0.75*0.5 + 0.55*0.3 + 0.46*0.2) * 10000
    #             = (0.375 + 0.165 + 0.092) * 10000 = 6320
    # upper = 10000 + 30000 + 6320 = 46320
    assert result.projected_misstatement == pytest.approx(10000, abs=1)
    assert result.basic_precision == pytest.approx(30000, abs=1)
    assert result.incremental_allowance == pytest.approx(6320, abs=10)
    assert result.upper_limit == pytest.approx(46320, abs=10)


def test_projection_taintings_sorted_desc_for_ranking():
    r1 = project_misstatement(
        kind=Kind.AR, confidence=0.95, sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(140, 700), (250, 500), (180, 600)],
    )
    r2 = project_misstatement(
        kind=Kind.AR, confidence=0.95, sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(250, 500), (180, 600), (140, 700)],
    )
    assert r1.upper_limit == pytest.approx(r2.upper_limit, abs=1)
