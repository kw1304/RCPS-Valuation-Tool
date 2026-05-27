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


def _detect_outliers(per_ticker, method, k, min_n=5, k_mad=None):
    """유사기업 바스켓 σ에 이상치 플래그 부여 (per_ticker in-place 수정).

    method:
      'iqr'         — Tukey k×IQR 펜스 (분포 형상 기반)
      'mad'         — |σ−중앙값| > k·MAD (중앙값 거리 기반)
      'iqr_or_mad'  — 합집합 (둘 중 하나라도 outlier면 제외) — 보수적 제거
      'iqr_and_mad' — 교집합 (둘 다 outlier여야 제외)        — 보수적 유지
      그 외 → 미적용
    k     — IQR 임계 (기본 1.5)
    k_mad — MAD 임계 (None이면 k와 동일, 통상 3.0)
    표본 < min_n: 자동 미적용 (통계적으로 무의미).
    """
    if method not in ("iqr", "mad", "iqr_or_mad", "iqr_and_mad"):
        return {"applied": False, "method": "none"}
    valid = [p for p in per_ticker if p.get("sigma") is not None]
    if len(valid) < min_n:
        return {"applied": False, "method": method, "k": k,
                "reason": f"표본 {len(valid)}<{min_n}: 필터 미적용"}
    sigs = np.array([p["sigma"] for p in valid], dtype=float)
    info = {"applied": True, "method": method, "k": k, "n_input": len(valid)}

    # IQR 산출
    iqr_out = set()
    iqr_info = None
    if method in ("iqr", "iqr_or_mad", "iqr_and_mad"):
        q1, q3 = np.percentile(sigs, [25, 75])
        iqr = float(q3 - q1)
        lo, hi = float(q1 - k * iqr), float(q3 + k * iqr)
        iqr_info = {"q1": float(q1), "q3": float(q3), "iqr": iqr, "lo": lo, "hi": hi}
        for i, p in enumerate(valid):
            if p["sigma"] < lo or p["sigma"] > hi:
                iqr_out.add(i)

    # MAD 산출
    mad_out = set()
    mad_info = None
    k_m = float(k_mad) if k_mad is not None else float(k)
    if method in ("mad", "iqr_or_mad", "iqr_and_mad"):
        med = float(np.median(sigs))
        mad = float(np.median(np.abs(sigs - med)))
        mad_info = {"median": med, "mad": mad, "k_mad": k_m}
        if mad > 0:
            for i, p in enumerate(valid):
                if abs(p["sigma"] - med) > k_m * mad:
                    mad_out.add(i)
        else:
            mad_info["note"] = "MAD=0(전 종목 σ 동일): MAD 검출 미적용"

    # 합집합/교집합 결정
    if method == "iqr":
        out_idx = iqr_out
    elif method == "mad":
        out_idx = mad_out
    elif method == "iqr_or_mad":
        out_idx = iqr_out | mad_out
    else:  # iqr_and_mad
        out_idx = iqr_out & mad_out

    # outlier 플래그 + 이유 (어느 방법에 잡혔는지)
    for i, p in enumerate(valid):
        if i in out_idx:
            p["outlier"] = True
            reasons = []
            if i in iqr_out and iqr_info:
                reasons.append(f"IQR {k:g}× 밖 (허용 {iqr_info['lo']*100:.2f}%~{iqr_info['hi']*100:.2f}%)")
            if i in mad_out and mad_info and mad_info.get("mad", 0) > 0:
                reasons.append(f"MAD {k_m:g}× 밖 (|σ−중앙값|>{k_m*mad_info['mad']*100:.2f}%)")
            p["outlier_reason"] = " · ".join(reasons) if reasons else "outlier"

    if iqr_info:
        info.update(iqr_info)
    if mad_info:
        info.update(mad_info)
    info["n_iqr_only"] = len(iqr_out - mad_out)
    info["n_mad_only"] = len(mad_out - iqr_out)
    info["n_both"] = len(iqr_out & mad_out)
    info["n_excluded"] = len(out_idx)
    return info


