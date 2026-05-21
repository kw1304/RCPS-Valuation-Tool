"""
RCPS 이항모형 (CRR) v2 — 5803 구조 기반

3-component 분해:
  ① 채권가치   (bond_value)       : 전환/풋 없는 순채권 PV
  ② 풋옵션가치 (put_option_value) : 풋 채권 - 순채권
  ③ 전환권가치 (conversion_value) : 총 FV - 풋 채권

기본 스텝: T × 12 (월별)
풋 행사가: face × (1+IRR)^(발행일→노드 경과연수)
"""
import numpy as np
from datetime import date
from inputs.deal_params import RCPSParams


def rcps_binomial(params: RCPSParams, steps: int = None) -> dict:
    T = params.T
    if T <= 0:
        raise ValueError("평가기준일이 만기일 이후입니다.")

    if steps is None:
        steps = max(int(round(T * 12)), 12)

    dt = T / steps
    S0 = params.stock_price
    sigma = params.volatility
    r_f = params.risk_free_rate
    q = params.dividend_yield
    face = params.face_value
    K = params.conversion_price if params.conversion_price > 0 else face
    K_floor = K * params.refixing_floor if (params.refixing and params.refixing_floor) else K
    Kd = params.discount_rate

    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp((r_f - q) * dt) - d) / (u - d)

    if not (0 < p < 1):
        raise ValueError(f"위험중립확률 범위 오류: p={p:.4f}. 변동성/금리 확인 필요")

    disc = np.exp(-Kd * dt)

    # ── 스텝별 사전 계산: 쿠폰, 전환·풋 가능 여부
    coupon_cf = _coupon_schedule(params, steps, dt)      # step→쿠폰 금액
    conv_step = _date_to_step(params.conversion_start, params, steps)
    put_step  = _date_to_step(params.put_start, params, steps)

    # ── 주가 트리 (말단 노드)
    S_terminal = np.array([S0 * (u ** (steps - j)) * (d ** j) for j in range(steps + 1)])

    # ── 1. 순채권 (전환·풋 없음)
    bond_val = _bond_only(face, params, disc, p, steps, dt, coupon_cf)

    # ── 2. 풋 채권 (풋만, 전환 없음)
    put_bond_val = _puttable_bond(face, params, disc, p, steps, dt, coupon_cf,
                                   put_step, S0, u, d, K, K_floor)

    # ── 3. 전환+풋 전체 RCPS (순수 CRR, 단일 Kd 할인)
    total_val = _crr_full(face, params, Kd, steps, dt, coupon_cf, conv_step, put_step,
                          S0, u, d, p, K, K_floor)

    return {
        "fair_value":        round(total_val),
        "bond_value":        round(bond_val),
        "put_bond_value":    round(put_bond_val),
        "put_option_value":  round(put_bond_val - bond_val),
        "conversion_value":  round(total_val - put_bond_val),
        "equity_component":  round(total_val - put_bond_val),   # 전환권 = total - put bond
        "bond_component":    round(put_bond_val),
        "steps":             steps,
        "dt":                dt,
        "u":                 u,
        "d":                 d,
        "risk_neutral_prob": p,
        "Kd":                Kd,
        "time_to_maturity":  T,
        "model":             "CRR Binomial (월별 스텝, 단일Kd)",
    }


# ─────────────────────────────────────────────────
# 보조 함수
# ─────────────────────────────────────────────────

