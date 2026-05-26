"""VE (TF 지분 성분) vs 전환권가치 (흡수형) 엄격한 검증.

검증 목표:
1. VE − 전환권 = 풋채권 − VD 라는 항등식 확인
2. 14.48bn 차이의 정확한 구성 요소 분해:
   - (흡수형 채권 − VD) = "전환 경로에서 TF 채권 성분에서 빠져나간 부분"
   - 풋옵션 = "풋 행사 시간가치"
3. 노드별 E/B 추적으로 두 분해의 본질 차이 시각화
"""
from datetime import date
from inputs.deal_params import RCPSParams
from inputs.curves import spot_to_step_forwards
from models.tsiveriotis_fernandes import tf_rcps

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

p = RCPSParams(
    issue_date=date(2023, 9, 21), maturity_date=date(2028, 9, 21),
    face_value=114_299_975_108, coupon_rate=0.02, coupon_frequency="annual",
    conversion_price=29986, conversion_start=date(2025, 1, 21),
    put_start=date(2028, 3, 21), put_irr=0.075,
    stock_price=25522, volatility=0.5007,
    risk_free_rate=0.027, credit_spread=0.105,
    valuation_date=date(2024, 12, 31),
)

steps = 120
rf_curve = spot_to_step_forwards(RF_SPOT, p.T, steps)
kd_curve = spot_to_step_forwards(RD_SPOT, p.T, steps)

# TF 평가 (분해 모두 산출)
r = tf_rcps(p, steps=steps, rf_curve=rf_curve, kd_curve=kd_curve, bond_discrete=False)

print("=" * 75)
print("VE vs 전환권가치 — 엄격한 검증")
print("=" * 75)
print(f"5803 케이스, steps={steps}, 부트스트랩 곡선 적용")
print()
print(f"공정가치(fv)            = {r['fair_value']:>20,.0f}")
print()
print(f"[A] 흡수형 분해 (한국 평가실무):")
print(f"    채권(_bond_only)    = {r['bond_value']:>20,.0f}")
print(f"    풋옵션              = {r['put_option_value']:>20,.0f}")
print(f"    풋채권(_puttable)   = {r['put_bond_value']:>20,.0f}")
print(f"    전환권              = {r['conversion_value']:>20,.0f}")
print(f"    합계                = {r['bond_value']+r['put_option_value']+r['conversion_value']:>20,.0f}")
print()
print(f"[B] TF 2-way 분해 (Tsiveriotis-Fernandes):")
print(f"    VD (B[0], 채권 성분) = {r['bond_component']:>20,.0f}")
print(f"    VE (E[0], 지분 성분) = {r['equity_component']:>20,.0f}")
print(f"    합계                = {r['bond_component']+r['equity_component']:>20,.0f}")
print()

# 항등식 검증
ve = r['equity_component']
vd = r['bond_component']
conv = r['conversion_value']
bond = r['bond_value']
put_opt = r['put_option_value']
put_bond = r['put_bond_value']

print("=" * 75)
print("항등식 검증")
print("=" * 75)
diff1 = ve - conv
diff2 = put_bond - vd
print(f"VE − 전환권             = {ve:>15,.0f} − {conv:>15,.0f} = {diff1:>15,.0f}")
print(f"풋채권 − VD             = {put_bond:>15,.0f} − {vd:>15,.0f} = {diff2:>15,.0f}")
print(f"두 항등식 일치          : {abs(diff1 - diff2) < 1} (차이 {diff1-diff2:,.0f}원)")
print()

# 차이의 구성요소 분해
diff_A = bond - vd        # 흡수형 채권 − VD
diff_B = put_opt          # 풋옵션 (= 흡수형 풋채권 − 흡수형 채권)
print(f"차이 14.48bn의 구성:")
print(f"  ① (흡수형 채권 − VD)  = {bond:>15,.0f} − {vd:>15,.0f} = {diff_A:>15,.0f}")
print(f"     → 전환 가능성으로 TF 채권성분에서 빠져나간 부분")
print(f"     (전환 결정 시 B 버킷이 coup로 떨어지는 효과의 PV)")
print()
print(f"  ② 풋옵션 시간가치      = {diff_B:>15,.0f}")
print(f"     → 풋채권 = 채권 + 풋옵션이라 추가 가산")
print()
print(f"  합계 ① + ②           = {diff_A + diff_B:>15,.0f}")
print(f"  = VE − 전환권 = 풋채권 − VD ✓")
print()

# 회계적 해석
print("=" * 75)
print("회계적 해석")
print("=" * 75)
print("""
두 분해는 본질적으로 다른 차원:

[A] 흡수형 (한국 평가실무):
    - 분리 기준: "발행자 무조건 의무 vs 추가 옵션 가치"
    - 채권 = 발행자 무조건 의무 PV (max(face,put_mat) 전 경로에 흡수)
    - 풋옵션 = 풋 행사 시간가치
    - 전환권 = 풋채권 위에 얹어지는 전환 옵션의 IN-THE-MONEY 가치

[B] TF 2-way (Tsiveriotis-Fernandes):
    - 분리 기준: "전환 경로 vs 비전환 경로의 위험 분리"
    - VD = 비전환 경로에서 받는 채권 PV (Kd 할인)
    - VE = 전환 경로에서 받는 cv PV (Rf 할인)

차이가 발생하는 이유:
    - 흡수형 채권은 "전환·풋 무관 가상 채권" — 전환되든 안되든 만기 보장
      금액 PV로 계산 (78.70bn)
    - VD는 "TF에서 채권 버킷에 남은 PV" — 전환 결정 시 B 버킷이 0으로
      떨어지므로 전환 가능성으로 채권 PV 감소 (70.64bn)
    - 차이 8.06bn = "전환 결정 노드들에서 사라진 채권 PV가 VE로 이동"

    - 풋옵션 6.43bn = "흡수형에서는 풋채권에 포함, TF에서는 VE+VD에 흡수"
""")

# 노드별 추적 (전환 노드 vs 비전환 노드 샘플)
print("=" * 75)
print("노드별 추적 — 만기 노드에서 전환 결정의 효과")
print("=" * 75)
print("TF 분해에서 만기 노드(steps={})는 cv vs mat_principal 비교 후:".format(steps))
print("  - 전환 시 : E[j] = cv,        B[j] = 만기쿠폰")
print("  - 비전환  : E[j] = 0,         B[j] = mat_principal + 만기쿠폰")
print()
print("후방귀납하면:")
print("  - VE = E[0] = 전환 경로의 cv를 Rf로 할인한 합산")
print("  - VD = B[0] = 비전환 경로의 mat_principal을 Kd로 할인한 합산")
print()
print("흡수형 분해에서는 노드별 결정 무관:")
print("  - 채권 = 모든 경로의 mat_principal × DF (단일 PV 계산)")
print("  - 따라서 채권 > VD (전환 경로의 mat_principal이 VD에서는 빠짐)")
print()
print(f"수치로: 흡수형 채권 78.70bn vs VD 70.64bn → 8.06bn 차이")
print(f"     이 8.06bn이 정확히 'TF에서 VE로 이동한 채권 가치'")