def multiple_trailings(closes, dates, trailing_years=(1, 2, 3, 5),
                       trading_days=252, log=True):
    """동일 종가 시계열에서 여러 trailing 기간의 σ를 동시에 산출.

    K-IFRS 1109 RCPS 평가에서 σ 산정 기간은 잔존만기에 가까울수록 정확
    (Damodaran "Investment Valuation" 3e Ch.5). 1y/3y/5y σ 비교로
    가정 robustness 확인 (5%p 이상 차이 시 평가자 판단 필요).

    closes: 시간순 정제된 종가 리스트
    dates: 동일 길이 ISO 날짜 리스트 (마지막 일자 기준 trailing 잘라냄)
    trailing_years: 산출할 기간들 (년 단위)

    Returns: [{"period_years", "n_obs", "sigma", "sigma_se", "ci95_low", "ci95_high"}, ...]
    """
    from datetime import date as _date
    if not closes or not dates or len(closes) != len(dates):
        return []
    try:
        end_date = _date.fromisoformat(str(dates[-1]))
    except Exception:
        return []
    results = []
    for y in trailing_years:
        # trailing y년: end_date - y*365일 이후 데이터만 사용
        cutoff_days = int(y * 365.25)
        sub_dates, sub_closes = [], []
        for d_str, c in zip(dates, closes):
            try:
                d = _date.fromisoformat(str(d_str))
                if (end_date - d).days <= cutoff_days:
                    sub_dates.append(d_str)
                    sub_closes.append(c)
            except Exception:
                continue
        if len(sub_closes) < 30:  # 최소 30거래일
            results.append({"period_years": y, "n_obs": len(sub_closes) - 1 if sub_closes else 0,
                           "sigma": None, "reason": "데이터 부족(<30 obs)"})
            continue
        try:
            hv = historical_vol(sub_closes, trading_days=trading_days, log=log)
            results.append({
                "period_years": y,
                "n_obs": hv["n_obs"],
                "sigma": hv["sigma"],
                "sigma_pct": round(hv["sigma"] * 100, 2),
                "sigma_se": hv["sigma_se"],
                "ci95_low": hv["ci95_low"],
                "ci95_high": hv["ci95_high"],
            })
        except Exception as e:
            results.append({"period_years": y, "sigma": None, "reason": str(e)[:80]})
    return results


def basket_volatility(series, trading_days=252, log=True, method="median",
                      outlier_method="none", outlier_k=None, outlier_k_mad=None):
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
            # 다중 trailing 기간 σ 비교 (1y/2y/3y/5y) — 데이터 충분 시
            trailings = multiple_trailings(cc, cleaned_dates,
                                           trailing_years=(1, 2, 3, 5),
                                           trading_days=td, log=log) if cleaned_dates else []
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
                "trailings": trailings,             # 1y/2y/3y/5y 비교
            })
            caps.append(s.get("cap"))
        except Exception as e:  # noqa: BLE001 — 종목별 실패는 스킵하고 사유 보존
            per.append({"ticker": tk, "name": s.get("name", tk), "sigma": None,
                        "error": str(e)})
            caps.append(None)
            failed.append({"ticker": tk, "error": str(e)})

    # 이상치 필터: IQR/MAD/합집합/교집합 모드 지원
    if outlier_k is None:
        outlier_k = 1.5 if outlier_method in ("iqr", "iqr_or_mad", "iqr_and_mad") else 3.0
    if outlier_k_mad is None:
        outlier_k_mad = 3.0 if outlier_method in ("mad", "iqr_or_mad", "iqr_and_mad") else None
    outlier_info = _detect_outliers(per, outlier_method, float(outlier_k),
                                    k_mad=outlier_k_mad)

    # 집계는 이상치 제외 후 수행. cap_weighted는 동일 인덱스 보존 필요
    active_idx = [i for i, p in enumerate(per) if p.get("sigma") is not None and not p.get("outlier")]
    active_per = [per[i] for i in active_idx]
    active_caps = [caps[i] for i in active_idx] if method == "cap_weighted" else None
    try:
        agg = aggregate(active_per, method=method, caps=active_caps)
        agg_err = None
    except Exception as e:  # noqa: BLE001
        agg, agg_err = None, str(e)

    # ── 바스켓 수준 trailing 비교: 종목별 trailings의 동일 기간 σ를 method로 집계
    basket_trailings = []
    for y in (1, 2, 3, 5):
        sigs = []
        ses = []
        for p in active_per:
            tlist = p.get("trailings") or []
            for t in tlist:
                if t.get("period_years") == y and t.get("sigma") is not None:
                    sigs.append(t["sigma"])
                    ses.append(t.get("sigma_se", 0))
                    break
        if sigs:
            import numpy as _np
            arr = _np.asarray(sigs)
            if method == "mean":
                agg_y = float(_np.mean(arr))
            else:  # default median (cap_weighted는 데이터 부족 시 fallback)
                agg_y = float(_np.median(arr))
            basket_trailings.append({
                "period_years": y,
                "sigma": agg_y,
                "sigma_pct": round(agg_y * 100, 2),
                "n_tickers": len(sigs),
                "avg_se": float(_np.mean(ses)) if ses else None,
            })
        else:
            basket_trailings.append({"period_years": y, "sigma": None,
                                     "reason": "데이터 부족"})

    return {"sigma": agg, "method": method, "per_ticker": per,
            "failed": failed, "error": agg_err, "outlier_info": outlier_info,
            "basket_trailings": basket_trailings}
