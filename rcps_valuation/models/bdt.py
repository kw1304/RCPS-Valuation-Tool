"""Black-Derman-Toy(BDT) 단기금리 이항트리 — 풋옵션부 채권 교차검증.

RCPS 평가 구조 중 ② 풋채권가치를 TF/GS의 주가-트리 + 결정론적 금리 방식과
독립적으로, 발행사 RD(신용조정) 곡선·금리변동성을 입력으로 BDT 트리를
캘리브레이션하여 평가한다. 결과:
  - put_bond_value (풋옵션부 채권가치)
  - bond_value      (풋 없는 일반채권가치)
  - put_option_value = put_bond_value − bond_value

수학적 가정:
  - 단기금리 r(i,j) = r(i,0) × exp(2 j σ √dt)  (lognormal short rate)
  - 위험중립 확률 q = 0.5/0.5 (BDT 관행)
  - 변동성 σ는 일정(constant) — 기본형
  - 캘리브레이션: 각 스텝의 r(i,0)을 한 스텝짜리 zero 가격이
    시장 zero 가격 P(0, (i+1)·dt) = exp(-z·(i+1)dt) 와 같아지도록 bisection.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple


def _interp_zero(spot_pts: Sequence[Sequence[float]], t: float) -> float:
    """연속복리 zero rate z(t) 선형보간 + 평탄 외삽 (app.py와 동일 컨벤션)."""
    pts = sorted((float(p[0]), float(p[1])) for p in spot_pts if p[0] and p[1] is not None)
    if not pts:
        return 0.0
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for k in range(len(pts) - 1):
        t0, z0 = pts[k]
        t1, z1 = pts[k + 1]
        if t0 <= t <= t1:
            return z0 + (z1 - z0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def calibrate_bdt(zero_rates: List[float], dt: float, sigma: float,
                  max_iter: int = 80, tol: float = 1e-10) -> List[List[float]]:
    """BDT 단기금리 트리 캘리브레이션 (constant volatility).

    zero_rates: 길이 N+1. zero_rates[i] = i·dt 만기의 연속 zero rate (zero_rates[0]은 0이거나 무시).
    Returns r[i][j] (i=0..N-1, j=0..i).
    """
    N = len(zero_rates) - 1
    if N <= 0:
        return []
    sd = sigma * math.sqrt(dt)
    r: List[List[float]] = [[] for _ in range(N)]

    # 스텝 0: 한 스텝짜리 zero 가격 매칭 → r(0,0) = z(dt)
    r[0] = [zero_rates[1]]

    for i in range(1, N):
        # 시장가격: P(0, (i+1)·dt) = exp(-z·(i+1)dt)
        T_i1 = (i + 1) * dt
        target_P = math.exp(-zero_rates[i + 1] * T_i1)

        def model_P(r0: float) -> float:
            """후보 r(i,0) 으로 i+1 만기 zero 가격을 트리에서 산정."""
            r_i = [r0 * math.exp(2 * j * sd) for j in range(i + 1)]
            # 만기(스텝 i+1)에서 V=1. 스텝 i에서 한 칸 할인:
            V = [math.exp(-rij * dt) for rij in r_i]
            # 스텝 i-1 → 0 까지 후방귀납 (q=0.5)
            for s in range(i - 1, -1, -1):
                V = [math.exp(-r[s][j] * dt) * 0.5 * (V[j + 1] + V[j])
                     for j in range(s + 1)]
            return V[0]

        # bisection: r0↑ → 모델가격↓ (monotone decreasing in r0)
        lo, hi = 1e-7, 1.0
        mid = 0.5 * (lo + hi)
        for _ in range(max_iter):
            mid = 0.5 * (lo + hi)
            if model_P(mid) > target_P:
                lo = mid
            else:
                hi = mid
            if hi - lo < tol:
                break
        r[i] = [mid * math.exp(2 * j * sd) for j in range(i + 1)]

    return r


def price_bond_on_bdt(r_tree: List[List[float]], dt: float, face: float,
                      coupon_schedule: Dict[int, float],
                      put_schedule: Optional[Dict[int, float]] = None) -> float:
    """BDT 트리 위 채권 후방귀납.

    coupon_schedule: {step: 지급액}.
    put_schedule: {step: 풋 행사가}. 그 스텝에서 max(계속가치, 풋가). None=일반채권.
    만기(step N)에서 V_N = max(face, put_schedule.get(N, face)) + coupon[N].
    """
    N = len(r_tree)
    put_mat = (put_schedule or {}).get(N, face)
    V = [max(face, put_mat) + coupon_schedule.get(N, 0.0)] * (N + 1)
    for i in range(N - 1, -1, -1):
        new_V = []
        for j in range(i + 1):
            disc = math.exp(-r_tree[i][j] * dt)
            cont = disc * 0.5 * (V[j + 1] + V[j])
            if i in coupon_schedule:
                cont += coupon_schedule[i]
            if put_schedule and i in put_schedule:
                cont = max(cont, put_schedule[i])
            new_V.append(cont)
        V = new_V
    return float(V[0])


def evaluate_bdt_bond(rd_spot: Sequence[Sequence[float]], T: float, steps: int,
                      sigma: float, face: float,
                      coupon_schedule: Dict[int, float],
                      put_schedule: Dict[int, float]) -> dict:
    """RCPS 풋채권 BDT 교차평가. RD(신용조정) 곡선 + 금리변동성으로 캘리브레이션.

    Returns {put_bond_value, bond_value, put_option_value, sigma, n_steps}.
    """
    dt = T / steps
    zero_rates = [0.0] + [_interp_zero(rd_spot, (i + 1) * dt) for i in range(steps)]
    tree = calibrate_bdt(zero_rates, dt, sigma)
    pbv = price_bond_on_bdt(tree, dt, face, coupon_schedule, put_schedule=put_schedule)
    bv = price_bond_on_bdt(tree, dt, face, coupon_schedule, put_schedule=None)
    return {
        "put_bond_value": round(pbv),
        "bond_value": round(bv),
        "put_option_value": round(pbv - bv),
        "sigma": sigma,
        "n_steps": steps,
        "dt": dt,
    }