def _coupon_schedule(params: RCPSParams, steps: int, dt: float) -> dict:
    """
    각 스텝에서 지급되는 우선배당(쿠폰) 금액 → {step: amount}.

    누적적(cumulative) 우선주 기준: 배당은 **발행일부터** interval 간격으로 누적되며,
    발행~만기 전체 기간의 배당이 모두 지급 대상이다.
    평가일 이전에 도래한 배당(미지급 누적분)은 평가일 이후 **첫 지급일에 합산**한다.
    (5803 레퍼런스 동일 — 평가일 기준이 아니라 발행일 기준 전체 배당 반영)
    """
    cf = {}
    rate = params.coupon_rate
    freq = params.coupon_frequency
    if rate <= 0 or freq == "none":
        return cf

    interval = {"annual": 1.0, "semi": 0.5, "quarterly": 0.25}.get(freq)
    if not interval:
        return cf

    per = params.face_value * rate * interval     # 1회 배당액
    tiv = params.t_issue_to_val                    # 발행→평가 경과연수
    T = steps * dt                                 # 평가→만기 잔존연수
    n = int(round((tiv + T) / interval))           # 발행~만기 총 배당 횟수

    accrued = 0.0
    first_paid = False
    for k in range(1, n + 1):
        t_from_val = k * interval - tiv            # 발행+k·interval 시점의 평가일 기준 연수
        if t_from_val <= 1e-9:
            accrued += per                         # 평가일 이전 도래 → 누적(미지급)
            continue
        step = min(max(int(round(t_from_val / dt)), 1), steps)
        cf[step] = cf.get(step, 0.0) + per + (accrued if not first_paid else 0.0)
        accrued = 0.0
        first_paid = True

    # 모든 배당일이 평가일 이전이었던 경우(누적분만 남음) → 만기에 일괄 지급
    if accrued > 0:
        cf[steps] = cf.get(steps, 0.0) + accrued

    return cf


def _at(x, i):
    """disc/p 가 per-step 시퀀스면 x[i], 스칼라면 x 반환"""
    if isinstance(x, (list, tuple, np.ndarray)):
        return x[i]
    return x


def _bond_only(face, params: RCPSParams, disc, p, steps, dt, coupon_cf) -> float:
    """순채권(bond floor) PV: 쿠폰 + 만기 보장상환액, 조기 풋·전환 없음.
    만기 상환 = max(face, 만기 풋행사가) — 보장수익률(IRR) 상환이 있으면 그 누적액.
    풋옵션가치 = puttable_bond − bond_only = 조기행사 프리미엄.
    disc/p 는 스칼라 또는 per-step 배열."""
    t_mat = steps * dt
    redeem = params.put_exercise_price(t_mat) if params.has_put else face
    V = np.full(steps + 1, max(face, redeem))

    # 만기 쿠폰
    if steps in coupon_cf:
        V += coupon_cf[steps]

    for i in range(steps - 1, -1, -1):
        di, pi = _at(disc, i), _at(p, i)
        V_new = di * (pi * V[:i + 1] + (1 - pi) * V[1:i + 2])
        if i in coupon_cf:
            V_new += coupon_cf[i]
        V = V_new

    return float(V[0])


def _puttable_bond(face, params: RCPSParams, disc, p, steps, dt, coupon_cf,
                   put_step, S0, u, d, K, K_floor) -> float:
    """풋 채권 PV: 쿠폰 + 만기상환 + 풋옵션. disc/p 는 스칼라 또는 per-step 배열."""
    # 만기 페이오프: max(순채권 상환, 풋 행사가)
    t_mat = steps * dt
    put_mat = params.put_exercise_price(t_mat) if params.has_put else face

    V = np.full(steps + 1, max(face, put_mat))
    if steps in coupon_cf:
        V += coupon_cf[steps]

    for i in range(steps - 1, -1, -1):
        di, pi = _at(disc, i), _at(p, i)
        V_new = di * (pi * V[:i + 1] + (1 - pi) * V[1:i + 2])
        if i in coupon_cf:
            V_new += coupon_cf[i]

        # 풋 행사 가능 구간
        if i >= put_step and params.has_put:
            t_node = i * dt
            put_ex = params.put_exercise_price(t_node)
            V_new = np.maximum(V_new, put_ex)

        V = V_new

    return float(V[0])


