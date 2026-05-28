import pytest
from src.domain.entities import Account, Strata
from src.domain.sampling.allocation import allocate_strata


def _acc(pid, balance):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_allocate_proportional_to_strata_bv():
    # strata1 BV = 100, strata2 BV = 900, total_n = 10
    # → strata1 n=1, strata2 n=9
    accs = [_acc(f"s{i}", 10) for i in range(10)] + \
           [_acc(f"l{i}", 100) for i in range(9)]
    strata = [Strata(0, 50, n_required=0), Strata(50, 1000, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=10)
    assert result[0].n_required == 1
    assert result[1].n_required == 9


def test_allocate_total_n_zero():
    strata = [Strata(0, 100, n_required=0), Strata(100, 200, n_required=0)]
    accs = [_acc("a", 50)]
    result = allocate_strata(strata, accounts=accs, total_n=0)
    assert all(s.n_required == 0 for s in result)


def test_allocate_min_one_per_strata_with_bv():
    accs = [_acc("s1", 10), _acc("l1", 10_000)]
    strata = [Strata(0, 100, n_required=0), Strata(100, 100_000, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=5)
    assert result[0].n_required >= 1
    assert result[1].n_required >= 1
    assert result[0].n_required + result[1].n_required == 5


def test_allocate_empty_strata_gets_zero():
    accs = [_acc("a", 100)]
    strata = [Strata(0, 200, n_required=0), Strata(200, 300, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=5)
    assert result[0].n_required == 5
    assert result[1].n_required == 0


def test_allocate_preserves_strata_bounds():
    accs = [_acc(f"a{i}", 100) for i in range(10)]
    strata = [Strata(0, 500, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=3)
    assert result[0].low == 0 and result[0].high == 500
