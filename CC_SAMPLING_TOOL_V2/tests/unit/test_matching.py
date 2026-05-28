import pytest
from src.domain.entities import Verdict
from src.domain.matching import judge_response


def test_no_response_when_confirmed_none():
    v = judge_response(expected=1000, confirmed=None, diff_reason=None)
    assert v == Verdict.NO_RESPONSE


def test_match_within_threshold():
    # diff 500 < max(1000, 1_000_000_000 × 0.001 = 1_000_000)
    v = judge_response(expected=1_000_000_000, confirmed=1_000_000_500,
                       diff_reason=None)
    assert v == Verdict.MATCH


def test_match_minimum_threshold_1000():
    # 작은 잔액: max(1000, 100 × 0.001 = 0.1) → 1000
    v = judge_response(expected=100, confirmed=999, diff_reason=None)
    assert v == Verdict.MATCH


def test_reconciled_with_timing():
    v = judge_response(expected=1000, confirmed=0, diff_reason="시점차이")
    assert v == Verdict.RECONCILED


def test_reconciled_with_other_reasons():
    for r in ["미수령", "미발송"]:
        v = judge_response(expected=1000, confirmed=0, diff_reason=r)
        assert v == Verdict.RECONCILED


def test_discrepancy_default():
    v = judge_response(expected=1000, confirmed=500, diff_reason=None)
    assert v == Verdict.DISCREPANCY


def test_negative_expected_uses_abs_threshold():
    # 환불금 -1M, confirmed -999.5K → diff 500 < threshold 1000
    v = judge_response(expected=-1_000_000, confirmed=-999_500,
                       diff_reason=None)
    assert v == Verdict.MATCH


def test_custom_threshold():
    # 0.01% (10bp)로 strict
    v = judge_response(expected=1_000_000, confirmed=1_000_500,
                       diff_reason=None, ratio_threshold=0.0001)
    assert v == Verdict.DISCREPANCY  # 500 > max(1000, 100)
