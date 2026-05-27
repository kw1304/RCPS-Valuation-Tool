"""차이 판정 단위 테스트."""
import pytest

from src.domain.reconciliation import ReconResult, reconcile


class TestMatchedStatus:
    def test_zero_difference_matched(self):
        r = reconcile(1_000_000, 1_000_000)
        assert r.status == "matched"
        assert r.difference == pytest.approx(0.0)

    def test_within_tolerance_matched(self):
        r = reconcile(1_000_000, 999_500, tolerance=1_000)
        assert r.status == "matched"
        assert r.difference == pytest.approx(500.0)

    def test_exactly_at_tolerance_matched(self):
        r = reconcile(1_000_000, 999_000, tolerance=1_000)
        assert r.status == "matched"

    def test_just_over_tolerance_mismatch(self):
        r = reconcile(1_000_000, 998_999, tolerance=1_000)
        assert r.status == "mismatch"


class TestMismatch:
    def test_simple_mismatch(self):
        r = reconcile(1_000_000, 900_000)
        assert r.status == "mismatch"
        assert r.difference == pytest.approx(100_000.0)

    def test_difference_pct(self):
        r = reconcile(1_000_000, 900_000)
        assert r.difference_pct == pytest.approx(0.1, rel=1e-3)

    def test_negative_extracted_balance(self):
        r = reconcile(500_000, -500_000)
        assert r.status == "mismatch"
        assert r.difference == pytest.approx(1_000_000.0)

    def test_negative_ledger(self):
        """부채 계정 — 장부가 음수."""
        r = reconcile(-500_000, -500_000)
        assert r.status == "matched"

    def test_extracted_larger_than_ledger(self):
        r = reconcile(1_000_000, 1_200_000)
        assert r.difference == pytest.approx(-200_000.0)


class TestExtractionFailed:
    def test_none_extracted_returns_extraction_failed(self):
        r = reconcile(1_000_000, None)
        assert r.status == "extraction_failed"
        assert r.difference is None
        assert r.difference_pct is None

    def test_none_tolerance_respected(self):
        r = reconcile(1_000_000, None, tolerance=5000)
        assert r.status == "extraction_failed"


class TestZeroLedger:
    def test_zero_ledger_no_crash(self):
        r = reconcile(0.0, 0.0)
        assert r.status == "matched"
        assert r.difference_pct is None  # 분모 0


class TestToleranceField:
    def test_tolerance_stored_in_result(self):
        r = reconcile(1_000_000, 990_000, tolerance=5_000)
        assert r.tolerance == 5_000
