from copy import deepcopy
import numpy as np
from inputs.deal_params import RCPSParams
from models.tsiveriotis_fernandes import tf_rcps


def _spot_to_step_forwards(spot_curve, T, steps):
    """제로스팟(연속, t→z(t)) → 스텝별 forward rate.
    잔존만기 T를 steps 칸으로 쪼개 각 구간 forward = (z₂·t₂ − z₁·t₁) / (t₂ − t₁) 산출.
    spot_curve = [(t, z), ...] 또는 None."""
    if not spot_curve:
        return None
    dt = T / steps
    pts = sorted([(float(t), float(z)) for t, z in spot_curve])

    def z_of(t):
        # 평탄 외삽 + 선형 보간
        if t <= pts[0][0]:
            return pts[0][1]
        if t >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            t0, z0 = pts[i]
            t1, z1 = pts[i + 1]
            if t0 <= t <= t1:
                w = (t - t0) / (t1 - t0)
                return z0 + w * (z1 - z0)
        return pts[-1][1]

    fwds = []
    for i in range(steps):
        t1, t2 = i * dt, (i + 1) * dt
        if t1 == 0:
            fwds.append(z_of(t2))  # 0→t2 구간 forward = z(t2)
        else:
            f = (z_of(t2) * t2 - z_of(t1) * t1) / (t2 - t1)
            fwds.append(f)
    return fwds


def subsequent_measurement(params: RCPSParams, reporting_dates: list, steps: int = None,
                            rf_curve=None, kd_curve=None, bond_discrete: bool = False,
                            rf_spot=None, rd_spot=None) -> list:
    """K-IFRS 1109 후속측정: 보고일별 공정가치 재산정.
    측정 연속성(B5.1.2A): 최초인식과 동일한 컨벤션(연속복리, 위험중립, 곡선소스).

    **곡선 호라이즌 정합** (2026-05-26 수정):
    각 보고일에서 잔존만기 T가 단축되면 트리 dt도 변하므로, 동일한 forward 시퀀스를
    재사용하면 forward의 기간 매칭이 어긋남.
    → spot 원자료(rf_spot, rd_spot)가 있으면 보고일별 잔존 T에 맞춰 forward 재구성.
    → spot 없이 forward만 받은 경우 fallback으로 공통 곡선 사용(이전 동작).
    """
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

        # 보고일별 잔존 T에 맞춰 곡선 재구성 (K-IFRS 1109.B5.1.2A 측정 연속성)
        # 우선순위: entry별 명시 curve > entry별 spot으로 재구성 > 공통 spot으로 재구성 > 공통 curve fallback
        rf_c = entry.get("rf_curve")
        kd_c = entry.get("kd_curve")
        if not rf_c:
            rf_s = entry.get("rf_spot", rf_spot)
            if rf_s:
                rf_c = _spot_to_step_forwards(rf_s, p.T, steps)
        if not kd_c:
            kd_s = entry.get("rd_spot", rd_spot)
            if kd_s:
                kd_c = _spot_to_step_forwards(kd_s, p.T, steps)
        # fallback: 공통 curve (호라이즌 불일치 가능 — spot 없을 때만)
        if not rf_c:
            rf_c = rf_curve
        if not kd_c:
            kd_c = kd_curve

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
            "put_option_value": round(r["put_option_value"]),
            "conversion_value": round(r["conversion_value"]),
            "change": round(change) if change is not None else None,
            "change_pct": change_pct,
            "stock_price": p.stock_price,
            "volatility": round(p.volatility * 100, 1),
            "curve_horizon_aligned": bool((entry.get("rf_spot") or rf_spot) and (entry.get("rd_spot") or rd_spot)),
        })
        prev_fv = fv

    return results
