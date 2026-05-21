from inputs.deal_params import RCPSParams
from datetime import date
from models.binomial_v2 import rcps_binomial

# 5803 파라미터 — 신용스프레드 10.5% (UI 기본값과 동일, Kd=13.2%)
p = RCPSParams(
    issue_date=date(2023,9,21),
    maturity_date=date(2028,9,21),
    face_value=114_299_975_108,
    coupon_rate=0.02,
    coupon_frequency='annual',
    conversion_price=29986,
    conversion_start=date(2025,1,21),
    put_start=date(2028,3,21),
    put_irr=0.075,
    stock_price=25522,
    volatility=0.5007,
    risk_free_rate=0.027,
    credit_spread=0.105,   # Kd = 13.2%
    valuation_date=date(2024,12,31),
)

r = rcps_binomial(p)
print(f"steps={r['steps']}  Kd={p.discount_rate*100:.1f}%")
print(f"채권가치   = {r['bond_value']:>22,.0f}  (참고 78,262,381,242)")
print(f"풋옵션가치 = {r['put_option_value']:>22,.0f}  (참고  6,487,553,563)")
print(f"전환권가치 = {r['conversion_value']:>22,.0f}  (참고 36,017,234,632)")
print(f"총 공정가치= {r['fair_value']:>22,.0f}  (참고 120,767,169,439)")
print()

# Kd별 채권가치 비교
print("Kd별 채권가치:")
for kd in [0.09, 0.10, 0.105, 0.11, 0.12, 0.13, 0.15, 0.20]:
    from copy import deepcopy
    p2 = deepcopy(p); p2.credit_spread = kd; p2.risk_free_rate = 0.0
    r2 = rcps_binomial(p2)
    print(f"  Kd={kd*100:.1f}%: 채권={r2['bond_value']:>18,.0f}  풋={r2['put_option_value']:>14,.0f}  conv={r2['conversion_value']:>14,.0f}  total={r2['fair_value']:>18,.0f}")
