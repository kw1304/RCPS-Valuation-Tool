import pytest
from src.domain.entities import Account
from src.domain.allowance import (
    is_fully_provisioned, classify_allowance_band,
)


def _acc(balance, allowance):
    return Account(party_id="p", name="p", gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance, allowance_amt=allowance,
                   is_bad_debt=(allowance == balance and balance > 0))


def test_fully_provisioned_true():
    a = _acc(1000, 1000)
    assert is_fully_provisioned(a) is True


def test_fully_provisioned_false_partial():
    a = _acc(1000, 500)
    assert is_fully_provisioned(a) is False


def test_fully_provisioned_zero_balance_false():
    a = _acc(0, 0)
    assert is_fully_provisioned(a) is False


def test_fully_provisioned_not_flagged_bad():
    # allowance == balance인데 is_bad_debt 플래그 없으면 False
    a = Account(party_id="p", name="p", gl_account="x",
                balance_orig=1000, ccy="KRW", fx_rate=1.0,
                balance_krw=1000, allowance_amt=1000, is_bad_debt=False)
    assert is_fully_provisioned(a) is False


def test_band_normal():
    a = _acc(1000, 0)
    assert classify_allowance_band(a) == "NORMAL"


def test_band_partial():
    a = _acc(1000, 300)
    assert classify_allowance_band(a) == "PARTIAL"


def test_band_full():
    a = _acc(1000, 1000)
    assert classify_allowance_band(a) == "FULL"


def test_band_excess():
    a = _acc(1000, 1500)
    assert classify_allowance_band(a) == "EXCESS"  # 이상 — 데이터 검증 필요
