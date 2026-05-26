from copy import deepcopy
from inputs.deal_params import RCPSParams
from models.tsiveriotis_fernandes import tf_rcps


def subsequent_measurement(params: RCPSParams, reporting_dates: list, steps: int = None,
                            rf_curve=None, kd_curve=None, bond_discrete: bool = False) -> list:
    """K-IFRS 1109 후속측정: 보고일별 공정가치 재산정.
    측정 연속성을 위해 최초인식과 동일한 할인 컨벤션(curve, discrete) 전달."""
    results = []
    prev_fv = None

    for entry in reporting_dates:
        p = deepcopy(params)
        p.valuation_date = entry["date"]
        p.stock_price = entry["stock_price"]
        p.volatility = entry["volatility"]
        p.risk_free_rate = entry.get("risk_free_rate", params.risk_free_rate)
        p.credit_spread = entry.get("credit_spread", params.credit_spread)

        if p.T <= 0:
            continue

        # 보고일별 곡선이 따로 제공되면 사용, 아니면 공통 곡선
        rf_c = entry.get("rf_curve", rf_curve)
        kd_c = entry.get("kd_curve", kd_curve)
        tf_kw = {"bond_discrete": bond_discrete}
        if rf_c and kd_c:
            tf_kw["rf_curve"] = rf_c
            tf_kw["kd_curve"] = kd_c
        r = tf_rcps(p, steps=steps, **tf_kw)
        fv = r["fair_value"]

        change = fv - prev_fv if prev_fv is not None else None
        change_pct = round(change / prev_fv * 100, 2) if prev_fv else None

        results.append({
            "date": str(p.valuation_date),
            "fair_value": round(fv),
            "bond_value": round(r["bond_value"]),
            "put_option_value": r["put_option_value"],
            "conversion_value": round(r["conversion_value"]),
            "change": round(change) if change is not None else None,
            "change_pct": change_pct,
            "stock_price": p.stock_price,
            "volatility": round(p.volatility * 100, 1),
        })
        prev_fv = fv

    return results
