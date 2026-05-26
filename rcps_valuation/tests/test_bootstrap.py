"""Par yield bond bootstrap 골든 테스트 — 결정론적 재현성 검증.

K-IFRS 13 BC176 "관측가능 input의 충실한 표현"을 위한 산출과정 재현 보장.
"""
import math
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inputs.bootstrap import bootstrap_par_yield, spot_curve_from_bootstrap


def test_flat_curve_recovers_ytm():
    """평탄 YTM 곡선 → 모든 만기 spot ≈ YTM (연속복리 변환 차이만)."""
    rows = [{"t": t, "y": 3.0} for t in [1, 2, 3, 5, 10]]
    r = bootstrap_par_yield(rows, m=2, max_T=10)
    assert r["out_rows"], "out_rows should not be empty"
    # 평탄 곡선이면 zcont ≈ m·ln(1+y/m) = 2·ln(1.015) ≈ 2.978%
    expected_zcont = 2 * math.log(1.015) * 100
    for row in r["out_rows"]:
        assert abs(row["zcont"] - expected_zcont) < 0.05, (
            f"T={row['T']}: zcont={row['zcont']:.4f}, expected {expected_zcont:.4f}"
        )


def test_upward_curve_spot_above_ytm():
    """우상향 YTM 곡선 → 장기 spot > 장기 YTM (forward > spot > YTM 단조성)."""
    rows = [{"t": 1, "y": 2.0}, {"t": 3, "y": 3.0}, {"t": 5, "y": 4.0}, {"t": 10, "y": 5.0}]
    r = bootstrap_par_yield(rows, m=2, max_T=10)
    # 10년물 spot은 YTM(5.0%)보다 약간 위
    last = [o for o in r["out_rows"] if abs(o["T"] - 10) < 1e-6]
    assert last, "10y output expected"
    assert last[0]["zcont"] > 5.0, f"10y zcont {last[0]['zcont']:.3f}% expected > 5.0%"


def test_max_T_cap_warning():
    """20년 초과 입력 시 warning 발생, 부트스트랩 결과는 20년까지만."""
    rows = [{"t": 1, "y": 2.0}, {"t": 10, "y": 4.0}, {"t": 30, "y": 5.0}]
    r = bootstrap_par_yield(rows, m=2, max_T=20)
    assert r["warning"] is not None, "30y input should trigger warning"
    assert r["input_max"] == 30
    assert r["max_T_used"] == 20
    # 20년 초과 spot은 없어야 함
    for row in r["out_rows"]:
        assert row["T"] <= 20.0 + 1e-6


def test_reproducibility():
    """동일 입력 → 동일 결과 (결정론적 재현성)."""
    rows = [{"t": 1, "y": 3.5}, {"t": 3, "y": 4.0}, {"t": 5, "y": 4.5}]
    r1 = bootstrap_par_yield(rows, m=2, max_T=5)
    r2 = bootstrap_par_yield(rows, m=2, max_T=5)
    for k in r1["dfs"]:
        assert abs(r1["dfs"][k] - r2["dfs"][k]) < 1e-15


def test_spot_curve_format():
    """spot_curve_from_bootstrap이 api/app.py의 rf_spot 형식과 일치."""
    rows = [{"t": 1, "y": 2.5}, {"t": 5, "y": 4.0}]
    r = bootstrap_par_yield(rows, m=2, max_T=5)
    sc = spot_curve_from_bootstrap(r)
    assert all(isinstance(t, float) and isinstance(z, float) for t, z in sc)
    assert all(0 < z < 1 for t, z in sc), "z는 decimal (0~1 사이)"


if __name__ == "__main__":
    test_flat_curve_recovers_ytm()
    test_upward_curve_spot_above_ytm()
    test_max_T_cap_warning()
    test_reproducibility()
    test_spot_curve_format()
    print("All bootstrap tests PASSED")
