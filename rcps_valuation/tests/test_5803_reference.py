"""5803 표본 RCPS 정합 회귀 테스트 — 부트스트랩 곡선 + 5803 흡수형 분해.

K-IFRS 1109.B4.3.5 복합금융상품 분리 회계 표준 정합:
  ① 채권가치   = max(face, put_mat) × DF + 쿠폰 PV — 발행자 무조건 의무
  ② 풋옵션가치 = 풋채권 − 채권 — 조기 행사 시간가치
  ③ 전환권가치 = 총 FV − 풋채권 — 자본 부분 (잔여)

5803 BOOT.csv의 RF·RD 부트스트랩 곡선(B- 등급, 평균 Kd ≈ 20.4%) 적용 시
모든 분해 항목이 5803 보고서 reference와 ±1% 이내 정합.

이전 _test_5803.py는 flat Kd=13.2% 잘못된 단순화로 공정가치를 +14% 부풀림.
폐기됨 (2026-05-27).
"""
import pytest
from datetime import date
from inputs.deal_params import RCPSParams
from inputs.curves import spot_to_step_forwards
from models.tsiveriotis_fernandes import tf_rcps
from models.goldman_sachs import gs_rcps
from models.monte_carlo import monte_carlo_rcps


# 5803 BOOT.csv C-SPOT (Y) — 연속 스팟 곡선 (B- 등급 회사채)
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

# 5803 reference (보고서 TF 시트 명시값 — TF/T&F Without Call 분해)
REF = {
    "fair_value":       120_767_169_439,   # TF 모형 공정가치 (5803 TF Without Call)
    "bond_value":        78_262_381_242,
    "put_option_value":   6_487_553_563,
    "put_bond_value":    84_749_934_805,
    "conversion_value":  36_017_234_632,
}

# 5803 reference (보고서 GS 시트 명시값 — GS Without Call)
REF_GS = {
    "fair_value":       115_103_574_039,   # GS 모형 공정가치 (5803 GS Without Call)
}


def _params_5803():
    return RCPSParams(
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
        risk_free_rate=0.027,
        credit_spread=0.105,
        valuation_date=date(2024, 12, 31),
    )


@pytest.fixture
def result_5803_curve():
    """5803 부트스트랩 곡선 적용 평가 결과."""
    p = _params_5803()
    steps = 120
    rf_curve = spot_to_step_forwards(RF_SPOT, p.T, steps)
    kd_curve = spot_to_step_forwards(RD_SPOT, p.T, steps)
    return tf_rcps(p, steps=steps, rf_curve=rf_curve, kd_curve=kd_curve, bond_discrete=False)


def test_fair_value_정합(result_5803_curve):
    """총 공정가치 5803 ref와 ±1% 이내."""
    diff_pct = (result_5803_curve["fair_value"] - REF["fair_value"]) / REF["fair_value"]
    assert abs(diff_pct) < 0.01, f"공정가치 차이 {diff_pct*100:.2f}% — 1% 초과"


def test_bond_value_정합(result_5803_curve):
    """채권가치(5803 흡수형 분해) ±1% 이내."""
    diff_pct = (result_5803_curve["bond_value"] - REF["bond_value"]) / REF["bond_value"]
    assert abs(diff_pct) < 0.01, f"채권 차이 {diff_pct*100:.2f}% — 1% 초과"


def test_put_option_value_정합(result_5803_curve):
    """풋옵션가치 5803 ref ±2% 이내 (작은 절대값이라 허용 폭 확대)."""
    diff_pct = (result_5803_curve["put_option_value"] - REF["put_option_value"]) / REF["put_option_value"]
    assert abs(diff_pct) < 0.02, f"풋옵션 차이 {diff_pct*100:.2f}% — 2% 초과"


def test_put_bond_value_정합(result_5803_curve):
    """풋채권가치 5803 ref ±1% 이내."""
    diff_pct = (result_5803_curve["put_bond_value"] - REF["put_bond_value"]) / REF["put_bond_value"]
    assert abs(diff_pct) < 0.01, f"풋채권 차이 {diff_pct*100:.2f}% — 1% 초과"


