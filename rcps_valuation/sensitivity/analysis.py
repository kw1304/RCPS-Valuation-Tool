"""민감도 분석 — 가정을 조금씩 흔들었을 때 공정가치 변동.

K-IFRS 13.93(h)(ii) Level 3 unobservable input 민감도 공시.
본 평가와 같은 곡선·같은 단계를 써야 base fv가 일치합니다.
"""
from copy import deepcopy
from typing import Optional, List
import numpy as np
from inputs.deal_params import RCPSParams
from models.tsiveriotis_fernandes import tf_rcps


def _shift_curve(curve: Optional[List[float]], delta: float) -> Optional[List[float]]:
    """곡선 평행이동 — 신용스프레드 민감도용 (kd_curve += delta)."""
    if not curve:
        return None
    return [max(float(r) + delta, 0.0) for r in curve]


def sensitivity_analysis(params: RCPSParams, steps: int = None,
                         rf_curve: Optional[List[float]] = None,
                         kd_curve: Optional[List[float]] = None) -> dict:
    """가정 ±변동에 따른 공정가치 민감도.

    Args:
        params: 평가 파라미터
        steps: 트리 단계 (본 평가와 동일해야 base fv 일치)
        rf_curve, kd_curve: 본 평가에 사용된 step-forward 곡선
            — 신용스프레드 민감도는 kd_curve 평행이동으로 재구성
    """
    tf_kw = {}
    if rf_curve and kd_curve:
        tf_kw["rf_curve"] = rf_curve
        tf_kw["kd_curve"] = kd_curve

    base = tf_rcps(params, steps=steps, **tf_kw)
    base_fv = base["fair_value"]

    def calc(p, kw=None):
        try:
            kw = kw or tf_kw
            return round(tf_rcps(p, steps=steps, **kw)["fair_value"])
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
    # 곡선 사용 시 kd_curve 평행이동, 곡선 미사용 시 credit_spread 가산
    spread_results = []
    for delta in np.arange(-0.05, 0.051, 0.01):
        p = deepcopy(params)
        p.credit_spread = max(round(params.credit_spread + delta, 4), 0.001)
        if kd_curve:
            # 곡선 사용: kd_curve 평행이동
            kw = {"rf_curve": rf_curve, "kd_curve": _shift_curve(kd_curve, float(delta))}
            fv = calc(p, kw=kw)
        else:
            # 곡선 미사용: credit_spread 가산만으로 충분
            fv = calc(p)
        if fv:
            spread_results.append({
                "label": f"{p.credit_spread*100:.1f}%",
                "value": round(p.credit_spread, 4),
                "fair_value": fv,
                "change_pct": round((fv - base_fv) / base_fv * 100, 2),
            })

    # 보장수익률(put_irr) 민감도: ±2%p (1%p 간격) — RCPS 핵심 가정
    # 누적 IRR 보장이 발행자 무조건 의무라 가치 결정자
    irr_results = []
    if params.put_irr and params.put_irr > 0:
        for delta in np.arange(-0.02, 0.021, 0.01):
            p = deepcopy(params)
            p.put_irr = max(round(params.put_irr + delta, 4), 0.001)
            fv = calc(p)
            if fv:
                irr_results.append({
                    "label": f"{p.put_irr*100:.1f}%",
                    "value": round(p.put_irr, 4),
                    "fair_value": fv,
                    "change_pct": round((fv - base_fv) / base_fv * 100, 2),
                })

    # 전환가액(conversion_price) 민감도: ±30% (10% 간격) — 전환권 ITM/OTM 가치
    conv_results = []
    if params.conversion_price and params.conversion_price > 0:
        for delta in np.arange(-0.30, 0.31, 0.10):
            p = deepcopy(params)
            p.conversion_price = max(round(params.conversion_price * (1 + delta), 0), 1)
            fv = calc(p)
            if fv:
                conv_results.append({
                    "label": f"{int(p.conversion_price):,}",
                    "value": p.conversion_price,
                    "fair_value": fv,
                    "change_pct": round((fv - base_fv) / base_fv * 100, 2),
                })

    return {
        "base_fair_value": round(base_fv),
        "volatility": vol_results,
        "stock_price": stock_results,
        "credit_spread": spread_results,
        "put_irr": irr_results,
        "conversion_price": conv_results,
        "curve_applied": bool(rf_curve and kd_curve),
    }
