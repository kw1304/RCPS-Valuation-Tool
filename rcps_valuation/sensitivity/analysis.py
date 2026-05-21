from copy import deepcopy
import numpy as np
from inputs.deal_params import RCPSParams
from models.tsiveriotis_fernandes import tf_rcps


def sensitivity_analysis(params: RCPSParams, steps: int = None) -> dict:
    base = tf_rcps(params, steps=steps)
    base_fv = base["fair_value"]

    def calc(p):
        try:
            return round(tf_rcps(p, steps=steps)["fair_value"])
        except Exception:
            return None

    # 변동성 민감도: ±30%p (10%p 간격)
    vol_results = []
    for delta in np.arange(-0.30, 0.31, 0.10):
        p = deepcopy(params)
        p.volatility = max(round(params.volatility + delta, 4), 0.01)
        fv = calc(p)
        if fv:
            vol_results.append({
                "label": f"{p.volatility*100:.0f}%",
                "value": round(p.volatility, 4),
                "fair_value": fv,
                "change_pct": round((fv - base_fv) / base_fv * 100, 2),
            })

    # 주가 민감도: ±30% (10% 간격)
    stock_results = []
    for delta in np.arange(-0.30, 0.31, 0.10):
        p = deepcopy(params)
        p.stock_price = max(round(params.stock_price * (1 + delta), 0), 1)
        fv = calc(p)
        if fv:
            stock_results.append({
                "label": f"{int(p.stock_price):,}",
                "value": p.stock_price,
                "fair_value": fv,
                "change_pct": round((fv - base_fv) / base_fv * 100, 2),
            })

    # 신용스프레드 민감도: ±5%p (1%p 간격)
    spread_results = []
    for delta in np.arange(-0.05, 0.051, 0.01):
        p = deepcopy(params)
        p.credit_spread = max(round(params.credit_spread + delta, 4), 0.001)
        fv = calc(p)
        if fv:
            spread_results.append({
                "label": f"{p.credit_spread*100:.1f}%",
                "value": round(p.credit_spread, 4),
                "fair_value": fv,
                "change_pct": round((fv - base_fv) / base_fv * 100, 2),
            })

    return {
        "base_fair_value": round(base_fv),
        "volatility": vol_results,
        "stock_price": stock_results,
        "credit_spread": spread_results,
    }
