from inputs.deal_params import RCPSParams
from models.binomial import binomial_rcps


def initial_recognition(params: RCPSParams, steps: int = 500) -> dict:
    """
    최초인식 공정가치 산출 (IFRS 9 / K-IFRS 1109)

    발행시점 기준으로 이항모형 적용.
    전환권가치(equity component)와 부채요소(debt component) 분리는
    K-IFRS 1032 적용 여부에 따라 별도 처리 필요.
    """
    result = binomial_rcps(params, steps=steps)
    fv = result["fair_value"]

    # 전환권 없는 순수 채권 가치 (현금흐름 할인)
    straight_bond_value = _straight_bond_pv(params)

    conversion_component = max(fv - straight_bond_value, 0.0)

    return {
        "valuation_date": params.valuation_date,
        "fair_value": fv,
        "straight_bond_value": straight_bond_value,
        "conversion_component": conversion_component,
        "model": "Binomial (CRR)",
        "steps": steps,
        "key_inputs": {
            "stock_price": params.stock_price,
            "volatility": params.volatility,
            "risk_free_rate": params.risk_free_rate,
            "credit_spread": params.credit_spread,
            "conversion_price": params.conversion_price,
            "time_to_maturity": round(result["time_to_maturity"], 4),
        },
        "binomial_detail": result,
    }


def _straight_bond_pv(params: RCPSParams) -> float:
    """전환권 없는 채권 현재가치 (우선배당 + 만기상환)"""
    from datetime import date

    r = params.discount_rate
    T = params.time_to_maturity
    face = params.face_value
    redemption = face * params.redemption_premium

    # 연간 우선배당 현금흐름 (매년 말 지급 가정)
    pv = 0.0
    years = int(T)
    for t in range(1, years + 1):
        coupon = face * params.dividend_rate
        pv += coupon / ((1 + r) ** t)

    # 만기 상환금
    pv += redemption / ((1 + r) ** T)
    return pv
