import pytest
from src.domain.alternative import coverage_verdict, COVERAGE_ACCEPTABLE_THRESHOLD


def test_coverage_acceptable_high():
    pct, verdict = coverage_verdict(covered_amt=800, non_response_total=1000)
    assert pct == pytest.approx(0.8)
    assert verdict == "ACCEPTABLE"


def test_coverage_insufficient_low():
    pct, verdict = coverage_verdict(covered_amt=500, non_response_total=1000)
    assert pct == 0.5
    assert verdict == "INSUFFICIENT"


def test_coverage_exact_threshold_acceptable():
    pct, verdict = coverage_verdict(
        covered_amt=750, non_response_total=1000)
    assert verdict == "ACCEPTABLE"


def test_coverage_zero_non_response_returns_acceptable():
    pct, verdict = coverage_verdict(covered_amt=0, non_response_total=0)
    assert verdict == "ACCEPTABLE"
    assert pct == 1.0


def test_coverage_capped_at_one():
    pct, verdict = coverage_verdict(
        covered_amt=2000, non_response_total=1000)
    assert pct == 1.0
    assert verdict == "ACCEPTABLE"


def test_coverage_threshold_constant():
    assert COVERAGE_ACCEPTABLE_THRESHOLD == 0.75
