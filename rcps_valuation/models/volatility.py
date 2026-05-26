"""주가 변동성(σ) 평가 — 역사적 변동성, 유사상장기업 바스켓.

K-IFRS 1109 RCPS 공정가치 평가의 변동성 입력 산출용. 비상장 발행사는
자사 주가가 없으므로 유사상장기업의 역사적 변동성을 집계해 σ를 추정한다.

이 모듈은 numpy만 사용한다(외부 데이터 의존 없음). 가격 시계열을 받아
계산만 수행하므로 단위테스트가 용이하다. KRX 자동조회(FinanceDataReader)는
API 계층(api/app.py)에서 처리하고, 정제된 종가 리스트를 이 모듈로 넘긴다.
"""
import math
import numpy as np


def clean_closes(dates, closes, volumes=None):
    """종가 시계열 정제: 결측·비양수가격·거래정지(거래량 0)일 제거.

    Returns (clean_dates, clean_closes, removed) — 시간순 정렬 가정.
    """
    n = len(closes)
    out_d, out_c = [], []
    removed = 0
    for i in range(n):
        c = closes[i]
        v = volumes[i] if volumes is not None else None
        if c is None or (isinstance(c, float) and math.isnan(c)) or c <= 0:
            removed += 1
            continue
        if v is not None and (v == 0 or (isinstance(v, float) and math.isnan(v))):
            removed += 1   # 거래정지일: 가격이 직전값으로 고정되어 변동성 왜곡
            continue
        out_d.append(dates[i] if dates is not None else i)
        out_c.append(float(c))
    return out_d, out_c, removed


def historical_vol(closes, trading_days=252, log=True):
    """역사적 변동성. closes는 시간순 정제된 종가 리스트.

    σ_annual = stdev(daily returns, ddof=1) × √(trading_days)
    log=True 면 로그수익률 ln(S_t/S_{t-1}), 아니면 산술수익률.

    표준오차(SE): σ_SE ≈ σ / √(2·n_obs) — 정규수익률 가정 하 σ 추정의 SE.
    Hull "Options, Futures, and Other Derivatives" 11e Ch.15.
    95% CI = σ ± 1.96·σ_SE.

    log/산술 비교: log_return σ와 simple_return σ를 동시 산출하여 비교 (정규 분포일 때 ~동일,
    σ 큰 경우 차이 ~0.1~0.5%p).
    """
    c = np.asarray(closes, dtype=float)
    if c.size < 2:
        raise ValueError("종가가 2개 이상 필요합니다 (수익률 계산 불가).")
    rets_log = np.diff(np.log(c))
    rets_simple = c[1:] / c[:-1] - 1.0
    rets = rets_log if log else rets_simple
    daily_sigma = float(np.std(rets, ddof=1))
    sigma = daily_sigma * math.sqrt(trading_days)
    n_obs = int(rets.size)
    # 표준오차 — σ 추정 신뢰도 (95% CI 산출용)
    sigma_se = sigma / math.sqrt(2 * n_obs) if n_obs > 0 else 0.0
    # 비교용 산출 (log/산술 모두)
    log_sigma = float(np.std(rets_log, ddof=1)) * math.sqrt(trading_days)
    simple_sigma = float(np.std(rets_simple, ddof=1)) * math.sqrt(trading_days)
    return {
        "sigma": sigma,                     # 연율 변동성(소수, 0.241 = 24.1%)
        "sigma_se": sigma_se,               # 표준오차 (정규수익률 가정)
        "ci95_low": max(0.0, sigma - 1.96 * sigma_se),
        "ci95_high": sigma + 1.96 * sigma_se,
        "daily_sigma": daily_sigma,
        "n_obs": n_obs,                     # 수익률 관측치 수
        "n_prices": int(c.size),
        "trading_days": trading_days,
        "log_returns": bool(log),
        # 비교 정보 (log vs 산술)
        "log_sigma": log_sigma,
        "simple_sigma": simple_sigma,
        "convention_diff_pp": abs(log_sigma - simple_sigma) * 100,
    }


def aggregate(per_ticker, method="median", caps=None):
    """종목별 σ 리스트를 하나로 집계.

    per_ticker: [{"sigma": float, ...}, ...] (실패 종목은 sigma=None 가능 → 제외)
    method: "median"(권장) | "mean" | "cap_weighted"
    caps: cap_weighted 일 때 종목별 시가총액 리스트(per_ticker와 동순서).
    """
    sig = [t["sigma"] for t in per_ticker if t.get("sigma") is not None]
    if not sig:
        raise ValueError("집계할 유효한 종목 변동성이 없습니다.")
    sig = np.asarray(sig, dtype=float)

    if method == "mean":
        return float(np.mean(sig))
    if method == "cap_weighted":
        if not caps:
            raise ValueError("cap_weighted 집계에는 시가총액(caps)이 필요합니다.")
        w = np.asarray(
            [c for c, t in zip(caps, per_ticker) if t.get("sigma") is not None],
            dtype=float,
        )
        if w.size != sig.size or np.nansum(w) <= 0:
            raise ValueError("시가총액 가중치가 유효하지 않습니다.")
        w = np.nan_to_num(w, nan=0.0)
        return float(np.sum(sig * w) / np.sum(w))
    # default: median
    return float(np.median(sig))


