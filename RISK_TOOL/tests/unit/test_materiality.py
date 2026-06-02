from risk.domain.financial import FinancialYear
from risk.domain.materiality import performance_materiality


def test_pm_uses_smallest_benchmark():
    # 매출 100억, 자산 50억, 세전이익 2억 → 세전이익 5%=1천만, 매출0.5%=5천만, 자산0.5%=2.5천만
    # 가장 작은(보수적) = 세전이익 5% = 1천만, PM = ×0.75 = 750만
    fy = FinancialYear(year=2025, revenue=10_000_000_000,
                       total_assets=5_000_000_000, pretax_income=200_000_000)
    pm = performance_materiality(fy)
    assert pm.materiality == 10_000_000
    assert pm.pm == 7_500_000
    assert pm.benchmark == "pretax_income"


def test_pm_skips_none_and_nonpositive():
    # 세전이익 결측·자산 결측 → 매출 0.5%만 적용
    fy = FinancialYear(year=2025, revenue=20_000_000_000)
    pm = performance_materiality(fy)
    assert pm.materiality == 100_000_000
    assert pm.benchmark == "revenue"


def test_pm_raises_when_no_base():
    fy = FinancialYear(year=2025)
    import pytest
    with pytest.raises(ValueError):
        performance_materiality(fy)


def test_pm_manual_benchmark_with_ratios():
    # 직접지정: 자산총계 100억 × 중요성 1% × 수행 50% = PM 5천만
    fy = FinancialYear(year=2025, revenue=10_000_000_000, total_assets=10_000_000_000)
    pm = performance_materiality(fy, benchmark="total_assets",
                                 materiality_ratio=0.01, pm_ratio=0.5)
    assert pm.materiality == 100_000_000
    assert pm.pm == 50_000_000
    assert pm.benchmark == "total_assets"
    assert pm.manual is True


def test_pm_manual_uses_default_ratio_when_omitted():
    # 비율 미지정 → benchmark 기본비율(매출 0.5%, 수행 75%)
    fy = FinancialYear(year=2025, revenue=20_000_000_000)
    pm = performance_materiality(fy, benchmark="revenue")
    assert pm.materiality == 100_000_000      # 0.5%
    assert pm.pm == 75_000_000                # ×0.75
    assert pm.manual is True


def test_pm_manual_raises_on_missing_base():
    import pytest
    fy = FinancialYear(year=2025, revenue=10_000_000_000)  # 세전이익 결측
    with pytest.raises(ValueError):
        performance_materiality(fy, benchmark="pretax_income")


def test_pm_manual_raises_on_bad_ratio():
    import pytest
    fy = FinancialYear(year=2025, revenue=10_000_000_000)
    with pytest.raises(ValueError):
        performance_materiality(fy, benchmark="revenue", pm_ratio=1.5)  # >100%
