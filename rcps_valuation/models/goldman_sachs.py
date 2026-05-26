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
    if params.volatility <= 0:
        raise ValueError("변동성(σ)은 양수여야 합니다. 입력: %.4f" % params.volatility)

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

    conv_step = params.date_to_step(params.conversion_start, steps)
    put_step  = params.date_to_step(params.put_start, steps)
    call_step = params.date_to_step(params.call_start, steps)
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

    # ── 희석주가: 전환 후 1주당 가격 (5803 표준 — 모든 RCPS 동시 전환 가정)
    # = (n_com·S + n_rcps·bond_pv) / (n_com + n_rcps·N_new_per)
    # 분자: 기존 지분 + 전체 RCPS 부채흡수, 분모: 기존 + 전체 신주
    # bond_pv는 per-RCPS, N_new_per = (face/K)·ratio (per RCPS).
    # 1주 한계 케이스 (n_rcps 없는 식)는 ITM 만기 노드 전환가치 과대평가.
    def _diluted(i, j):
        S = _S(i, j)
        r = _ratio(i, j)
        N_new = (face / K) * r
        return (S * n_com + n_rcps * bond_pv[i]) / (n_com + n_rcps * N_new)

    # ── 전환가치 (희석 경로) — TOTAL 단위
    # per-share post × N_new = 전환 시 RCPS 보유자가 받는 총 가치
    def _conv_val_dil(i, j):
        if i < conv_step:
            return 0.0
        r = _ratio(i, j)
        N_new = (face / K) * r
        return _diluted(i, j) * N_new

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

    # 만기 초기화 (Pass 3와 동일 결정 규칙: cv vs 원금상환액 (쿠폰 미포함) 비교)
    # 5803 컨벤션: 쿠폰은 결정 무관 지급 → 비교는 원금끼리, 양쪽 모두 쿠폰 가산
    _mat_principal_p1 = max(face, put_mat)
    _mat_coupon_p1 = coupon_cf.get(steps, 0)
    for j in range(steps + 1):
        ei = _conv_val(steps, j)
        if ei >= _mat_principal_p1:
            # 전환: 지분 = cv, 채권 = 만기쿠폰 (5803 컨벤션 — 전환도 쿠폰 받음)
            Er[j] = ei;  Br[j] = _mat_coupon_p1;  dec[steps][j] = 'c'
        else:
            Er[j] = 0.0; Br[j] = _mat_principal_p1 + _mat_coupon_p1;  dec[steps][j] = 'r'

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
    # 5803 / Goldman-Sachs(1994) 표준 컨벤션 (검증으로 확정):
    #   자식 가지의 위험구조(cp[child])는 그 가지가 도달하는 미래의 실제 전환확률 →
    #   자식별로 다른 블렌딩 할인율 적용:
    #     df_up = exp(-(cp[i+1][j  ]·rf + (1-cp[i+1][j  ])·Kd)·dt)
    #     df_dn = exp(-(cp[i+1][j+1]·rf + (1-cp[i+1][j+1])·Kd)·dt)
    #     hold  = p·V_up·df_up + q·V_dn·df_dn
    #   이전엔 부모 cp 단일 할인이었으나 골든값 -30 잔차 → 자식 가지별로 -6까지 좁힘.
    def _dfac_child(child_i, child_j, period_idx):
        c = cp[child_i][child_j]
        dr = c * _rf(period_idx) + (1.0 - c) * _kd(period_idx)
        return float(np.exp(-dr * dt))

    # ── 트리 수집용 그리드 초기화 (collect_tree=True 일 때만)
    if collect_tree:
        _g_stock    = [[0.0]*(i+1) for i in range(steps+1)]
        _g_rcps     = [[0.0]*(i+1) for i in range(steps+1)]
        _g_conv     = [[0.0]*(i+1) for i in range(steps+1)]
        _g_bond_intr= [[0.0]*(i+1) for i in range(steps+1)]  # 채권 내재가치
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
            _g_bond_intr[steps][j] = round(float(mat_redeem), 2)  # 만기 상환 내재가치
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
            # 자식 가지별 cp로 블렌딩 할인 (5803 표준 — 검증으로 골든값 잔차 회복)
            df_up = _dfac_child(i + 1, j, i)
            df_dn = _dfac_child(i + 1, j + 1, i)
            hold = p_i * V[j] * df_up + q_i * V[j + 1] * df_dn
            # 시각화용 평균 df (트리 그리드에 표시)
            df_parent = 0.5 * (df_up + df_dn)

            # Pass 1 결정을 그대로 따라 cp 일관성 보장 (M14 — GS Pass3 결정 일관성)
            # 이전엔 Pass3가 max(intr, cont_hold)로 결정을 재산정 → 콜 활성 노드에서
            # Pass1·Pass3 결정이 갈릴 위험. cp는 Pass1 기반인데 Pass3가 다른 결정이면
            # 블렌딩 할인계수와 가치 결정이 inconsistent.
            ei = _conv_val(i, j)
            rd_i = _redeem(i)
            d = dec[i][j]
            coup_i = coupon_cf.get(i, 0)
            if d == 'c':           # 전환
                Vn[j] = ei + coup_i
            elif d == 'r':         # 상환 (풋 또는 만기상환)
                Vn[j] = (rd_i if rd_i is not None else face) + coup_i
            elif d == 'l':         # 발행자 콜
                call_ex_p3 = params.call_exercise_price(i * dt)
                Vn[j] = call_ex_p3 + coup_i
            else:                  # 'h' = 보유 (Pass3 블렌딩 hold 값)
                Vn[j] = hold + coup_i
            # 시각화용 df_parent는 그대로 유지
            cont_hold = hold  # for tree visualization compatibility

            if collect_tree:
                S = _S(i, j)
                # 채권 내재가치 (즉시 풋 행사 시 받을 금액)
                # 풋 활성: 풋 행사가 / 풋 비활성: face (TF와 통일, 시각적 직관)
                bond_intr_node = float(rd_i) if rd_i is not None else float(face)
                _g_stock[i][j]    = round(S, 2)
                _g_rcps[i][j]     = round(Vn[j], 2)
                _g_conv[i][j]     = round(ei, 2)
                _g_bond_intr[i][j]= round(bond_intr_node, 2)
                _g_dil[i][j]      = round(float(_diluted(i, j)) if use_dil else S, 2)
                _g_cp[i][j]       = round(cp[i][j], 6)
                _g_df[i][j]       = round(df_parent, 6)  # 부모 cp 기준 단일 할인율
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
            "bond_intrinsic": _g_bond_intr,
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
    """리픽싱 시 유효 전환가. _ratio()와 동일 컨벤션: 주가 ≤ 트리거가에서 발동.
    한국 RCPS 약정 표준 '주가가 트리거 이하' (≤)."""
    if not params.refixing or K <= 0:
        return K
    if not params.is_refixing_date(step, steps):
        return K
    if params.refixing_trigger and S <= K * params.refixing_trigger:
        return max(K_floor, S)
    return K


# _date_to_step: deal_params.RCPSParams.date_to_step()로 통일됨
