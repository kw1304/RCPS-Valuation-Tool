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
