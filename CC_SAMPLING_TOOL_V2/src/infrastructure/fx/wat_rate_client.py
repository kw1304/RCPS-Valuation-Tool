"""WAT /api/rates HTTP wrapper.

설계서 §5.5. 기말환율 조회·캐싱.
"""
from __future__ import annotations
from datetime import date
from typing import Optional
import requests


class RateLookupError(Exception):
    pass


# FY25 기말환율 fallback — 한국은행 매매기준율 2025-12-31 근사 (KRW per 1단위).
# WAT 서버 (localhost:9090) 미가용 시 사용. 실무엔 정확한 환율로 교체 권장.
_FALLBACK_RATES_FY25 = {
    "USD": 1472.5,
    "EUR": 1531.0,
    "JPY": 9.36,        # 100엔당 936원 → 1엔당 9.36원
    "CNY": 201.3,
    "HKD": 188.0,
    "GBP": 1856.0,
    "AUD": 925.0,
    "SGD": 1086.0,
    "THB": 41.5,
    "MYR": 313.0,
    "VND": 0.059,
    "TWD": 44.7,
    "IDR": 0.090,
}


class WatRateClient:
    def __init__(self, base_url: str = "http://localhost:9090",
                 timeout: float = 5.0, cache_ttl: float = 3600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict[str, float]]] = {}

    def lookup(self, ccy: str, period_end: date) -> float:
        if ccy.upper() == "KRW":
            return 1.0
        key = period_end.isoformat()
        import time
        entry = self._cache.get(key)
        now = time.time()
        if entry is None or (now - entry[0]) > self.cache_ttl:
            rates: dict[str, float]
            try:
                rates = self._fetch(period_end)
            except RateLookupError:
                # 1차 fallback: Frankfurter (ECB, 무료·인증 X)
                try:
                    rates = _fetch_frankfurter(period_end)
                except RateLookupError:
                    # 2차 fallback: 내장 hardcoded — FY25 기말환율이므로 2025 기말만 적용.
                    # 타 기간엔 부정확 → 빈 dict로 두고 호출측이 원장 fx_rate 사용.
                    rates = dict(_FALLBACK_RATES_FY25) if period_end.year == 2025 else {}
            self._cache[key] = (now, rates)
        else:
            rates = entry[1]
        ccy_u = ccy.upper()
        if ccy_u not in rates:
            # 라이브 응답에 해당 통화 누락 시 내장값 보충 — 단 FY25 기말에만.
            # period_end가 2025가 아니면 FY25 상수는 틀린 환율이므로 사용 금지.
            fb = _FALLBACK_RATES_FY25.get(ccy_u)
            if fb is not None and period_end.year == 2025:
                return fb
            raise RateLookupError(
                f"ccy {ccy} not available at {key}; available: {sorted(rates)}"
            )
        return rates[ccy_u]

    def _fetch(self, period_end: date) -> dict[str, float]:
        url = f"{self.base_url}/api/rates"
        try:
            resp = requests.get(url, params={"date": period_end.isoformat()},
                                timeout=self.timeout)
        except requests.RequestException as e:
            raise RateLookupError(f"WAT /api/rates request failed: {e}") from e
        if resp.status_code != 200:
            raise RateLookupError(
                f"WAT /api/rates {resp.status_code}: {resp.text[:200]}"
            )
        body = resp.json()
        rates = body.get("rates", {})
        return {k.upper(): float(v) for k, v in rates.items()}


# Frankfurter API (https://frankfurter.dev) — ECB 매매기준율, 무료·인증 X.
# 평일 환율만 (주말·공휴일은 직전 영업일). 한국은행 매매기준율과 미세 차이 가능.
_FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"
_FRANKFURTER_CCYS = ["USD", "EUR", "JPY", "CNY", "HKD", "GBP", "AUD",
                     "SGD", "THB", "MYR", "TWD", "IDR"]


def _fetch_frankfurter(period_end: date) -> dict[str, float]:
    """Frankfurter API → 모든 외화에 대해 KRW 환율 fetch (한 번 호출).

    base=KRW로 query 후 결과 inverse 가져옴 (rates[CCY] = 1KRW당 CCY) →
    KRW per 1 CCY = 1 / rates[CCY].
    """
    url = f"{_FRANKFURTER_BASE}/{period_end.isoformat()}"
    params = {"base": "KRW", "symbols": ",".join(_FRANKFURTER_CCYS)}
    try:
        resp = requests.get(url, params=params, timeout=5.0,
                             allow_redirects=True)
    except requests.RequestException as e:
        raise RateLookupError(f"Frankfurter request failed: {e}") from e
    if resp.status_code != 200:
        raise RateLookupError(
            f"Frankfurter {resp.status_code}: {resp.text[:200]}"
        )
    body = resp.json()
    raw = body.get("rates", {}) or {}
    # Frankfurter rates: 1 KRW = X CCY → KRW per 1 CCY = 1/X
    out: dict[str, float] = {}
    for ccy, v in raw.items():
        try:
            f = float(v)
            if f > 0:
                out[ccy.upper()] = 1.0 / f
        except (ValueError, TypeError):
            continue
    if not out:
        raise RateLookupError("Frankfurter returned empty rates")
    return out
