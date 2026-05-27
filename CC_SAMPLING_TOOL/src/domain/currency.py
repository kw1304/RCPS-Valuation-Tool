"""통화 환산 — PDF 원통화 금액 ↔ 장부 KRW 금액 비교 지원.

설계 원칙:
  - UploadGuide에 같은 거래처·계정에 두 통화가 함께 있으면 implicit 환율을 산출
  - 시장 범위 필터로 비현실적 환율 폐기 (예: USD 1로 100억 등 오류 방어)
  - manual_rates는 UploadGuide implicit rate를 덮어씀 (사용자 우선)
  - 환산 불가 시 None 반환 — caller가 "정확도 낮음" 표시

ISA 505 / K-IFRS 1021: 외화거래의 기능통화 환산은 거래일 환율이 원칙이나,
채권채무조회서 대사 목적으로는 UploadGuide에 기재된 환산금액(KRW)을 기준으로
implicit rate를 산출하는 것이 합리적 대안.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── 환율 시장 범위 (비현실적 값 방어) ────────────────────────────────────────
# 값이 이 범위를 벗어나면 implicit rate로 채택하지 않음
_RATE_SANITY: dict[str, tuple[float, float]] = {
    "USD": (800.0, 1800.0),
    "EUR": (900.0, 2000.0),
    "JPY": (5.0, 20.0),
    "CNY": (100.0, 300.0),
    "RMB": (100.0, 300.0),
    "SGD": (600.0, 1400.0),
    "AUD": (500.0, 1500.0),
    "MYR": (150.0, 500.0),
    "THB": (20.0, 60.0),
}


def _is_sane_rate(currency: str, rate: float) -> bool:
    """환율이 시장 범위 내인지 확인."""
    bounds = _RATE_SANITY.get(currency.upper())
    if bounds is None:
        return True  # 알 수 없는 통화 — 범위 검증 생략
    lo, hi = bounds
    return lo <= rate <= hi


class CurrencyResolver:
    """거래처별 원통화 ↔ KRW 환산 지원.

    사용 우선순위:
    1. manual_rates (사용자 입력)
    2. UploadGuide implicit rate (같은 거래처·계정에 원통화+KRW 병기 시 산출)
    3. 환산 불가 → None
    """

    def __init__(
        self,
        upload_guide_data=None,     # UploadGuideData | None
        manual_rates: Optional[dict[str, float]] = None,
    ):
        self._ug = upload_guide_data
        self._manual = {k.upper(): v for k, v in (manual_rates or {}).items()}
        self._implicit_rates: dict[str, float] = {}  # currency → KRW/1외화
        self._party_currency: dict[str, str] = {}    # party_name → dominant currency

        if upload_guide_data is not None:
            self._build_implicit_rates()

    # ── 공개 API ──────────────────────────────────────────────────────────

    def get_party_currency(self, party_name: str) -> Optional[str]:
        """UploadGuide에서 거래처의 주요 통화 반환 (가장 큰 금액의 통화)."""
        return self._party_currency.get(party_name)

    def get_party_amount_in_original(
        self,
        party_name: str,
        account: Optional[str] = None,
    ) -> Optional[tuple[float, str]]:
        """UploadGuide에서 거래처의 원통화 조회금액 반환 → (금액, 통화코드).

        account 지정 시 해당 계정만, None이면 합산.
        """
        if self._ug is None:
            return None

        contact = self._ug.contact_map().get(party_name)
        if contact is None:
            return None

        rows = contact.accounts  # list[(acct_name, currency, amount)]
        if account:
            rows = [(a, c, amt) for a, c, amt in rows if a == account]

        if not rows:
            return None

        # KRW가 아닌 통화 우선 반환 (원통화)
        non_krw = [(a, c, amt) for a, c, amt in rows if c.upper() != "KRW"]
        if non_krw:
            total = sum(amt for _, _, amt in non_krw)
            currency = non_krw[0][1]
            return (total, currency.upper())

        # KRW만 있으면 KRW 반환
        total = sum(amt for _, _, amt in rows)
        return (total, "KRW")

    def original_to_krw(self, amount: float, currency: str) -> Optional[float]:
        """원통화 금액 → KRW 환산. 환산 불가 시 None."""
        cur = currency.upper()
        if cur == "KRW":
            return amount
        rate = self._get_rate(cur)
        if rate is None:
            return None
        return amount * rate

    def krw_to_original(
        self,
        amount_krw: float,
        party_name: str,
        account: Optional[str] = None,
    ) -> Optional[tuple[float, str]]:
        """KRW 금액을 거래처 원통화로 역환산 → (환산금액, 통화코드).

        거래처 통화를 모르면 None.
        """
        orig = self.get_party_amount_in_original(party_name, account)
        if orig is None:
            return None
        _, currency = orig
        if currency == "KRW":
            return (amount_krw, "KRW")
        rate = self._get_rate(currency)
        if rate is None or rate == 0:
            return None
        return (amount_krw / rate, currency)

    def compare_amounts(
        self,
        ledger_krw: float,
        reply_amount: float,
        reply_currency: str,
        party_name: str,
        account: Optional[str] = None,
    ) -> dict:
        """장부 KRW와 회신 금액(원통화)을 비교.

        반환:
          {
            "ledger_krw": float,
            "reply_original": float,
            "reply_currency": str,
            "reply_krw": float | None,       — 환산 후 KRW
            "diff_krw": float | None,
            "diff_pct": float | None,
            "rate_used": float | None,
            "rate_source": "manual" | "implicit" | None,
            "comparison_possible": bool,
          }
        """
        cur = reply_currency.upper()
        if cur == "KRW":
            diff = ledger_krw - reply_amount
            diff_pct = diff / ledger_krw if ledger_krw != 0 else None
            return {
                "ledger_krw": ledger_krw,
                "reply_original": reply_amount,
                "reply_currency": "KRW",
                "reply_krw": reply_amount,
                "diff_krw": diff,
                "diff_pct": diff_pct,
                "rate_used": 1.0,
                "rate_source": None,
                "comparison_possible": True,
            }

        rate = self._get_rate(cur)
        if rate is None:
            # 환산 불가 — UploadGuide 원통화 금액과 직접 비교 시도
            orig_info = self.get_party_amount_in_original(party_name, account)
            if orig_info and orig_info[1].upper() == cur:
                ug_orig, _ = orig_info
                diff_orig = ug_orig - reply_amount
                diff_pct = diff_orig / ug_orig if ug_orig != 0 else None
                return {
                    "ledger_krw": ledger_krw,
                    "reply_original": reply_amount,
                    "reply_currency": cur,
                    "reply_krw": None,
                    "diff_krw": None,
                    "diff_pct": diff_pct,
                    "rate_used": None,
                    "rate_source": None,
                    "comparison_possible": True,
                }
            return {
                "ledger_krw": ledger_krw,
                "reply_original": reply_amount,
                "reply_currency": cur,
                "reply_krw": None,
                "diff_krw": None,
                "diff_pct": None,
                "rate_used": None,
                "rate_source": None,
                "comparison_possible": False,
            }

        reply_krw = reply_amount * rate
        diff = ledger_krw - reply_krw
        diff_pct = diff / ledger_krw if ledger_krw != 0 else None
        rate_src = "manual" if cur in self._manual else "implicit"
        return {
            "ledger_krw": ledger_krw,
            "reply_original": reply_amount,
            "reply_currency": cur,
            "reply_krw": reply_krw,
            "diff_krw": diff,
            "diff_pct": diff_pct,
            "rate_used": rate,
            "rate_source": rate_src,
            "comparison_possible": True,
        }

    # ── 내부 메서드 ────────────────────────────────────────────────────────

    def _get_rate(self, currency: str) -> Optional[float]:
        """통화 → KRW/1외화 환율. manual → implicit 순. 없으면 None."""
        cur = currency.upper()
        if cur in self._manual:
            return self._manual[cur]
        if cur in self._implicit_rates:
            return self._implicit_rates[cur]
        return None

    def _build_implicit_rates(self) -> None:
        """UploadGuide에서 implicit 환율 산출.

        같은 거래처·같은 계정에:
          - 통화1 ≠ KRW, 금액1 (원통화)
          - 통화2 = KRW, 금액2 (원화환산)
        이면 rate = 금액2 / 금액1

        복수 거래처에서 동일 통화 implicit rate가 나오면 중앙값 사용.
        """
        rate_candidates: dict[str, list[float]] = {}

        for contact in self._ug.send_targets:
            accts = contact.accounts  # list[(acct_name, currency, amount)]
            # 계정별 그룹핑
            acct_groups: dict[str, list[tuple[str, float]]] = {}
            for acct_name, cur, amt in accts:
                if acct_name not in acct_groups:
                    acct_groups[acct_name] = []
                acct_groups[acct_name].append((cur.upper(), amt))

            for acct_name, entries in acct_groups.items():
                krw_entries = [(c, a) for c, a in entries if c == "KRW"]
                non_krw_entries = [(c, a) for c, a in entries if c != "KRW"]

                for orig_cur, orig_amt in non_krw_entries:
                    if orig_amt <= 0:
                        continue
                    for _, krw_amt in krw_entries:
                        if krw_amt <= 0:
                            continue
                        rate = krw_amt / orig_amt
                        if _is_sane_rate(orig_cur, rate):
                            if orig_cur not in rate_candidates:
                                rate_candidates[orig_cur] = []
                            rate_candidates[orig_cur].append(rate)

            # 거래처 주요 통화 기록 (가장 큰 비KRW 금액 기준)
            non_krw_all = [(c, a) for _, c, a in accts if c.upper() != "KRW"]
            if non_krw_all:
                dominant = max(non_krw_all, key=lambda x: x[1])
                self._party_currency[contact.name] = dominant[0].upper()

        # 중앙값으로 implicit rate 확정
        for cur, rates in rate_candidates.items():
            if rates:
                rates.sort()
                mid = len(rates) // 2
                self._implicit_rates[cur] = rates[mid]