def _crr_full(face, params: RCPSParams, Kd, steps, dt, coupon_cf,
              conv_step, put_step, S0, u, d, p, K, K_floor) -> float:
    """표준 CRR: 단일 Kd 할인, max(보유, 전환, 풋)"""
    disc = np.exp(-Kd * dt)
    t_mat = steps * dt
    put_mat = params.put_exercise_price(t_mat) if params.put_irr > 0 else face
    mat_redeem = max(face, put_mat) + coupon_cf.get(steps, 0)

    V = np.zeros(steps + 1)
    for j in range(steps + 1):
        S_T = S0 * (u ** (steps - j)) * (d ** j)
        K_eff = _eff_K(S_T, K, K_floor, params, steps, steps)
        conv_val = (face / K_eff) * S_T if K_eff > 0 else 0
        V[j] = max(conv_val, mat_redeem)

    for i in range(steps - 1, -1, -1):
        t_node = i * dt
        V_new = disc * (p * V[:i + 1] + (1 - p) * V[1:i + 2]) + coupon_cf.get(i, 0)
        for j in range(i + 1):
            S = S0 * (u ** (i - j)) * (d ** j)
            K_eff = _eff_K(S, K, K_floor, params, i, steps)
            conv_val = (face / K_eff) * S if K_eff > 0 else 0
            node_val = V_new[j]
            if i >= put_step and params.put_irr > 0:
                node_val = max(node_val, params.put_exercise_price(t_node))
            if i >= conv_step:
                node_val = max(node_val, conv_val)
            V_new[j] = node_val
        V = V_new

    return float(V[0])


def _full_rcps_tf(face, params: RCPSParams, r_f, Kd, q, steps, dt,
                  coupon_cf, conv_step, put_step, S0, u, d, p, K, K_floor) -> tuple:
    """
    TF 분리 할인 (Tsiveriotis-Fernandes) + 풋옵션:
      E: 지분 컴포넌트 (전환 → 주식 가치) → Rf 할인
      B: 채권 컴포넌트 (쿠폰 + 상환 + 풋) → Kd 할인
      총 FV = E + B
    """
    disc_f = np.exp(-r_f * dt)
    disc_d = np.exp(-Kd * dt)

    # 만기 페이오프
    t_mat = steps * dt
    put_mat = params.put_exercise_price(t_mat)
    mat_coupon = coupon_cf.get(steps, 0)

    E = np.zeros(steps + 1)
    B = np.zeros(steps + 1)

    for j in range(steps + 1):
        S_T = S0 * (u ** (steps - j)) * (d ** j)
        K_eff = _eff_K(S_T, K, K_floor, params, steps, steps)
        conv_val = (face / K_eff) * S_T if K_eff > 0 else 0
        redeem_val = max(face, put_mat) + mat_coupon

        if conv_val >= redeem_val:
            E[j] = conv_val
            B[j] = 0.0
        else:
            E[j] = 0.0
            B[j] = redeem_val

    for i in range(steps - 1, -1, -1):
        t_node = i * dt
        E_new = np.zeros(i + 1)
        B_new = np.zeros(i + 1)
        coup = coupon_cf.get(i, 0)

        for j in range(i + 1):
            S = S0 * (u ** (i - j)) * (d ** j)
            K_eff = _eff_K(S, K, K_floor, params, i, steps)
            conv_val = (face / K_eff) * S if K_eff > 0 else 0

            E_hold = disc_f * (p * E[j] + (1 - p) * E[j + 1])
            B_hold = coup + disc_d * (p * B[j] + (1 - p) * B[j + 1])
            V_hold = E_hold + B_hold

            # 풋 행사 가능 구간
            if i >= put_step and params.put_irr > 0:
                put_ex = params.put_exercise_price(t_node)
                if put_ex > V_hold:
                    E_new[j] = 0.0
                    B_new[j] = put_ex
                    continue

            # 전환 가능 구간
            if i >= conv_step and conv_val > V_hold:
                E_new[j] = conv_val
                B_new[j] = 0.0
            else:
                E_new[j] = E_hold
                B_new[j] = B_hold

        E = E_new
        B = B_new

    return float(E[0] + B[0]), float(E[0]), float(B[0])


def _eff_K(S, K, K_floor, params: RCPSParams, step: int, steps: int) -> float:
    if not params.refixing or K <= 0:
        return K
    if not params.is_refixing_date(step, steps):
        return K
    if params.refixing_trigger and S < K * params.refixing_trigger:
        return max(K_floor, S)
    return K


def _date_to_step(target, params: RCPSParams, steps: int) -> int:
    if target is None:
        return steps  # 해당 없으면 만기 이후
    days = (target - params.valuation_date).days
    if days <= 0:
        return 0
    return min(int(days / (params.T * 365) * steps), steps)
