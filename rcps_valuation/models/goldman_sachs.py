import numpy as np
from inputs.deal_params import RCPSParams


def gs_rcps(params: RCPSParams, steps: int = None,
            enterprise_value=None, net_debt=None,
            common_shares=None, rcps_shares=None,
            rf_curve=None, kd_curve=None,
            bond_discrete: bool = False,
            collect_tree: bool = False,
            **kw) -> dict:
    """Goldman Sachs 블렌딩 할인계수 모형 (노드희석 + 3-pass)

    Pass 1 : TF-style E/B 분리 역방향 귀납 → 노드별 결정(전환/상환/보유)
    Pass 2 : 앞방향으로 전환확률 cp[i][j] 계산
    Pass 3 : 블렌딩 할인계수 df = cp*exp(-rf*dt)+(1-cp)/(1+kd)^dt 으로
             후행 노드별 할인하여 최종 가치 산출

    Optional kwargs
    ---------------
    rf_curve : list[float] of length `steps`
        Per-step forward risk-free rates.  rf_curve[i] is used for period i→i+1.
        If None, falls back to flat params.risk_free_rate.
    kd_curve : list[float] of length `steps`
        Per-step forward credit-adjusted discount rates.
        If None, falls back to flat params.discount_rate.
    bond_discrete : bool (default False)
        When True, bond component discounted with discrete compounding
        1/((1+kd)**dt).  Required to match the reference answer.
    enterprise_value / net_debt : legacy kwargs, accepted but ignored when
        common_shares / rcps_shares are provided directly or via params.
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
    n_com_arg = common_shares if common_shares is not None else params.common_shares
    n_rcps_arg = rcps_shares if rcps_shares is not None else params.rcps_shares
    use_dil = bool(n_com_arg and n_rcps_arg)
    n_com = float(n_com_arg) if use_dil else None
    n_rcps = float(n_rcps_arg) if use_dil else None

    # ── 쿠폰 스케줄
    from models.binomial_v2 import _coupon_schedule
    coupon_cf = _coupon_schedule(params, steps, dt)

    conv_step = _date_to_step(params.conversion_start, params, steps)
    put_step  = _date_to_step(params.put_start, params, steps)
    call_step = _date_to_step(params.call_start, params, steps)
    call_active = params.has_call

    # ── 단계별 rf/kd 조회 헬퍼
    def _rf(step_idx):
        """step_idx→step_idx+1 구간 rf (0-based)"""
        if rf_curve:
            return rf_curve[step_idx]
        return r_f

    def _kd(step_idx):
        if kd_curve:
            return kd_curve[step_idx]
        return r_d

    # p_of(step_end): 구간 끝 스텝의 위험중립확률
    # 레퍼런스: p_of(i) = (exp(rf[i-1]*dt)-d)/(u-d)
    def _p(step_end):
        rf_i = _rf(step_end - 1) if rf_curve else r_f
        return (np.exp((rf_i - q) * dt) - d_fac) / (u - d_fac)

    # flat 확률/할인인수 (no-curve 경로)
    p_flat = (np.exp((r_f - q) * dt) - d_fac) / (u - d_fac)
    if not (0 < p_flat < 1):
        raise ValueError(f"위험중립확률 범위 오류: p={p_flat:.4f}")

    # ── bond_pv[i]: 희석경로 전용 사전 계산
    # 만기에서 Kd forward 로 역방향 할인, put_start 이후 put 하한 적용
    if use_dil:
        bond_pv = [0.0] * (steps + 1)
        # 풋이 유효(만기 전 시작)일 때만 풋 행사가 적용
        if params.has_put:
            redeem_at = [params.put_exercise_price(i * dt) for i in range(steps + 1)]
        else:
            redeem_at = [face] * (steps + 1)
        bond_pv[steps] = max(face, redeem_at[steps]) + coupon_cf.get(steps, 0)
        for i in range(steps - 1, -1, -1):
            kd_i = _kd(i)
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

    # ── 만기 상환액 (레퍼런스: redeem[N] = face*(1+put_rate)^N)
    # 풋이 유효(만기 전 시작)일 때만 풋 행사가 적용
    t_mat = steps * dt
    put_mat = params.put_exercise_price(t_mat) if params.has_put else face
    mat_redeem = max(face, put_mat) + coupon_cf.get(steps, 0)

    # ── 노드 주가
    def _S(i, j):
        return S0 * (u ** (i - j)) * (d_fac ** j)

    # ── 리픽싱 비율 (희석경로 전용): 동적 시가연동 — 새 전환가 = max(K_floor, 시가)
    #    (비희석 _eff_K 와 일관. trigger==floor 이면 K/K_floor 와 동일)
    def _ratio(i, j):
        S = _S(i, j)
        if params.refixing and params.is_refixing_date(i, steps):
            trigger_price = K * (params.refixing_trigger if params.refixing_trigger else 1.0)
            if S <= trigger_price:
                return K / max(K_floor, S)
        return 1.0

    # ── 희석주가: 전환 후 1주당 가격
    # 전환 시 회사가치 = 기존지분(n_com·S) + 부채흡수(bond_pv TOTAL)
    # 총 주식수 = n_com + n_rcps·ratio
    def _diluted(i, j):
        S = _S(i, j)
        r = _ratio(i, j)
        return (S * n_com + bond_pv[i]) / (n_com + n_rcps * r)

    # ── 전환가치 (희석 경로) — TOTAL 단위 (모든 RCPS 합산)
    # per-share post × n_rcps × ratio = 전환 시 RCPS 보유자가 받는 총 가치
    # (mat_redeem, _redeem, face 모두 TOTAL 단위 → 일관성 유지)
    def _conv_val_dil(i, j):
        if i < conv_step:
            return 0.0
        return _diluted(i, j) * _ratio(i, j) * n_rcps

    # ── 전환가치 (레거시 경로: (face/K_eff)*S)
    def _conv_val_leg(i, j):
        if i < conv_step:
            return 0.0
        S = _S(i, j)
        K_eff = _eff_K(S, K, K_floor, params, i, steps)
        return (face / K_eff) * S if K_eff > 0 else 0.0

    def _conv_val(i, j):
        return _conv_val_dil(i, j) if use_dil else _conv_val_leg(i, j)

    # ── 상환액 (put_start 이후에만 하한)
    def _redeem(i):
        if i >= put_step and params.has_put:
            return params.put_exercise_price(i * dt)
        return None

    # ════════════════════════════════════════════════════
    # PASS 1: TF-style E/B 분리 역방향 귀납 → 결정 그리드
    # ════════════════════════════════════════════════════
    # dec[i] = list of length (i+1), values: 'c'(전환)/'r'(상환)/'h'(보유)
    dec = [[None] * (i + 1) for i in range(steps + 1)]
    Er = [0.0] * (steps + 1)
    Br = [0.0] * (steps + 1)

    # 만기 초기화
    for j in range(steps + 1):
        ei = _conv_val(steps, j)
        rd = mat_redeem
        if ei >= rd:
            Er[j] = ei;  Br[j] = 0.0;  dec[steps][j] = 'c'
        else:
            Er[j] = 0.0; Br[j] = rd;   dec[steps][j] = 'r'

    # 역방향 귀납
    for i in range(steps - 1, -1, -1):
        coup = coupon_cf.get(i, 0)
        rd_i = _redeem(i)   # None or float

        if rf_curve or kd_curve:
            p_i = _p(i + 1)
            q_i = 1.0 - p_i
            kd_i = _kd(i)
            rf_i = _rf(i)
            disc_f_i = np.exp(-rf_i * dt)
            disc_d_i = (1.0 / ((1.0 + kd_i) ** dt)) if bond_discrete else np.exp(-kd_i * dt)
        else:
            p_i = p_flat;  q_i = 1.0 - p_flat
            disc_f_i = np.exp(-r_f * dt)
            disc_d_i = (1.0 / ((1.0 + r_d) ** dt)) if bond_discrete else np.exp(-r_d * dt)

        En = [0.0] * (i + 1)
        Bn = [0.0] * (i + 1)

        for j in range(i + 1):
            Eh = disc_f_i * (p_i * Er[j] + q_i * Er[j + 1])
            Bh = coup + disc_d_i * (p_i * Br[j] + q_i * Br[j + 1])
            hold = Eh + Bh

            ei = _conv_val(i, j)

            # ── 발행자 콜 캡 (수의상환권)
            cont_E = Eh
            cont_B = Bh
            call_triggered = False
            if call_active and i >= call_step:
                call_ex_p1 = params.call_exercise_price(i * dt)
                if call_ex_p1 < hold:
                    cont_E = 0.0
                    cont_B = call_ex_p1
                    call_triggered = True
            cont_hold = cont_E + cont_B

            # 레퍼런스 결정 로직 (call cap 적용 후 continuation 기준):
            if rd_i is not None:
                intr = max(ei, rd_i)
            else:
                intr = ei
            rcps = max(intr, cont_hold)

            if call_triggered and rcps == cont_hold:
                En[j] = cont_E; Bn[j] = cont_B; dec[i][j] = 'l'  # 'l' = call (콜)
            elif rcps == cont_hold or (ei < cont_hold and (rd_i is None or rd_i < cont_hold)):
                En[j] = cont_E; Bn[j] = cont_B; dec[i][j] = 'h'
            elif rd_i is not None and rd_i >= ei:
                En[j] = 0.0;   Bn[j] = rd_i;   dec[i][j] = 'r'
            else:
                En[j] = ei;    Bn[j] = 0.0;    dec[i][j] = 'c'

        Er = En
        Br = Bn

    # ════════════════════════════════════════════════════
    # PASS 2: 앞방향 전환확률 cp[i][j]
    # ════════════════════════════════════════════════════
    cp = [[0.0] * (i + 1) for i in range(steps + 1)]

    # 만기 확률
    for j in range(steps + 1):
        cp[steps][j] = 1.0 if dec[steps][j] == 'c' else 0.0

    # 앞방향 전파 (레퍼런스: 하향식 역방향이지만 결과적으로 동일)
    # cp[i][j] = 1 if 'c', 0 if 'r', p*cp[i+1][j]+q*cp[i+1][j+1] if 'h'
    for i in range(steps - 1, -1, -1):
        if rf_curve:
            p_i = _p(i + 1)
        else:
            p_i = p_flat
        q_i = 1.0 - p_i
        for j in range(i + 1):
            if dec[i][j] == 'c':
                cp[i][j] = 1.0
            elif dec[i][j] in ('r', 'l'):  # 상환 또는 콜: 전환 없음
                cp[i][j] = 0.0
            else:
                cp[i][j] = p_i * cp[i + 1][j] + q_i * cp[i + 1][j + 1]

    # ════════════════════════════════════════════════════
    # PASS 3: 블렌딩 할인계수 가치 산출
    # ════════════════════════════════════════════════════
    # dfac(child_i, j, period_idx):
    #   c = cp[child_i][j]
    #   return c*exp(-rf[period_idx]*dt) + (1-c)*(1/(1+kd[period_idx])^dt)
    # 레퍼런스에서 bond_discrete=True 이므로 항상 discrete Kd 사용
    # (GS 모형 정의상 본 pass 는 항상 discrete Kd 사용)
    def _dfac(child_i, j, period_idx):
        # 5803 방식: 금리를 블렌딩한 뒤 연속할인 exp(-(cp·rf+(1-cp)·Kd)·dt)
        # (DF 블렌딩이 아니라 RATE 블렌딩 — Jensen 차이로 결과가 달라짐)
        c = cp[child_i][j]
        dr = c * _rf(period_idx) + (1.0 - c) * _kd(period_idx)
        return float(np.exp(-dr * dt))

    # ── 트리 수집용 그리드 초기화 (collect_tree=True 일 때만)
    if collect_tree:
        _g_stock    = [[0.0]*(i+1) for i in range(steps+1)]
        _g_rcps     = [[0.0]*(i+1) for i in range(steps+1)]
        _g_conv     = [[0.0]*(i+1) for i in range(steps+1)]
        _g_dil      = [[0.0]*(i+1) for i in range(steps+1)]
        _g_cp       = [[0.0]*(i+1) for i in range(steps+1)]
        _g_df       = [[0.0]*(i+1) for i in range(steps+1)]
        _g_hold_val = [[0.0]*(i+1) for i in range(steps+1)]  # 총 보유가치 (terminal=0)
        # decision grid: map dec codes to Korean labels
        _dec_map = {'c': '전환', 'r': '상환', 'h': '보유', 'l': '콜'}
        _g_dec = [[_dec_map.get(dec[i][j], '') for j in range(i+1)]
                  for i in range(steps+1)]

    # 만기 페이오프: max(원금상환, 전환) + 만기쿠폰 (5803: 쿠폰은 max 밖에서 가산)
    _mat_principal = max(face, put_mat)
    _coup_mat = coupon_cf.get(steps, 0)
    V = [max(_conv_val(steps, j), _mat_principal) + _coup_mat for j in range(steps + 1)]

    if collect_tree:
        for j in range(steps + 1):
            S_T = _S(steps, j)
            _g_stock[steps][j] = round(S_T, 2)
            _g_rcps[steps][j]  = round(V[j], 2)
            _g_conv[steps][j]  = round(_conv_val(steps, j), 2)
            _g_dil[steps][j]   = round(float(_diluted(steps, j)) if use_dil else S_T, 2)
            _g_cp[steps][j]    = round(cp[steps][j], 6)
            _g_df[steps][j]    = 1.0  # terminal: no further discounting

    for i in range(steps - 1, -1, -1):
        if rf_curve:
            p_i = _p(i + 1)
        else:
            p_i = p_flat
        q_i = 1.0 - p_i

        Vn = [0.0] * (i + 1)
        for j in range(i + 1):
            # 각 후행 노드에 자신의 df 적용 (쿠폰은 별도 Kd strip 으로 합산)
            hold = (p_i * V[j]     * _dfac(i + 1, j,     i) +
                    q_i * V[j + 1] * _dfac(i + 1, j + 1, i))

            # ── 발행자 콜 캡 (Pass 3)
            cont_hold = hold
            if call_active and i >= call_step:
                call_ex_p3 = params.call_exercise_price(i * dt)
                if call_ex_p3 < hold:
                    cont_hold = call_ex_p3

            ei = _conv_val(i, j)
            rd_i = _redeem(i)
            if rd_i is not None:
                intr = max(ei, rd_i)
            else:
                intr = ei
            # 5803: value = max(MAT,PUT,CON,TIME) + INT (쿠폰은 결정 무관 현 노드 가산)
            Vn[j] = max(intr, cont_hold) + coupon_cf.get(i, 0)

            if collect_tree:
                S = _S(i, j)
                # blended disc factor for this node leaving to children (period i)
                df_u = _dfac(i + 1, j,     i)
                df_d = _dfac(i + 1, j + 1, i)
                blended_df = round((p_i * df_u + q_i * df_d) / 1.0, 6)
                _g_stock[i][j]    = round(S, 2)
                _g_rcps[i][j]     = round(Vn[j], 2)
                _g_conv[i][j]     = round(ei, 2)
                _g_dil[i][j]      = round(float(_diluted(i, j)) if use_dil else S, 2)
                _g_cp[i][j]       = round(cp[i][j], 6)
                _g_df[i][j]       = blended_df
                _g_hold_val[i][j] = round(hold, 2)

        V = Vn

    fair_value = float(V[0])

    # 희석주가 (루트 노드)
    diluted_s0 = float(_diluted(0, 0)) if use_dil else None

    out = {
        "fair_value":             round(fair_value),
        "steps":                  steps,
        "model":                  "Goldman Sachs (블렌딩 할인계수)",
        "dilution_applied":       use_dil,
        "diluted_stock_price_0":  round(diluted_s0, 6) if diluted_s0 is not None else None,
        "conv_prob_0":            round(cp[0][0], 6),
        # legacy keys kept for existing callers
        "diluted_stock_price":    round(diluted_s0, 2) if diluted_s0 is not None else None,
        "iterations":             1,
    }
    if collect_tree:
        out["tree"] = {
            "stock":          _g_stock,
            "decision":       _g_dec,
            "rcps_value":     _g_rcps,
            "conv_intrinsic": _g_conv,
            "diluted":        _g_dil,
            "conv_prob":      _g_cp,
            "disc_factor":    _g_df,
            "hold_value":     _g_hold_val,
            "u":    round(float(u), 6),
            "d":    round(float(d_fac), 6),
            "steps": steps,
            "p":    ([round(float(_p(i+1)), 6) for i in range(steps)] if rf_curve
                     else round(float(p_flat), 6)),
        }
    return out


def _eff_K(S, K, K_floor, params, step, steps):
    if not params.refixing or K <= 0:
        return K
    if not params.is_refixing_date(step, steps):
        return K
    if params.refixing_trigger and S < K * params.refixing_trigger:
        return max(K_floor, S)
    return K


def _date_to_step(target, params, steps):
    """이벤트 일자 → 트리 step 인덱스 변환.
    target=None → steps (활성화 없음)
    target > maturity → steps+1 (절대 활성화 안 됨)
    target ≤ valuation → 0 (즉시 활성)
    """
    if target is None:
        return steps
    if target > params.maturity_date:
        return steps + 1
    days = (target - params.valuation_date).days
    if days <= 0:
        return 0
    return min(int(round(days / (params.T * 365) * steps)), steps)
