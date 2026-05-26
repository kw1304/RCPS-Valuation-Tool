"""5803 부트스트랩 곡선 적용한 정확한 정합 검증.

이전 _test_5803.py는 flat Kd=13.2% 단순화 가정 — B- 등급 신용곡선의 텀 프리미엄
(단기 13% → 만기 20%) 미반영. 본 스크립트는 BOOT.csv의 실제 부트스트랩 곡선
(RF·RD spot rates)을 적용해 5803 reference와 정합 확인.

K-IFRS 13.62 / B40 "관측가능 input의 만기 매칭" 정합 검증.
"""
from inputs.deal_params import RCPSParams
from datetime import date
from models.tsiveriotis_fernandes import tf_rcps
from inputs.curves import spot_to_step_forwards

# 5803 BOOT.csv C-SPOT (Y) — 연속 스팟 곡선 (실제 부트스트랩 결과)
RF_SPOT = [
    (0.25, 0.02840), (0.5, 0.02776), (0.75, 0.02733), (1.0, 0.02691),
    (1.25, 0.02724), (1.5, 0.02756), (1.75, 0.02752), (2.0, 0.02748),
    (2.25, 0.02722), (2.5, 0.02695), (2.75, 0.02635), (3.0, 0.02575),
    (3.25, 0.02633), (3.5, 0.02691), (3.75, 0.02748), (4.0, 0.02806),
    (4.25, 0.02791), (4.5, 0.02777), (4.75, 0.02762), (5.0, 0.02747),
]
RD_SPOT = [
    (0.25, 0.12700), (0.5, 0.13727), (0.75, 0.14575), (1.0, 0.15206),
    (1.25, 0.15756), (1.5, 0.16316), (1.75, 0.16971), (2.0, 0.17641),
    (2.25, 0.18152), (2.5, 0.18678), (2.75, 0.19100), (3.0, 0.19536),
    (3.25, 0.19837), (3.5, 0.20150), (3.75, 0.20475), (4.0, 0.20812),
    (4.25, 0.20964), (4.5, 0.21124), (4.75, 0.21292), (5.0, 0.21470),
]

# 5803 발행조건 (steps=120 화면 기본)
p = RCPSParams(
    issue_date=date(2023, 9, 21),
    maturity_date=date(2028, 9, 21),
    face_value=114_299_975_108,
    coupon_rate=0.02,
    coupon_frequency="annual",
    conversion_price=29986,
    conversion_start=date(2025, 1, 21),
    put_start=date(2028, 3, 21),
    put_irr=0.075,
    stock_price=25522,
    volatility=0.5007,
    risk_free_rate=0.027,    # legacy fallback (곡선 미적용 시)
    credit_spread=0.105,     # legacy fallback (곡선 미적용 시)
    valuation_date=date(2024, 12, 31),
)

print("=" * 70)
print("5803 정합 검증 — 부트스트랩 곡선 vs flat Kd")
print("=" * 70)
print(f"face = {p.face_value:,}원, IRR = {p.put_irr*100:.1f}%, T = {p.T:.3f}년")
print(f"valuation_date = {p.valuation_date}, maturity = {p.maturity_date}")
print()

# ── (A) 부트스트랩 곡선 적용 ──
steps = 120
rf_curve = spot_to_step_forwards(RF_SPOT, p.T, steps)
kd_curve = spot_to_step_forwards(RD_SPOT, p.T, steps)
avg_rf = sum(rf_curve) / len(rf_curve)
avg_kd = sum(kd_curve) / len(kd_curve)
print(f"[A] 부트스트랩 곡선 적용 (steps={steps})")
print(f"    평균 forward Rf = {avg_rf*100:.3f}%, 평균 forward Kd = {avg_kd*100:.3f}%")

r_curve = tf_rcps(p, steps=steps, rf_curve=rf_curve, kd_curve=kd_curve, bond_discrete=False)
print(f"    채권가치   = {r_curve['bond_value']:>22,.0f}")
print(f"    풋옵션가치 = {r_curve['put_option_value']:>22,.0f}")
print(f"    풋채권가치 = {r_curve['put_bond_value']:>22,.0f}")
print(f"    전환권가치 = {r_curve['conversion_value']:>22,.0f}")
print(f"    공정가치   = {r_curve['fair_value']:>22,.0f}")
print()

# ── (B) flat Kd 13.2% (기존 _test_5803.py 가정) ──
print(f"[B] flat Kd 13.2% (Rf 2.7% + cs 10.5%) — 기존 단순화")
r_flat = tf_rcps(p, steps=steps, bond_discrete=False)
print(f"    채권가치   = {r_flat['bond_value']:>22,.0f}")
print(f"    풋옵션가치 = {r_flat['put_option_value']:>22,.0f}")
print(f"    풋채권가치 = {r_flat['put_bond_value']:>22,.0f}")
print(f"    전환권가치 = {r_flat['conversion_value']:>22,.0f}")
print(f"    공정가치   = {r_flat['fair_value']:>22,.0f}")
print()

# ── 5803 reference ──
print(f"[ref] 5803 보고서")
print(f"    채권가치   =         78,262,381,242")
print(f"    풋옵션가치 =          6,487,553,563")
print(f"    풋채권가치 =         84,749,934,805")
print(f"    전환권가치 =         36,017,234,632")
print(f"    공정가치   =        120,767,169,439")
print()

# ── 비교 분석 ──
print("=" * 70)
print("정합 분석")
print("=" * 70)
ref_fv = 120_767_169_439
ref_bv = 78_262_381_242
ref_cv = 36_017_234_632
ref_pv = 6_487_553_563

print(f"부트스트랩 곡선 (A) vs 5803 ref:")
print(f"    공정가치 차이: {r_curve['fair_value']-ref_fv:+,.0f} ({(r_curve['fair_value']-ref_fv)/ref_fv*100:+.2f}%)")
print(f"    채권가치 차이: {r_curve['bond_value']-ref_bv:+,.0f} ({(r_curve['bond_value']-ref_bv)/ref_bv*100:+.2f}%)")
print(f"    풋옵션 차이:   {r_curve['put_option_value']-ref_pv:+,.0f}")
print(f"    전환권 차이:   {r_curve['conversion_value']-ref_cv:+,.0f}")
print()
print(f"flat Kd (B) vs 5803 ref:")
print(f"    공정가치 차이: {r_flat['fair_value']-ref_fv:+,.0f} ({(r_flat['fair_value']-ref_fv)/ref_fv*100:+.2f}%)")
print(f"    채권가치 차이: {r_flat['bond_value']-ref_bv:+,.0f} ({(r_flat['bond_value']-ref_bv)/ref_bv*100:+.2f}%)")
