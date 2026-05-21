import sys; sys.path.insert(0, r'c:\Claude\rcps_valuation')
from datetime import date
from inputs.deal_params import RCPSParams
from models.tsiveriotis_fernandes import tf_rcps
from models.goldman_sachs import gs_rcps

base = dict(
    issue_date=date(2023,1,1),
    valuation_date=date(2023,1,1),
    maturity_date=date(2026,1,1),
    face_value=10000,
    coupon_rate=0.0,
    coupon_frequency='none',
    conversion_price=10000,
    conversion_start=date(2024,1,1),
    put_start=date(2025,1,1),
    put_irr=0.03,
    stock_price=9000,
    volatility=0.3,
    risk_free_rate=0.03,
    credit_spread=0.04,
    dividend_yield=0.0,
)

params_no_call = RCPSParams(**base)
params_with_call = RCPSParams(**base, call_start=date(2024,1,1), call_irr=0.05)
params_no_call2 = RCPSParams(**base)   # identical baseline, call_start=None

tf_no  = tf_rcps(params_no_call, steps=36)
tf_yes = tf_rcps(params_with_call, steps=36)
tf_nc2 = tf_rcps(params_no_call2, steps=36)
gs_no  = gs_rcps(params_no_call, steps=36)
gs_yes = gs_rcps(params_with_call, steps=36)

print("TF no-call =", tf_no["fair_value"])
print("TF with-call =", tf_yes["fair_value"])
print("TF delta =", tf_yes["fair_value"] - tf_no["fair_value"])
print("TF call_start=None identical to no-call:", tf_no["fair_value"] == tf_nc2["fair_value"])
print()
print("GS no-call =", gs_no["fair_value"])
print("GS with-call =", gs_yes["fair_value"])
print("GS delta =", gs_yes["fair_value"] - gs_no["fair_value"])
print()
assert tf_yes["fair_value"] <= tf_no["fair_value"], "FAIL: TF call should reduce value"
assert gs_yes["fair_value"] <= gs_no["fair_value"], "FAIL: GS call should reduce value"
assert tf_no["fair_value"] == tf_nc2["fair_value"], "FAIL: call_start=None must be unchanged"
print("All call sanity checks PASSED")