def test_conversion_value_정합(result_5803_curve):
    """전환권가치 5803 ref ±1% 이내."""
    diff_pct = (result_5803_curve["conversion_value"] - REF["conversion_value"]) / REF["conversion_value"]
    assert abs(diff_pct) < 0.01, f"전환권 차이 {diff_pct*100:.2f}% — 1% 초과"


def test_분해_항등식(result_5803_curve):
    """① + ② + ③ = 공정가치 (분해 항등식 검증). 반올림 톨러런스 ±2원."""
    r = result_5803_curve
    total = r["bond_value"] + r["put_option_value"] + r["conversion_value"]
    # 풋채권 = 채권 + 풋옵션
    assert abs(r["put_bond_value"] - (r["bond_value"] + r["put_option_value"])) <= 2, \
        "풋채권 = 채권 + 풋옵션 항등식 위배"
    # 공정가치 = 풋채권 + 전환권 (= 채권 + 풋옵션 + 전환권)
    assert abs(r["fair_value"] - total) <= 2, "공정가치 분해 항등식 위배"


@pytest.fixture
def all_models_5803():
    """TF·GS·MC 3모형 5803 곡선 평가 결과."""
    p = _params_5803()
    steps = 120
    rf_curve = spot_to_step_forwards(RF_SPOT, p.T, steps)
    kd_curve = spot_to_step_forwards(RD_SPOT, p.T, steps)
    return {
        "tf": tf_rcps(p, steps=steps, rf_curve=rf_curve, kd_curve=kd_curve, bond_discrete=False),
        "gs": gs_rcps(p, steps=steps, rf_curve=rf_curve, kd_curve=kd_curve, bond_discrete=False),
        "mc": monte_carlo_rcps(p, n_paths=50000, n_steps=steps, rf_curve=rf_curve, kd_curve=kd_curve),
    }


def test_TF_5803_정합(all_models_5803):
    """TF 모형은 5803 ref와 ±1% 이내 (메인 모형 — 가장 정확한 정합 요구)."""
    diff_pct = (all_models_5803["tf"]["fair_value"] - REF["fair_value"]) / REF["fair_value"]
    assert abs(diff_pct) < 0.01, f"TF 공정가치 차이 {diff_pct*100:.2f}% — 1% 초과"


def test_MC_5803_정합(all_models_5803):
    """MC 모형은 5803 ref와 ±2% 이내 (표본오차 고려)."""
    diff_pct = (all_models_5803["mc"]["fair_value"] - REF["fair_value"]) / REF["fair_value"]
    assert abs(diff_pct) < 0.02, f"MC 공정가치 차이 {diff_pct*100:.2f}% — 2% 초과"


def test_GS_5803_정합(all_models_5803):
    """GS 모형은 5803 GS 시트 ref와 ±1% 이내 정합.

    이전에 GS를 5803 TF ref(120.77bn)와 비교한 게 잘못된 기준이었음 (2026-05-27).
    5803 보고서는 TF·GS 두 모형 모두 산출 — 각 모형별로 별도 ref 비교가 정확.
    """
    gs_fv = all_models_5803["gs"]["fair_value"]
    diff_pct = (gs_fv - REF_GS["fair_value"]) / REF_GS["fair_value"]
    assert abs(diff_pct) < 0.01, f"GS 공정가치 차이 {diff_pct*100:.2f}% — 1% 초과 (5803 GS ref 115.10bn 대비)"


def test_TF_GS_모형_차이_합리적(all_models_5803):
    """GS·TF 차이는 모형 구조(블렌딩 vs 분리할인)에서 발생.

    5803 보고서: TF 120.77bn − GS 115.10bn = -4.7% (5803도 동일 차이 인정).
    K-IFRS 13.93(g) Level 3 측정 불확실성 공시 대상.
    """
    diff = (all_models_5803["gs"]["fair_value"] - all_models_5803["tf"]["fair_value"]) / all_models_5803["tf"]["fair_value"]
    # 우리 모델: -5.22%, 5803: -4.7% → ±1.5%p 이내면 정합
    expected_diff = -0.047  # 5803 보고서의 TF·GS 차이
    assert abs(diff - expected_diff) < 0.015, \
        f"TF·GS 모형 차이 {diff*100:.2f}% — 5803 보고서 차이({expected_diff*100:.2f}%) 대비 ±1.5%p 초과"
