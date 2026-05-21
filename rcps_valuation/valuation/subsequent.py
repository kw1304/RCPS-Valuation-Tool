from copy import deepcopy
from inputs.deal_params import RCPSParams
from models.tsiveriotis_fernandes import tf_rcps


def subsequent_measurement(params: RCPSParams, reporting_dates: list, steps: int = None) -> list:
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

        r = tf_rcps(p, steps=steps)
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
