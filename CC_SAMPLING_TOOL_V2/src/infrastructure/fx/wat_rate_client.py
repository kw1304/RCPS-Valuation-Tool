"""WAT /api/rates HTTP wrapper.

설계서 §5.5. 기말환율 조회·캐싱.
"""
from __future__ import annotations
from datetime import date
from typing import Optional
import requests


class RateLookupError(Exception):
    pass


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
            rates = self._fetch(period_end)
            self._cache[key] = (now, rates)
        else:
            rates = entry[1]
        if ccy.upper() not in rates:
            raise RateLookupError(
                f"ccy {ccy} not available at {key}; available: {sorted(rates)}"
            )
        return rates[ccy.upper()]

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
