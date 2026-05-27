"""test_currency_resolver — UploadGuide implicit rate 산출 + 환산 검증."""
from __future__ import annotations

import pytest
from src.domain.currency import CurrencyResolver, _is_sane_rate
from src.infrastructure.loaders import UploadGuideData, PartyContact


def _make_ug_with_rate(name: str, acct: str, orig_cur: str, orig_amt: float, krw_amt: float) -> UploadGuideData:
    """원통화 + KRW 병기 UploadGuide mock."""
    contact = PartyContact(
        name=name,
        accounts=[
            (acct, orig_cur, orig_amt),
            (acct, "KRW", krw_amt),
        ]
    )
    return UploadGuideData(send_targets=[contact])


# ── sanity check ─────────────────────────────────────────────────────────────

def test_sane_rate_usd_valid():
    assert _is_sane_rate("USD", 1300.0) is True


def test_sane_rate_usd_too_low():
    assert _is_sane_rate("USD", 100.0) is False


def test_sane_rate_usd_too_high():
    assert _is_sane_rate("USD", 5000.0) is False


def test_sane_rate_jpy_valid():
    assert _is_sane_rate("JPY", 9.0) is True


def test_sane_rate_cny_valid():
    assert _is_sane_rate("CNY", 180.0) is True


# ── implicit rate 산출 ────────────────────────────────────────────────────────

def test_implicit_rate_usd():
    """USD 100,000 → KRW 130,000,000 이면 implicit rate = 1300."""
    ug = _make_ug_with_rate("COSMAX USA", "외상매출금", "USD", 100_000, 130_000_000)
    resolver = CurrencyResolver(ug)
    rate = resolver._implicit_rates.get("USD")
    assert rate is not None
    assert abs(rate - 1300.0) < 1.0


def test_implicit_rate_jpy():
    ug = _make_ug_with_rate("JP Partner", "미수금", "JPY", 10_000_000, 90_000_000)
    resolver = CurrencyResolver(ug)
    rate = resolver._implicit_rates.get("JPY")
    assert rate is not None
    assert abs(rate - 9.0) < 0.1


def test_implicit_rate_cny():
    ug = _make_ug_with_rate("CN Partner", "외상매출금", "CNY", 1_000_000, 180_000_000)
    resolver = CurrencyResolver(ug)
    rate = resolver._implicit_rates.get("CNY")
    assert rate is not None
    assert abs(rate - 180.0) < 1.0


def test_implicit_rate_sanity_filter():
    """환율이 시장 범위 벗어나면 폐기 → None."""
    ug = _make_ug_with_rate("Bad Rate Party", "외상매출금", "USD", 100, 100_000_000)
    # rate = 1,000,000 → 비정상
    resolver = CurrencyResolver(ug)
    rate = resolver._implicit_rates.get("USD")
    assert rate is None


# ── original_to_krw ───────────────────────────────────────────────────────────

def test_original_to_krw_uses_implicit():
    ug = _make_ug_with_rate("COSMAX USA", "외상매출금", "USD", 100_000, 130_000_000)
    resolver = CurrencyResolver(ug)
    result = resolver.original_to_krw(100_000, "USD")
    assert result is not None
    assert abs(result - 130_000_000) < 100


def test_original_to_krw_manual_overrides():
    ug = _make_ug_with_rate("COSMAX USA", "외상매출금", "USD", 100_000, 130_000_000)
    resolver = CurrencyResolver(ug, manual_rates={"USD": 1350.0})
    result = resolver.original_to_krw(100_000, "USD")
    assert result is not None
    assert abs(result - 135_000_000) < 100


def test_original_to_krw_krw_passthrough():
    resolver = CurrencyResolver()
    result = resolver.original_to_krw(1_000_000, "KRW")
    assert result == 1_000_000


def test_original_to_krw_unknown_currency():
    """알 수 없는 통화 → None."""
    resolver = CurrencyResolver()
    result = resolver.original_to_krw(100, "XYZ")
    assert result is None


# ── get_party_currency ────────────────────────────────────────────────────────

def test_get_party_currency():
    ug = _make_ug_with_rate("COSMAX USA", "외상매출금", "USD", 100_000, 130_000_000)
    resolver = CurrencyResolver(ug)
    cur = resolver.get_party_currency("COSMAX USA")
    assert cur == "USD"


def test_get_party_currency_unknown():
    resolver = CurrencyResolver()
    assert resolver.get_party_currency("없는거래처") is None


# ── compare_amounts ───────────────────────────────────────────────────────────

def test_compare_amounts_krw():
    resolver = CurrencyResolver()
    result = resolver.compare_amounts(
        ledger_krw=1_000_000,
        reply_amount=1_000_000,
        reply_currency="KRW",
        party_name="테스트",
    )
    assert result["comparison_possible"] is True
    assert result["diff_krw"] == 0.0


def test_compare_amounts_usd_matched():
    ug = _make_ug_with_rate("COSMAX USA", "외상매출금", "USD", 100_000, 130_000_000)
    resolver = CurrencyResolver(ug)
    result = resolver.compare_amounts(
        ledger_krw=130_000_000,
        reply_amount=100_000,
        reply_currency="USD",
        party_name="COSMAX USA",
    )
    assert result["comparison_possible"] is True
    assert abs(result["diff_krw"]) < 100  # 차이 없음


def test_compare_amounts_usd_mismatch():
    ug = _make_ug_with_rate("COSMAX USA", "외상매출금", "USD", 100_000, 130_000_000)
    resolver = CurrencyResolver(ug)
    result = resolver.compare_amounts(
        ledger_krw=130_000_000,
        reply_amount=90_000,   # USD 10,000 부족
        reply_currency="USD",
        party_name="COSMAX USA",
    )
    assert result["comparison_possible"] is True
    assert result["diff_krw"] > 0  # 장부가 > 회신


def test_compare_amounts_no_rate():
    """환율 정보 없으면 comparison_possible=False."""
    resolver = CurrencyResolver()
    result = resolver.compare_amounts(
        ledger_krw=130_000_000,
        reply_amount=100_000,
        reply_currency="USD",
        party_name="알 수 없는 거래처",
    )
    assert result["comparison_possible"] is False
