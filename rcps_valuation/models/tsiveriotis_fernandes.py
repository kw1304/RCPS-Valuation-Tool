import numpy as np
from inputs.deal_params import RCPSParams


def tf_rcps(params: RCPSParams, steps: int = None,
            rf_curve=None, kd_curve=None,
            bond_discrete: bool = False,
            collect_tree: bool = False) -> dict:
    """Tsiveriotis-Fernandes (TF) 모형 — 지분(Rf)/채권(Kd) 분리 할인

    Optional kwargs
    ---------------
    rf_curve : list[float] of length `steps`
        Per-step forward risk-free rates.  rf_curve[i] is used for period i→i+1.
        If None, falls back to flat params.risk_free_rate everywhere.
    kd_curve : list[float] of length `steps`
        Per-step forward credit-adjusted discount rates (Kd).
        If None, falls back to flat params.discount_rate everywhere.
    bond_discrete : bool (default False)
        When True, discount the bond component with DISCRETE compounding
        1/((1+kd)**dt) instead of exp(-kd*dt).  Required to match the
        Korean "노드희석_구분할인" reference answer.
    """
    T = params.T
    if T <= 0:
        raise ValueError("평가기준일이 만기일 이후입니다.")

    if steps is None:
        steps = max(int(round(T * 12)), 12)

    dt = T / steps
    S0 = params.stock_price
    sigma = params.volatility
    r_f = params.risk_free_rate
    r_d = params.discount_rate
    q = params.dividend_yield
    face = params.face_value
    K = params.conversion_price if params.conversion_price > 0 else face
    K_floor = K * params.refixing_floor if (params.refixing and params.refixing_floor) else K

    u = np.exp(sigma * np.sqrt(dt))
    d_fac = 1.0 / u

    # ── 희석 경로 여부
    use_dil = bool(params.common_shares and params.rcps_shares)
    n_com = float(params.common_shares) if use_dil else None
    n_rcps = float(params.rcps_shares) if use_dil else None

    # ── 쿠폰 스케줄
    from models.binomial_v2 import _coupon_schedule
    coupon_cf = _coupon_schedule(params, steps, dt)

    conv_step = _date_to_step(params.conversion_start, params, steps)
    put_step  = _date_to_step(params.put_start, params, steps)
    call_step = _date_to_step(params.call_start, params, steps)
    call_active = params.has_call

    # ── bond_pv[i] = 채권 컴포넌트 사전 계산 (희석경로 전용)
    # 만기에서 put 보장 상환액으로 시작, Kd forward 로 역방향 할인
    # put_start 이후에는 put_exercise_price 하한 적용
    if use_dil:
        bond_pv = [0.0] * (steps + 1)
        redeem_at = [params.put_exercise_price(i * dt) for i in range(steps + 1)]
        # 만기: max(face, put_exercise_price(T)) + 만기쿠폰
        bond_pv[steps] = max(face, redeem_at[steps]) + coupon_cf.get(steps, 0)
        for i in range(steps - 1, -1, -1):
            kd_i = kd_curve[i] if kd_curve else r_d
            if bond_discrete:
                disc_b = 1.0 / ((1.0 + kd_i) ** dt)
            else:
                disc_b = np.exp(-kd_i * dt)
            pv = bond_pv[i + 1] * disc_b + coupon_cf.get(i, 0)
            if i >= put_step:
                pv = max(pv, redeem_at[i])
            bond_pv[i] = pv
    else:
        bond_pv = None

    # ── 만기 페이오프
    t_mat = steps * dt
    put_mat = params.put_exercise_price(t_mat)
    mat_redeem = max(face, put_mat) + coupon_cf.get(steps, 0)

    E = np.zeros(steps + 1)
    B = np.zeros(steps + 1)

    # Helper closures
    def _ratio(i, j):
        """리픽싱 비율: 희석경로 전용. 동적 시가연동 — 새 전환가 = max(K_floor, 시가)
        (비희석 _eff_K 와 일관). trigger==floor 이면 K/K_floor 와 동일."""
        S = S0 * (u ** (i - j)) * (d_fac ** j)
        if params.refixing and params.is_refixing_date(i, steps):
            trigger_price = K * (params.refixing_trigger if params.refixing_trigger else 1.0)
            if S <= trigger_price:
                return K / max(K_floor, S)
        return 1.0

    def _diluted(i, j):
        """희석주가: (S*n_com + bond_pv[i]*n_rcps) / (n_com + n_rcps*ratio)"""
        S = S0 * (u ** (i - j)) * (d_fac ** j)
        r = _ratio(i, j)
        return (S * n_com + bond_pv[i] * n_rcps) / (n_com + n_rcps * r)

    def _conv_val_dil(i, j):
        """희석경로 전환가치 = diluted_price * ratio"""
        if i < conv_step:
            return 0.0
        return _diluted(i, j) * _ratio(i, j)

    # 단계별 rf/kd 조회
    def _rf(step_idx):
        """step_idx→step_idx+1 구간 rf (0-based)"""
        if rf_curve:
            return rf_curve[step_idx]
        return r_f

    def _kd(step_idx):
        if kd_curve:
            return kd_curve[step_idx]
        return r_d

    # 단계별 p 조회: p_of(i) uses rf of step i-1→i (matching reference p_of(i): rf[i-1])
    # In the reference: p_of(i) = (exp(rf[i-1]*dt)-d)/(u-d) for backward step i
    # We compute p for the period ending at step i: uses rf_curve[i-1]
    def _p(step_end):
        """위험중립확률 for the period ending at step_end"""
        rf_i = _rf(step_end - 1) if rf_curve else r_f
        return (np.exp((rf_i - q) * dt) - d_fac) / (u - d_fac)

    # 정적 (flat) 확률/할인인수 (no-dilution 경로용)
    p_flat = (np.exp((r_f - q) * dt) - d_fac) / (u - d_fac)
    if not (0 < p_flat < 1):
        raise ValueError(f"위험중립확률 범위 오류: p={p_flat:.4f}")
    disc_f_flat = np.exp(-r_f * dt)
    disc_d_flat = np.exp(-r_d * dt)

    # ── 트리 수집용 그리드 초기화 (collect_tree=True 일 때만)
    if collect_tree:
        _g_stock      = [[0.0]*(i+1) for i in range(steps+1)]
        _g_eq         = [[0.0]*(i+1) for i in range(steps+1)]
        _g_bond       = [[0.0]*(i+1) for i in range(steps+1)]
        _g_rcps       = [[0.0]*(i+1) for i in range(steps+1)]
        _g_conv       = [[0.0]*(i+1) for i in range(steps+1)]
        _g_dil        = [[0.0]*(i+1) for i in range(steps+1)]
        _g_dec        = [[""  ]*(i+1) for i in range(steps+1)]
        _g_hold_val   = [[0.0]*(i+1) for i in range(steps+1)]  # 총 보유가치
        _g_eq_hold    = [[0.0]*(i+1) for i in range(steps+1)]  # 지분 보유가치
        _g_bond_hold  = [[0.0]*(i+1) for i in range(steps+1)]  # 채권 보유가치

    # ── 만기 노드 초기화
    for j in range(steps + 1):
        S_T = S0 * (u ** (steps - j)) * (d_fac ** j)
        if use_dil:
            cv = _conv_val_dil(steps, j)
        else:
            K_eff = _eff_K(S_T, K, K_floor, params, steps, steps)
            cv = (face / K_eff) * S_T if K_eff > 0 else 0
        if cv >= mat_redeem:
            E[j] = cv; B[j] = 0.0
        else:
            E[j] = 0.0; B[j] = mat_redeem
        if collect_tree:
            _g_stock[steps][j] = round(S_T, 2)
            _g_eq[steps][j]    = round(float(E[j]), 2)
            _g_bond[steps][j]  = round(float(B[j]), 2)
            _g_rcps[steps][j]  = round(float(E[j] + B[j]), 2)
            _g_conv[steps][j]  = round(cv, 2)
            _g_dil[steps][j]   = round(float(_diluted(steps, j)) if use_dil else S_T, 2)
            _g_dec[steps][j]   = "전환" if cv >= mat_redeem else "상환"

    # ── 역방향 귀납
    for i in range(steps - 1, -1, -1):
        t_node = i * dt
        coup = coupon_cf.get(i, 0)
        E_new = np.zeros(i + 1)
        B_new = np.zeros(i + 1)

        if rf_curve or kd_curve:
            # 커브 모드: step-level p/discount
            p_i = _p(i + 1)
            q_i = 1.0 - p_i
            kd_i = _kd(i)
            rf_i = _rf(i)
            disc_f_i = np.exp(-rf_i * dt)
            if bond_discrete:
                disc_d_i = 1.0 / ((1.0 + kd_i) ** dt)
            else:
                disc_d_i = np.exp(-kd_i * dt)
        else:
            p_i = p_flat; q_i = 1.0 - p_flat
            disc_f_i = disc_f_flat
            disc_d_i = disc_d_flat

        for j in range(i + 1):
            S = S0 * (u ** (i - j)) * (d_fac ** j)

            if use_dil:
                cv = _conv_val_dil(i, j)
            else:
                K_eff = _eff_K(S, K, K_floor, params, i, steps)
                cv = (face / K_eff) * S if K_eff > 0 else 0

            E_hold = disc_f_i * (p_i * E[j] + q_i * E[j + 1])
            B_hold = coup + disc_d_i * (p_i * B[j] + q_i * B[j + 1])
            V_hold = E_hold + B_hold

            if collect_tree:
                _g_hold_val[i][j]  = round(V_hold, 2)
                _g_eq_hold[i][j]   = round(E_hold, 2)
                _g_bond_hold[i][j] = round(B_hold, 2)

            # ── 발행자 콜 캡 (수의상환권): issuer calls when call_ex < V_hold
            cont_E = E_hold
            cont_B = B_hold
            if call_active and i >= call_step:
                call_ex = params.call_exercise_price(t_node)
                if call_ex < V_hold:
                    cont_E = 0.0
                    cont_B = call_ex
            cont_tot = cont_E + cont_B

            # ── 투자자 옵션 (put / conversion)
            if i >= put_step and params.has_put:
                put_ex = params.put_exercise_price(t_node)
                if put_ex > cont_tot:
                    E_new[j] = 0.0; B_new[j] = put_ex
                    if collect_tree:
                        _g_stock[i][j] = round(S, 2)
                        _g_eq[i][j]    = 0.0
                        _g_bond[i][j]  = round(put_ex, 2)
                        _g_rcps[i][j]  = round(put_ex, 2)
                        _g_conv[i][j]  = round(cv, 2)
                        _g_dil[i][j]   = round(float(_diluted(i, j)) if use_dil else S, 2)
                        _g_dec[i][j]   = "상환"
                    continue

            if i >= conv_step and cv > cont_tot:
                E_new[j] = cv; B_new[j] = 0.0
                if collect_tree:
                    _g_dec[i][j] = "전환"
            else:
                E_new[j] = cont_E; B_new[j] = cont_B
                if collect_tree:
                    _g_dec[i][j] = "콜" if (call_active and i >= call_step and
                                              params.call_exercise_price(t_node) < V_hold) else "보유"

            if collect_tree:
                _g_stock[i][j] = round(S, 2)
                _g_eq[i][j]    = round(float(E_new[j]), 2)
                _g_bond[i][j]  = round(float(B_new[j]), 2)
                _g_rcps[i][j]  = round(float(E_new[j] + B_new[j]), 2)
                _g_conv[i][j]  = round(cv, 2)
                _g_dil[i][j]   = round(float(_diluted(i, j)) if use_dil else S, 2)

        E = E_new; B = B_new

    fair_value = float(E[0] + B[0])

    # 희석 주가 (루트 노드)
    diluted_s0 = float(_diluted(0, 0)) if use_dil else None

    # ── 3-component 분해: 순채권/풋옵션/전환권 (메인 재귀와 동일한 할인 적용)
    from models.binomial_v2 import _bond_only, _puttable_bond
    if rf_curve or kd_curve:
        # per-step kd 곡선 + 이산/연속 컨벤션 (메인 disc_d_i 와 동일)
        disc_d_report = [
            (1.0 / ((1.0 + _kd(i)) ** dt)) if bond_discrete else float(np.exp(-_kd(i) * dt))
            for i in range(steps)
        ]
        p_report = [_p(i + 1) for i in range(steps)]
    else:
        disc_d_report = disc_d_flat  # flat (bond_discrete 반영)
        p_report = p_flat
    bv  = _bond_only(face, params, disc_d_report, p_report, steps, dt, coupon_cf)
    pbv = _puttable_bond(face, params, disc_d_report, p_report, steps, dt, coupon_cf,
                         put_step, S0, u, d_fac, K, K_floor)

    out = {
        "fair_value":             round(fair_value),
        "bond_value":             round(bv),
        "put_bond_value":         round(pbv),
        "put_option_value":       round(pbv - bv),
        "conversion_value":       round(fair_value - pbv),
        "equity_component":       round(float(E[0])),
        "bond_component":         round(float(B[0])),
        "steps":                  steps,
        "model":                  "Tsiveriotis-Fernandes",
        "rf_used":                r_f,
        "kd_used":                r_d,
        "dilution_applied":       bool(use_dil),
        "diluted_stock_price_0":  round(diluted_s0, 6) if diluted_s0 is not None else None,
    }
    if collect_tree:
        p_scalar = (rf_curve if rf_curve else p_flat) if rf_curve else p_flat
        out["tree"] = {
            "stock":          _g_stock,
            "decision":       _g_dec,
            "rcps_value":     _g_rcps,
            "conv_intrinsic": _g_conv,
            "diluted":        _g_dil,
            "equity_comp":    _g_eq,
            "bond_comp":      _g_bond,
            "hold_value":     _g_hold_val,
            "equity_hold":    _g_eq_hold,
            "bond_hold":      _g_bond_hold,
            "u":    round(float(u), 6),
            "d":    round(float(d_fac), 6),
            "steps": steps,
            "p":    ([round(float(_p(i+1)), 6) for i in range(steps)] if rf_curve
                     else round(float(p_flat), 6)),
        }
    return out


def _eff_K(S, K, K_floor, params, step, steps):
    if not params.refixing or K <= 0: return K
    if not params.is_refixing_date(step, steps): return K
    if params.refixing_trigger and S < K * params.refixing_trigger:
        return max(K_floor, S)
    return K


def _date_to_step(target, params, steps):
    if target is None: return steps
    days = (target - params.valuation_date).days
    if days <= 0: return 0
    return min(int(round(days / (params.T * 365) * steps)), steps)
