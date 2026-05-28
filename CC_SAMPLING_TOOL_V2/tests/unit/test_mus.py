import pytest
from src.domain.entities import Account
from src.domain.sampling.mus import pps_select


def _acc(pid, balance):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_pps_deterministic_with_seed():
    accs = [_acc(f"P{i}", (i + 1) * 100) for i in range(10)]
    s1 = pps_select(accs, n=3, seed=42)
    s2 = pps_select(accs, n=3, seed=42)
    assert [a.party_id for a in s1] == [a.party_id for a in s2]


def test_pps_returns_n_accounts():
    accs = [_acc(f"P{i}", 100) for i in range(20)]
    s = pps_select(accs, n=5, seed=0)
    assert len(s) == 5


def test_pps_larger_balances_more_likely():
    """PPS = probability proportional to size."""
    accs = [_acc("small", 1), _acc("big", 9999)]
    s = pps_select(accs, n=1, seed=0)
    # big has ~99.99% probability — likely selected
    assert s[0].party_id == "big"


def test_pps_n_zero_returns_empty():
    accs = [_acc("a", 100)]
    assert pps_select(accs, n=0, seed=0) == []


def test_pps_n_geq_population_returns_all():
    accs = [_acc("a", 100), _acc("b", 200)]
    s = pps_select(accs, n=5, seed=0)
    assert {a.party_id for a in s} == {"a", "b"}


def test_pps_skips_zero_balance():
    accs = [_acc("zero", 0), _acc("real", 1000)]
    s = pps_select(accs, n=1, seed=0)
    assert s[0].party_id == "real"


def test_pps_negative_balance_uses_abs():
    accs = [_acc("refund", -5000), _acc("normal", 1)]
    s = pps_select(accs, n=1, seed=0)
    assert s[0].party_id == "refund"