def _td_from_dates(dates):
    """ISO 날짜 시계열에서 종목의 실측 연 거래일 수 산정.
    (관측 거래일 수) × 365.25 / (시작~종료 달력일수). 산정 불가면 None.
    """
    if not dates or len(dates) < 2:
        return None
    try:
        from datetime import date as _date
        d0 = _date.fromisoformat(str(dates[0]))
        d1 = _date.fromisoformat(str(dates[-1]))
    except Exception:
        return None
    cal_days = (d1 - d0).days
    if cal_days <= 0:
        return None
    return round(len(dates) * 365.25 / cal_days, 1)


def _detect_outliers(per_ticker, method, k, min_n=5):
    """유사기업 바스켓 σ에 이상치 플래그 부여(per_ticker 항목 in-place 수정).

    method: 'iqr'(Tukey k×IQR 펜스) | 'mad'(|σ−중앙값|>k·MAD) | 그 외 → 미적용.
    표본(유효종목 수)이 min_n 미만이면 자동 미적용(통계적으로 무의미).
    """
    if method not in ("iqr", "mad"):
        return {"applied": False, "method": "none"}
    valid = [p for p in per_ticker if p.get("sigma") is not None]
    if len(valid) < min_n:
        return {"applied": False, "method": method, "k": k,
                "reason": f"표본 {len(valid)}<{min_n}: 필터 미적용"}
    sigs = np.array([p["sigma"] for p in valid], dtype=float)
    info = {"applied": True, "method": method, "k": k, "n_input": len(valid)}
    if method == "iqr":
        q1, q3 = np.percentile(sigs, [25, 75])
        iqr = float(q3 - q1)
        lo, hi = float(q1 - k * iqr), float(q3 + k * iqr)
        info.update({"q1": float(q1), "q3": float(q3), "iqr": iqr, "lo": lo, "hi": hi})
        for p in valid:
            if p["sigma"] < lo or p["sigma"] > hi:
                p["outlier"] = True
                p["outlier_reason"] = f"IQR {k:g}× 밖 (허용 {lo*100:.2f}%~{hi*100:.2f}%)"
    else:  # mad
        med = float(np.median(sigs))
        mad = float(np.median(np.abs(sigs - med)))
        info.update({"median": med, "mad": mad})
        if mad <= 0:
            info["applied"] = False
            info["reason"] = "MAD=0(전 종목 σ 동일): 필터 미적용"
            return info
        for p in valid:
            if abs(p["sigma"] - med) > k * mad:
                p["outlier"] = True
                p["outlier_reason"] = f"MAD {k:g}× 밖 (|σ−중앙값|>{k*mad*100:.2f}%)"
    info["n_excluded"] = sum(1 for p in valid if p.get("outlier"))
    return info


def basket_volatility(series, trading_days=252, log=True, method="median",
                      outlier_method="none", outlier_k=None):
    """유사기업 바스켓 σ 산출 (편의 래퍼).

    series: {ticker: {"name", "dates", "closes", "volumes"(opt), "cap"(opt)}}
    trading_days: 정수(고정) 또는 "auto"(종목별 시계열에서 실측 산정).
    outlier_method: 'none' | 'iqr' | 'mad' (유사기업 σ 바스켓 이상치 제거).
    outlier_k: 임계 배수(IQR 기본 1.5, MAD 기본 3.0). None이면 method에 맞춰 기본값.
    Returns {"sigma", "method", "per_ticker":[...], "failed":[...], "outlier_info":{...}}.
    """
    per, caps, failed = [], [], []
    auto_td = isinstance(trading_days, str) and trading_days.lower() == "auto"
    for tk, s in series.items():
        try:
            cleaned_dates, cc, removed = clean_closes(s.get("dates"), s["closes"], s.get("volumes"))
            if auto_td:
                td = _td_from_dates(cleaned_dates) or 252   # 산정 불가 시 252 fallback
            else:
                td = int(trading_days)
            hv = historical_vol(cc, trading_days=td, log=log)
            per.append({
                "ticker": tk,
                "name": s.get("name", tk),
                "sigma": hv["sigma"],
                "sigma_se": hv["sigma_se"],         # 표준오차 (정규수익률 가정)
                "ci95_low": hv["ci95_low"],
                "ci95_high": hv["ci95_high"],
                "n_obs": hv["n_obs"],
                "removed": removed,
                "cap": s.get("cap"),
                "trading_days_used": td,
                "log_sigma": hv["log_sigma"],
                "simple_sigma": hv["simple_sigma"],
            })
            caps.append(s.get("cap"))
        except Exception as e:  # noqa: BLE001 — 종목별 실패는 스킵하고 사유 보존
            per.append({"ticker": tk, "name": s.get("name", tk), "sigma": None,
                        "error": str(e)})
            caps.append(None)
            failed.append({"ticker": tk, "error": str(e)})

    # 이상치 필터: 유사기업 σ 바스켓에 적용 (IQR/MAD, 평가자 조정가능 임계)
    if outlier_k is None:
        outlier_k = 1.5 if outlier_method == "iqr" else 3.0
    outlier_info = _detect_outliers(per, outlier_method, float(outlier_k))

    # 집계는 이상치 제외 후 수행. cap_weighted는 동일 인덱스 보존 필요
    active_idx = [i for i, p in enumerate(per) if p.get("sigma") is not None and not p.get("outlier")]
    active_per = [per[i] for i in active_idx]
    active_caps = [caps[i] for i in active_idx] if method == "cap_weighted" else None
    try:
        agg = aggregate(active_per, method=method, caps=active_caps)
        agg_err = None
    except Exception as e:  # noqa: BLE001
        agg, agg_err = None, str(e)
    return {"sigma": agg, "method": method, "per_ticker": per,
            "failed": failed, "error": agg_err, "outlier_info": outlier_info}
