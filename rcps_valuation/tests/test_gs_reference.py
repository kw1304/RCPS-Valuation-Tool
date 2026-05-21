"""
Golden-reference test: GS 노드희석_구분할인 모형
Expected fair_value = 10,758.6849  → rounds to 10759
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from inputs.deal_params import RCPSParams
from models.goldman_sachs import gs_rcps


RF_CURVE = [
    0.02,
    0.03117144293614893,
    0.039501324321855824,
    0.04273309617377419,
    0.0438610554742751,
]
KD_CURVE = [
    0.03944,
    0.06408517701354177,
    0.07445133252390601,
    0.06155275829026019,
    0.0709749288749959,
]


def build_params():
    """5-step annual RCPS matching the golden spec."""
    return RCPSParams(
        issue_date=date(2020, 1, 1),
        valuation_date=date(2020, 1, 1),
        maturity_date=date(2025, 1, 1),
        face_value=10000,
        coupon_rate=0.0,
        coupon_frequency="none",
        conversion_price=10000,
        conversion_start=date(2022, 1, 1),   # step 2 (annual)
        put_start=date(2023, 1, 1),           # step 3 (annual)
        put_irr=0.02,
        refixing=True,
        refixing_floor=0.8,          # K_floor = 10000*0.8 = 8000
        refixing_trigger=0.8,        # trigger at S <= K*0.8 = 8000 (= floor boundary)
        refixing_frequency="continuous",
        stock_price=8994.115280572414,
        volatility=0.3,
        risk_free_rate=0.02,
        credit_spread=0.01944,       # unused when kd_curve given
        dividend_yield=0.0,
        common_shares=100,
        rcps_shares=20,
    )


def test_golden_reference():
    params = build_params()
    result = gs_rcps(
        params,
        steps=5,
        rf_curve=RF_CURVE,
        kd_curve=KD_CURVE,
        bond_discrete=True,
    )
    fv = result["fair_value"]
    print(f"[golden] fair_value = {fv}  (expected 10759, reference exact 10758.6849)")
    print(f"  dilution_applied      = {result['dilution_applied']}")
    print(f"  diluted_stock_price_0 = {result['diluted_stock_price_0']}")
    print(f"  conv_prob_0           = {result['conv_prob_0']}")
    print(f"  model                 = {result['model']}")
    assert abs(fv - 10759) <= 1, (
        f"Golden-reference FAILED: fair_value={fv}, expected 10759 (tol ±1)"
    )
    print("[golden] PASSED")


def test_no_dilution_sanity():
    """No share counts — must return a number without error."""
    params = RCPSParams(
        issue_date=date(2020, 1, 1),
        valuation_date=date(2020, 1, 1),
        maturity_date=date(2025, 1, 1),
        face_value=10000,
        coupon_rate=0.0,
        coupon_frequency="none",
        conversion_price=10000,
        conversion_start=date(2022, 1, 1),
        put_start=date(2023, 1, 1),
        put_irr=0.02,
        refixing=False,
        stock_price=9000,
        volatility=0.3,
        risk_free_rate=0.03,
        credit_spread=0.04,
        dividend_yield=0.0,
        # NO common_shares / rcps_shares
    )
    result = gs_rcps(params, steps=60)
    fv = result["fair_value"]
    print(f"[no-dil] fair_value = {fv}  dilution_applied={result['dilution_applied']}")
    assert isinstance(fv, (int, float)) and fv > 0
    assert result["dilution_applied"] is False
    assert result["diluted_stock_price_0"] is None
    print("[no-dil] PASSED")


def test_legacy_kwargs():
    """enterprise_value/net_debt kwargs accepted without error (legacy callers)."""
    params = build_params()
    result = gs_rcps(
        params,
        steps=5,
        enterprise_value=1_000_000,
        net_debt=0,
        # common_shares / rcps_shares come from params
        rf_curve=RF_CURVE,
        kd_curve=KD_CURVE,
        bond_discrete=True,
    )
    fv = result["fair_value"]
    print(f"[legacy] fair_value = {fv}  (shares from params, ev/nd ignored)")
    assert isinstance(fv, (int, float)) and fv > 0
    print("[legacy] PASSED")


if __name__ == "__main__":
    test_golden_reference()
    test_no_dilution_sanity()
    test_legacy_kwargs()
    print("\nAll GS reference tests passed.")
