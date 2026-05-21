import numpy as np
from inputs.deal_params import RCPSParams


def binomial_rcps(params: RCPSParams, steps: int = 500) -> dict:
    """
    RCPS 이항모형 공정가치 평가 (CRR)

    - 전환권: 보유자 최적 행사 (전환 가능 기간)
    - 상환권: 상환가능기간 중 매 노드에서 보유자 최적 상환 반영
             상환가액 = face × (1+guarantee_rate)^경과연수 (보장수익률 있을 시)
    - 리픽싱: 주기별(연속/분기/반기/연) 체크, 주가 트리거 하회 시 전환가 하향
    - 우선배당: dt 비례 현금흐름
    """
    T = params.time_to_maturity
    if T <= 0:
        raise ValueError("평가기준일이 만기일 이후입니다.")

    dt = T / steps
    S0 = params.stock_price
    sigma = params.volatility
    r = params.risk_free_rate
    q = params.dividend_yield
    r_debt = params.discount_rate

    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)

    if not (0 < p < 1):
        raise ValueError(f"위험중립확률 범위 오류: p={p:.4f}. 변동성 또는 금리를 확인하세요.")

    face = params.face_value
    K = params.conversion_price
    K_floor = K * params.refixing_floor if params.refixing and params.refixing_floor else K
    redemption_maturity = face * params.redemption_premium
    coupon_per_step = face * params.dividend_rate * dt

    discount_step = np.exp(-r_debt * dt)
    conversion_start_step = _date_to_step(params.conversion_start, params.valuation_date, T, steps)
    redemption_start_step = (
        _date_to_step(params.redemption_start, params.valuation_date, T, steps)
        if params.redemption_start else steps  # None이면 만기에만
    )

    # ── 말단 노드 페이오프
    value = np.zeros(steps + 1)
    for j in range(steps + 1):
        S_T = S0 * (u ** (steps - j)) * (d ** j)
        K_eff = _eff_K(S_T, K, K_floor, params, steps, steps)
        conv_val = (face / K_eff) * S_T
        value[j] = max(conv_val, redemption_maturity)

    # ── 역방향 귀납
    for i in range(steps - 1, -1, -1):
        t_years = i * dt  # 평가기준일로부터 경과 연수
        value_next = value[:i + 2]

        hold = discount_step * (p * value_next[:-1] + (1 - p) * value_next[1:]) + coupon_per_step

        for j in range(i + 1):
            S = S0 * (u ** (i - j)) * (d ** j)
            K_eff = _eff_K(S, K, K_floor, params, i, steps)
            conv_val = (face / K_eff) * S

            node_val = hold[j]

            # 조기상환 가능 기간: 보유자는 상환도 선택 가능
            if i >= redemption_start_step:
                redeem_now = params.redemption_value_at(t_years)
                node_val = max(node_val, redeem_now)

            # 전환 가능 기간: 전환도 선택 가능
            if i >= conversion_start_step:
                node_val = max(node_val, conv_val)

            hold[j] = node_val

        value = np.append(hold, 0)[:i + 1]

    fair_value = value[0]

    return {
        "fair_value": fair_value,
        "steps": steps,
        "time_to_maturity": T,
        "u": u,
        "d": d,
        "risk_neutral_prob": p,
        "discount_rate": r_debt,
    }


def _eff_K(S: float, K: float, K_floor: float, params: RCPSParams, step: int, steps: int) -> float:
    """
    유효 전환가액 계산 (리픽싱 반영)

    리픽싱 발동 조건: 현재 주가(S) < 현행 전환가(K) × 트리거 비율
    발동 시 새 전환가: max(최초전환가 × 하한비율, 현재주가)
      → 시가로 내리되, 하한(floor) 아래로는 내리지 않음
    """
    if not params.refixing:
        return K
    if not params.is_refixing_date(step, steps):
        return K
    trigger_price = K * params.refixing_trigger  # 트리거 발동 기준 주가
    if S < trigger_price:
        return max(K_floor, S)  # 새 전환가 = max(하한, 시가)
    return K


def _date_to_step(target_date, valuation_date, T: float, steps: int) -> int:
    from datetime import date
    days_to_target = (target_date - valuation_date).days
    if days_to_target <= 0:
        return 0
    ratio = days_to_target / (T * 365)
    return min(int(ratio * steps), steps)
