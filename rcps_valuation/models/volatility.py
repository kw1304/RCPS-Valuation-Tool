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
    """
    c = np.asarray(closes, dtype=float)
    if c.size < 2:
        raise ValueError("종가가 2개 이상 필요합니다 (수익률 계산 불가).")
    if log:
        rets = np.diff(np.log(c))
    else:
        rets = c[1:] / c[:-1] - 1.0
    daily_sigma = float(np.std(rets, ddof=1))
    sigma = daily_sigma * math.sqrt(trading_days)
    return {
        "sigma": sigma,                     # 연율 변동성(소수, 0.241 = 24.1%)
        "daily_sigma": daily_sigma,
        "n_obs": int(rets.size),            # 수익률 관측치 수
        "n_prices": int(c.size),
        "trading_days": trading_days,
        "log_returns": bool(log),
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


def basket_volatility(series, trading_days=252, log=True, method="median"):
    """유사기업 바스켓 σ 산출 (편의 래퍼).

    series: {ticker: {"name", "dates", "closes", "volumes"(opt), "cap"(opt)}}
    Returns {"sigma", "method", "per_ticker":[...], "failed":[...]}.
    """
    per, caps, failed = [], [], []
    for tk, s in series.items():
        try:
            _, cc, removed = clean_closes(s.get("dates"), s["closes"], s.get("volumes"))
            hv = historical_vol(cc, trading_days=trading_days, log=log)
            per.append({
                "ticker": tk,
                "name": s.get("name", tk),
                "sigma": hv["sigma"],
                "n_obs": hv["n_obs"],
                "removed": removed,
                "cap": s.get("cap"),
            })
            caps.append(s.get("cap"))
        except Exception as e:  # noqa: BLE001 — 종목별 실패는 스킵하고 사유 보존
            per.append({"ticker": tk, "name": s.get("name", tk), "sigma": None,
                        "error": str(e)})
            caps.append(None)
            failed.append({"ticker": tk, "error": str(e)})

    # 전 종목 실패 시 raise 하지 않고 sigma=None 으로 반환(라우트가 사유를 안내)
    try:
        agg = aggregate(per, method=method, caps=caps if method == "cap_weighted" else None)
        agg_err = None
    except Exception as e:  # noqa: BLE001
        agg, agg_err = None, str(e)
    return {"sigma": agg, "method": method, "per_ticker": per,
            "failed": failed, "error": agg_err}
