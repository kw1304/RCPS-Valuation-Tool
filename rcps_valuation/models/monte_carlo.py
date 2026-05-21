import numpy as np
from inputs.deal_params import RCPSParams


def monte_carlo_rcps(params: RCPSParams, n_paths: int = 10000, n_steps: int = None) -> dict:
    """RCPS 몬테카를로 (Tsiveriotis-Fernandes 2성분 LSM, Antithetic Variates)

    경로별 가치를 지분(E)·채권(B) 두 성분으로 분리해 TF와 동일하게 할인:
      - 지분(전환) 요소 E : 무위험 rf 연속복리  exp(-rf·dt)
      - 채권(상환·쿠폰) 요소 B : 신용조정 Kd 이산복리  (1+Kd)^(-dt)
    조기 전환·풋 행사 결정은 LSM(최소제곱회귀)로 추정한 계속가치와 비교.
    """
    T = params.T
    if T <= 0:
        raise ValueError("평가기준일이 만기일 이후입니다.")

    if n_steps is None:
        n_steps = max(int(round(T * 12)), 12)

    dt = T / n_steps
    S0 = params.stock_price
    sigma = params.volatility
    r = params.risk_free_rate
    q = params.dividend_yield
    r_d = params.discount_rate
    face = params.face_value
    K = params.conversion_price if params.conversion_price > 0 else face

    # ── TF 정합 할인계수: 지분=rf, 채권=Kd 모두 연속복리 (연속스팟 정합) ──
    disc_rf = np.exp(-r * dt)
    disc_kd = np.exp(-r_d * dt)

    half = n_paths // 2
    Z = np.random.standard_normal((half, n_steps))
    Z = np.vstack([Z, -Z])
    S = np.empty((n_paths, n_steps + 1))
    S[:, 0] = S0
    ld = (r - q - 0.5 * sigma**2) * dt          # 위험중립 드리프트 (레퍼런스 GBM 동일)
    vd = sigma * np.sqrt(dt)
    for t in range(n_steps):
        S[:, t+1] = S[:, t] * np.exp(ld + vd * Z[:, t])

    # 리픽싱
    K_eff = np.full(n_paths, float(K))
    if params.refixing and params.refixing_floor and params.refixing_trigger:
        Kfl = float(K * params.refixing_floor)
        Ktr = float(K * params.refixing_trigger)
        for t in range(1, n_steps + 1):
            if not params.is_refixing_date(t, n_steps): continue
            trig = S[:, t] < Ktr
            prop = np.maximum(Kfl, S[:, t])
            K_eff = np.where(trig & (prop < K_eff), prop, K_eff)

    conv_step = _date_to_step(params.conversion_start, params, n_steps)
    put_step  = _date_to_step(params.put_start, params, n_steps)

    from models.binomial_v2 import _coupon_schedule
    coupon_cf = _coupon_schedule(params, n_steps, dt)

    # ── 만기 가치: 전환 vs 상환 → E/B 버킷 분리 ──
    put_mat = params.put_exercise_price(n_steps * dt)
    redeem_T = max(face, put_mat)
    conv_T = (face / K_eff) * S[:, -1]
    converted = conv_T >= redeem_T
    E = np.where(converted, conv_T, 0.0)
    B = np.where(converted, 0.0, float(redeem_T))
    ever_conv = converted.copy()

    # ── 후방귀납 (TF 와 동일: E_hold=disc_rf·E, B_hold=coup+disc_kd·B) ──
    for t in range(n_steps - 1, -1, -1):
        coup = coupon_cf.get(t, 0)
        E = E * disc_rf
        B = coup + B * disc_kd
        V_hold = E + B

        conv_on = t >= conv_step
        put_on  = (t >= put_step and params.has_put)
        if not (conv_on or put_on):
            continue

        S_t = S[:, t]
        conv_val = (face / K_eff) * S_t if conv_on else None
        put_ex   = float(params.put_exercise_price(t * dt)) if put_on else None

        # 즉시 행사가치 (전환/풋 중 큰 값)
        imm = np.full(n_paths, -1.0)
        if conv_on: imm = np.maximum(imm, conv_val)
        if put_on:  imm = np.maximum(imm, put_ex)
        itm = imm > 0.0

        # LSM: 계속가치 E[V_hold | S_t] 추정 (in-the-money 경로만 회귀)
        cont = V_hold.copy()
        if int(itm.sum()) >= 50:
            x = S_t[itm] / S0
            X = np.column_stack([np.ones(x.size), x, x**2, x**3])
            try:
                c, _, _, _ = np.linalg.lstsq(X, V_hold[itm], rcond=None)
                cont[itm] = X @ c
            except Exception:
                pass

        do_ex = itm & (imm > cont)
        # 전환·풋 중 유리한 쪽으로 버킷 배정
        if conv_on and put_on:
            conv_better = conv_val >= put_ex
        elif conv_on:
            conv_better = np.ones(n_paths, dtype=bool)
        else:
            conv_better = np.zeros(n_paths, dtype=bool)
        do_conv = do_ex & conv_better
        do_put  = do_ex & (~conv_better)

        if conv_on:
            E = np.where(do_conv, conv_val, E)
            B = np.where(do_conv, 0.0, B)
            ever_conv = ever_conv | do_conv
        if put_on:
            E = np.where(do_put, 0.0, E)
            B = np.where(do_put, put_ex, B)

    V = E + B
    fv = float(np.mean(V))
    se = float(np.std(V, ddof=1) / np.sqrt(n_paths))
    return {
        "fair_value": round(fv),
        "std_error": round(se),
        "ci_lower": round(fv - 1.96 * se),
        "ci_upper": round(fv + 1.96 * se),
        "n_paths": n_paths,
        "n_steps": n_steps,
        "early_exercise_pct": round(float(ever_conv.mean() * 100), 1),
        "model": "Monte Carlo (TF 2-component LSM)",
    }


def _date_to_step(target, params, steps):
    if target is None: return steps
    days = (target - params.valuation_date).days
    if days <= 0: return 0
    return min(int(days / (params.T * 365) * steps), steps)
