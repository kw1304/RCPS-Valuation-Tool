import pytest
from risk.domain import indicators as ind


def test_pct_change_basic():
    assert ind.pct_change(110, 100) == pytest.approx(10.0)
    assert ind.pct_change(50, 100) == pytest.approx(-50.0)


def test_pct_change_none_or_zero_base():
    assert ind.pct_change(100, None) is None
    assert ind.pct_change(None, 100) is None
    assert ind.pct_change(100, 0) is None


def test_ratio_safe_div():
    assert ind.safe_div(10, 2) == pytest.approx(5.0)
    assert ind.safe_div(10, 0) is None
    assert ind.safe_div(10, -0.0) is None
    assert ind.safe_div(None, 2) is None


def test_gross_margin():
    assert ind.gross_margin(revenue=100, cogs=60) == pytest.approx(40.0)  # %
    assert ind.gross_margin(revenue=0, cogs=0) is None


def test_receivables_turnover():
    # 매출 1000 / 매출채권 200 = 5.0회
    assert ind.turnover(flow=1000, balance=200) == pytest.approx(5.0)
    assert ind.turnover(flow=1000, balance=0) is None


def test_debt_ratio():
    assert ind.debt_ratio(liabilities=300, equity=100) == pytest.approx(300.0)  # %
    assert ind.debt_ratio(liabilities=300, equity=0) is None  # 자본잠식 분모 → None
    assert ind.debt_ratio(liabilities=300, equity=-50) is None


def test_interest_coverage():
    assert ind.interest_coverage(operating_income=300, finance_costs=100) == pytest.approx(3.0)
    assert ind.interest_coverage(operating_income=300, finance_costs=0) is None


def test_current_ratio():
    assert ind.current_ratio(current_assets=150, current_liabilities=100) == pytest.approx(150.0)


def test_net_margin():
    assert ind.net_margin(net_income=120, revenue=1000) == pytest.approx(12.0)  # %
    assert ind.net_margin(net_income=-50, revenue=1000) == pytest.approx(-5.0)
    assert ind.net_margin(net_income=120, revenue=0) is None  # 분모 0 → None
    assert ind.net_margin(net_income=None, revenue=1000) is None


def test_asset_turnover():
    assert ind.asset_turnover(revenue=1000, total_assets=500) == pytest.approx(2.0)  # 회
    assert ind.asset_turnover(revenue=1000, total_assets=0) is None  # 분모 0 → None
    assert ind.asset_turnover(revenue=None, total_assets=500) is None


def test_ocf_to_sales():
    assert ind.ocf_to_sales(operating_cf=80, revenue=1000) == pytest.approx(8.0)  # %
    assert ind.ocf_to_sales(operating_cf=-30, revenue=1000) == pytest.approx(-3.0)
    assert ind.ocf_to_sales(operating_cf=80, revenue=0) is None  # 분모 0 → None
    assert ind.ocf_to_sales(operating_cf=None, revenue=1000) is None
