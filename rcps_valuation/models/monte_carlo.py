import numpy as np
from inputs.deal_params import RCPSParams


def monte_carlo_rcps(params: RCPSParams, n_paths: int = 10000, n_steps: int = None,
                     bond_discrete: bool = False, seed: int = None,
                     rf_curve=None, kd_curve=None) -> dict:
    """RCPS 몬테카를로 (Tsiveriotis-Fernandes 2성분 LSM, Antithetic Variates)

    경로별 가치를 지분(E)·채권(B) 두 성분으로 분리해 TF와 동일하게 할인:
      - 지분(전환) 요소 E : 무위험 rf 연속복리  exp(-rf·dt)
      - 채권(상환·쿠폰) 요소 B : 신용조정 Kd
        · bond_discrete=False (기본, 연속복리): exp(-Kd·dt)
        · bond_discrete=True  (이산복리)     : 1/(1+Kd)^dt
    조기 전환·풋 행사 결정은 LSM(최소제곱회귀)로 추정한 계속가치와 비교.
    TF/GS와 정합 비교 시 bond_discrete를 동일하게 맞춰야 채권 PV 일치.

    seed: 난수 시드 (감사 재현성). None이면 평가기준일 ordinal을 사용해
          동일 평가일·동일 입력에서 항상 같은 결과를 산출 (K-IFRS 13.91).
          명시적으로 시드를 다르게 주면 다른 표본 경로 산출.
    rf_curve / kd_curve: 스텝별 forward rate (None이면 flat rate). TF·GS와 일관 비교 시 필수.
    """
    T = params.T
    if T <= 0:
        raise ValueError("평가기준일이 만기일 이후입니다.")
    if params.volatility <= 0:
        raise ValueError("변동성(σ)은 양수여야 합니다. 입력값: %.4f" % params.volatility)

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

    # ── 감사 재현성: 시드 고정 (K-IFRS 13.91 — 동일 입력 동일 결과)
    if seed is None:
        seed = int(params.valuation_date.toordinal())
    rng = np.random.default_rng(seed)

    # ── TF 정합 할인계수: 스텝별 곡선 우선, 없으면 flat
    use_curves = bool(rf_curve and kd_curve and len(rf_curve) >= n_steps and len(kd_curve) >= n_steps)
    if use_curves:
        rf_arr = np.array(rf_curve[:n_steps], dtype=float)
        kd_arr = np.array(kd_curve[:n_steps], dtype=float)
        disc_rf_arr = np.exp(-rf_arr * dt)
        if bond_discrete:
            disc_kd_arr = 1.0 / ((1.0 + kd_arr) ** dt)
        else:
            disc_kd_arr = np.exp(-kd_arr * dt)
        # 드리프트도 스텝별 — GBM에서 ld[t] = (rf[t]-q-0.5σ²)·dt
        ld_arr = (rf_arr - q - 0.5 * sigma**2) * dt
    else:
        disc_rf_arr = np.full(n_steps, float(np.exp(-r * dt)))
        if bond_discrete:
            disc_kd_arr = np.full(n_steps, float(1.0 / ((1.0 + r_d) ** dt)))
        else:
            disc_kd_arr = np.full(n_steps, float(np.exp(-r_d * dt)))
        ld_arr = np.full(n_steps, float((r - q - 0.5 * sigma**2) * dt))

    # 홀수 n_paths 가드: antithetic은 짝수 필요 → 짝수로 내림 (n_paths 정정)
    half = n_paths // 2
    n_paths = 2 * half
    Z = rng.standard_normal((half, n_steps))
    Z = np.vstack([Z, -Z])
    S = np.empty((n_paths, n_steps + 1))
    S[:, 0] = S0
    vd = sigma * np.sqrt(dt)
    for t in range(n_steps):
        S[:, t+1] = S[:, t] * np.exp(ld_arr[t] + vd * Z[:, t])

    # ── 리픽싱 기준가: spot(현재주가) 또는 VWAP(직전 N스텝 평균) ──
    vw = int(getattr(params, "refixing_vwap_window", 0) or 0)
    if vw > 0:
        cumS = np.cumsum(S, axis=1)
        Pref = np.empty_like(S)
        for t in range(n_steps + 1):
            lo = max(0, t - vw + 1)
            prev = cumS[:, lo - 1] if lo > 0 else 0.0
            Pref[:, t] = (cumS[:, t] - prev) / (t - lo + 1)
    else:
        Pref = S

    # ── 리픽싱: 시점별 유효전환가 K_path[path, t] ──
    #   ratchet(경로의존 lock-in): K_path[:,t] = s≤t 구간 리셋의 running-min (유지)
    #     ※ 시점 t 까지의 누적 최저만 사용(look-ahead 편향 없음).
    #   spot(메모리 없음): K_path[:,t] = 트리거 시 max(floor,기준가) 아니면 원 K (트리 _eff_K 정합)
    K_path = np.full((n_paths, n_steps + 1), float(K))
    if params.refixing and params.refixing_floor and params.refixing_trigger:
        Kfl = float(K * params.refixing_floor)
        Ktr = float(K * params.refixing_trigger)
        ratchet = bool(getattr(params, "refixing_ratchet", True))
        cur = np.full(n_paths, float(K))
        for t in range(1, n_steps + 1):
            if not params.is_refixing_date(t, n_steps):
                K_path[:, t] = cur if ratchet else float(K)
                continue
            p_t = Pref[:, t]
            trig = p_t < Ktr
            prop = np.maximum(Kfl, p_t)
            if ratchet:
                cur = np.where(trig & (prop < cur), prop, cur)
                K_path[:, t] = cur
            else:
                K_path[:, t] = np.where(trig, prop, float(K))

    conv_step = params.date_to_step(params.conversion_start, n_steps)
    put_step  = params.date_to_step(params.put_start, n_steps)

    # ── 경로의존 배리어 사전계산 (Parisian: window 중 count회 충족) ──
    def _parisian(cond, window, count):
        window = max(int(window or 1), 1); count = max(int(count or 1), 1)
        if window <= 1 and count <= 1:
            return cond
        cs = np.cumsum(cond.astype(np.int32), axis=1)
        out = np.zeros_like(cond)
        for t in range(cond.shape[1]):
            lo = max(0, t - window + 1)
            cnt = cs[:, t] - (cs[:, lo - 1] if lo > 0 else 0)
            out[:, t] = cnt >= count
        return out

    call_soft_active = None
    if params.call_soft_barrier:
        call_soft_active = _parisian(S >= (params.call_soft_barrier * K),
                                     params.call_soft_window, params.call_soft_count)
    mand_active = None
    if params.mandatory_conv_barrier:
        mand_active = _parisian(S >= (params.mandatory_conv_barrier * K),
                                params.mandatory_conv_window, params.mandatory_conv_count)
    put_ki = None
    if params.put_barrier and params.has_put:
        put_ki = np.cumsum((S <= (params.put_barrier * S0)).astype(np.int32), axis=1) > 0

    has_soft = call_soft_active is not None
    has_mand = mand_active is not None

    from models.binomial_v2 import _coupon_schedule
    coupon_cf = _coupon_schedule(params, n_steps, dt)

    # ── 만기 가치: 전환 vs 상환 → E/B 버킷 분리 ──
    # 패턴 A(누적 우선배당 표준 — GS/5803 일치): 비교는 원금끼리, 만기쿠폰은
    # 결정 무관 양쪽 가산. 전환자도 만기 시점 누적 우선배당 청구권 보유.
    put_mat = params.put_exercise_price(n_steps * dt) if params.has_put else face
    mat_coupon = coupon_cf.get(n_steps, 0)
    mat_principal = max(face, put_mat)
    conv_T = (face / K_path[:, -1]) * S[:, -1]
    # 만기 강제전환(KO): 배리어 충족 경로는 무조건 전환
    if has_mand:
        force_T = mand_active[:, -1]
        converted = (conv_T >= mat_principal) | force_T
    else:
        converted = conv_T >= mat_principal
    E = np.where(converted, conv_T, 0.0)
    B = np.where(converted, float(mat_coupon), float(mat_principal + mat_coupon))
    ever_conv = converted.copy()

    # ── 후방귀납 (TF 와 동일: E_hold=disc_rf·E, B_hold=coup+disc_kd·B) ──
    # 스텝별 할인계수 사용 (use_curves=True이면 forward curve, 아니면 flat)
    for t in range(n_steps - 1, -1, -1):
        coup = coupon_cf.get(t, 0)
        E = E * disc_rf_arr[t]
        B = coup + B * disc_kd_arr[t]
        V_hold = E + B

        conv_on = t >= conv_step
        put_time = (t >= put_step and params.has_put)
        if not (conv_on or put_time or has_soft or has_mand):
            continue

        S_t = S[:, t]
        conv_val = (face / K_path[:, t]) * S_t if conv_on else np.zeros(n_paths)
        # 풋 행사가능: 시점 + (배리어 풋이면 knock-in된 경로만)
        if put_time:
            put_ex = float(params.put_exercise_price(t * dt))
            put_active = put_ki[:, t] if put_ki is not None else np.ones(n_paths, dtype=bool)
        else:
            put_ex = 0.0
            put_active = np.zeros(n_paths, dtype=bool)

        # ── (a) 보유자 자발 행사 (LSM) ──
        if conv_on or put_time:
            imm = np.full(n_paths, -1.0)
            if conv_on:
                imm = np.maximum(imm, conv_val)
            if put_time:
                imm = np.where(put_active, np.maximum(imm, put_ex), imm)
            itm = imm > 0.0
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
            if conv_on and put_time:
                conv_better = conv_val >= put_ex
            elif conv_on:
                conv_better = np.ones(n_paths, dtype=bool)
            else:
                conv_better = np.zeros(n_paths, dtype=bool)
            # 패턴 A: 결정과 무관하게 그 시점 cash 쿠폰(coup, 이미 B에 가산됨)은 보존
            do_conv = do_ex & conv_better & conv_on
            do_put  = do_ex & (~conv_better) & put_active
            E = np.where(do_conv, conv_val, E); B = np.where(do_conv, float(coup), B)
            ever_conv = ever_conv | do_conv
            E = np.where(do_put, 0.0, E); B = np.where(do_put, put_ex + coup, B)

        # ── (b) 발행자 소프트콜: 배리어 충족 & 콜이 가치를 낮출 때만 행사 ──
        # 패턴 A: 콜→전환/콜→상환 모두 그 시점 cash 쿠폰 보존
        if has_soft:
            act = call_soft_active[:, t]
            call_ex = float(params.call_exercise_price(t * dt))
            called_val = np.maximum(call_ex, conv_val) if conv_on else np.full(n_paths, call_ex)
            do_call = act & (called_val < (E + B))
            conv_wins = conv_on & (conv_val >= call_ex)
            set_conv = do_call & conv_wins
            set_red  = do_call & (~conv_wins)
            E = np.where(set_conv, conv_val, E); B = np.where(set_conv, float(coup), B)
            ever_conv = ever_conv | set_conv
            E = np.where(set_red, 0.0, E); B = np.where(set_red, call_ex + coup, B)

        # ── (c) 강제전환 (Knock-out): 배리어 충족 경로 무조건 전환 ──
        # 패턴 A: 강제전환도 그 시점 cash 쿠폰 보존
        if has_mand and conv_on:
            act = mand_active[:, t]
            E = np.where(act, conv_val, E); B = np.where(act, float(coup), B)
            ever_conv = ever_conv | act

    V = E + B
    fv = float(np.mean(V))
    se = float(np.std(V, ddof=1) / np.sqrt(n_paths))
    # 구성요소 분해 (TF 2-성분): E=지분(전환) 성분, B=채권+풋+상환 성분
    equity_comp = float(np.mean(E))
    bond_comp = float(np.mean(B))
    return {
        "fair_value": round(fv),
        "std_error": round(se),
        "ci_lower": round(fv - 1.96 * se),
        "ci_upper": round(fv + 1.96 * se),
        "n_paths": n_paths,
        "n_steps": n_steps,
        "seed": seed,                                 # 감사 재현성 — 워크페이퍼 기록용
        "term_structure_applied": bool(use_curves),  # 스텝별 forward 사용 여부
        "early_exercise_pct": round(float(ever_conv.mean() * 100), 1),
        "conversion_value": round(equity_comp),      # 전환(지분) 성분
        "bond_put_value": round(bond_comp),           # 채권+풋+상환 성분
        "model": "Monte Carlo (TF 2-component LSM)",
    }


# _date_to_step: deal_params.RCPSParams.date_to_step()로 통일됨 (이전 truncate → round)
