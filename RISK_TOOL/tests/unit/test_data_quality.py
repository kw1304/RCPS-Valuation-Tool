from risk.domain.financial import FinancialYear
from risk.domain.data_quality import check_quality


def test_clean_no_warnings():
    fy = FinancialYear(2025, revenue=1000, total_assets=2000,
                       total_liabilities=1200, total_equity=800, operating_cf=100)
    assert check_quality([fy]) == []


def test_bs_identity_violation_warned():
    # 자산 2000 ≠ 부채1200 + 자본500 (=1700), 15% 차이
    fy = FinancialYear(2025, revenue=1000, total_assets=2000,
                       total_liabilities=1200, total_equity=500, operating_cf=100)
    w = check_quality([fy])
    assert any("항등식" in x for x in w)


def test_scale_anomaly_warned():
    # 매출이 자산의 50배
    fy = FinancialYear(2025, revenue=100_000, total_assets=2000,
                       total_liabilities=1000, total_equity=1000, operating_cf=1)
    w = check_quality([fy])
    assert any("스케일" in x for x in w)


def test_critical_missing_warned():
    fy = FinancialYear(2025, total_assets=2000, total_liabilities=1000, total_equity=1000)
    w = check_quality([fy])
    assert any("결측" in x for x in w)
