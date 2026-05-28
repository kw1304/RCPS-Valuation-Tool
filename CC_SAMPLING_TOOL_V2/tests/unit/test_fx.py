import pytest
from src.domain.fx import convert_to_base, FxRateMissing


def test_convert_same_currency_noop():
    assert convert_to_base(amount=1000, ccy="KRW",
                           base_ccy="KRW", rate=None) == 1000


def test_convert_with_rate():
    # USD 100 × 1300 = 130000
    assert convert_to_base(amount=100, ccy="USD",
                           base_ccy="KRW", rate=1300) == 130_000


def test_convert_missing_rate_raises():
    with pytest.raises(FxRateMissing):
        convert_to_base(amount=100, ccy="EUR",
                        base_ccy="KRW", rate=None)


def test_convert_zero_rate_raises():
    with pytest.raises(FxRateMissing):
        convert_to_base(amount=100, ccy="EUR",
                        base_ccy="KRW", rate=0)


def test_convert_negative_amount():
    # 환불금 -100 USD × 1300
    assert convert_to_base(amount=-100, ccy="USD",
                           base_ccy="KRW", rate=1300) == -130_000


def test_convert_same_currency_rate_ignored():
    # 동일통화면 rate 무의미
    assert convert_to_base(amount=500, ccy="KRW",
                           base_ccy="KRW", rate=9999) == 500
