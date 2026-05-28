import pytest
from src.domain.sampling.sample_size import (
    reliability_factor, expansion_factor, sample_size_mus,
)


@pytest.mark.parametrize("confidence,rf", [
    (0.99, 4.61),
    (0.95, 3.00),
    (0.90, 2.31),
    (0.80, 1.61),
])
def test_reliability_factor(confidence, rf):
    assert reliability_factor(confidence) == pytest.approx(rf, abs=0.01)


def test_reliability_factor_invalid():
    with pytest.raises(ValueError):
        reliability_factor(0.5)  # 미지원


def test_expansion_factor_zero_em():
    assert expansion_factor(0.95, em_ratio=0.0) == pytest.approx(1.0, abs=0.01)


def test_expansion_factor_increases_with_em():
    f_low = expansion_factor(0.95, em_ratio=0.1)
    f_high = expansion_factor(0.95, em_ratio=0.5)
    assert f_high > f_low


def test_sample_size_basic():
    n = sample_size_mus(
        book_value=10_000_000_000,
        confidence=0.95,
        tolerable=500_000_000,
        expected_ms=0,
    )
    # n = (10B × 3.0) / 500M = 60
    assert n == 60


def test_sample_size_with_em():
    n = sample_size_mus(
        book_value=10_000_000_000,
        confidence=0.95,
        tolerable=500_000_000,
        expected_ms=100_000_000,  # 20% of tolerable
    )
    # n_base = 60, expanded due to EM > 0
    assert n > 60


def test_sample_size_invalid_when_em_geq_tm():
    with pytest.raises(ValueError):
        sample_size_mus(10_000_000_000, 0.95, 500_000_000, 600_000_000)


def test_sample_size_round_up():
    n = sample_size_mus(
        book_value=1_000_000_000,
        confidence=0.95,
        tolerable=100_000_000,
        expected_ms=0,
    )
    # 10×3 = 30 — exact
    assert n == 30
