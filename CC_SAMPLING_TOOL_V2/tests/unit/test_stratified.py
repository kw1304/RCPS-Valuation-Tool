import pytest
from src.domain.entities import Account, Strata
from src.domain.sampling.stratified import (
    suggest_strata, should_use_single_stratum, stratified_pps,
)


def _acc(pid, balance):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_single_stratum_when_small_population():
    accs = [_acc(f"p{i}", 100 * (i + 1)) for i in range(30)]
    assert should_use_single_stratum(accs) is True


def test_single_stratum_when_uniform():
    # CV < 0.3 → uniform
    accs = [_acc(f"p{i}", 1000 + i) for i in range(100)]
    assert should_use_single_stratum(accs) is True


def test_multi_stratum_when_diverse():
    # 명확한 분포 차이
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"m{i}", 10_000) for i in range(30)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    assert should_use_single_stratum(accs) is False


def test_suggest_strata_four_bins_default():
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"m{i}", 10_000) for i in range(30)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    strata = suggest_strata(accs, n_strata=4)
    assert len(strata) == 4
    # 인접 strata 경계 연속
    for i in range(len(strata) - 1):
        assert strata[i].high <= strata[i + 1].low + 1e-9


def test_suggest_strata_covers_all():
    accs = [_acc(f"p{i}", (i + 1) * 100) for i in range(100)]
    strata = suggest_strata(accs, n_strata=3)
    min_b = min(a.balance_krw for a in accs)
    max_b = max(a.balance_krw for a in accs)
    assert strata[0].low <= min_b
    assert strata[-1].high >= max_b


def test_stratified_pps_distributes_sample():
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    strata = [Strata(0, 1000, n_required=2),
              Strata(1000, 1_000_001, n_required=3)]
    sample = stratified_pps(accs, strata, seed=0)
    # 각 strata에서 정확히 n_required개 (가용 모집단 한도)
    assert len(sample) == 5


def test_stratified_pps_no_boundary_double_count():
    """Account at exact stratum boundary selected at most once."""
    # boundary account at balance=1000 sits in both [0,1000] and [1000,2000]
    accs = [_acc("boundary", 1000), _acc("small", 100), _acc("large", 1500)]
    strata = [Strata(0, 1000, n_required=2), Strata(1000, 2000, n_required=2)]
    sample = stratified_pps(accs, strata, seed=42)
    ids = [a.party_id for a in sample]
    assert ids.count("boundary") <= 1


def test_suggest_strata_n_strata_one():
    accs = [_acc(f"p{i}", 100 * (i + 1)) for i in range(50)]
    strata = suggest_strata(accs, n_strata=1)
    assert len(strata) == 1
    assert strata[0].low == 0.0


def test_suggest_strata_all_same_balance():
    accs = [_acc(f"p{i}", 5000) for i in range(50)]
    strata = suggest_strata(accs, n_strata=4)
    # 모두 동일 잔액 → 단일 strata 반환 (min_b == max_b early-return)
    assert len(strata) == 1


def test_suggest_strata_empty_or_all_zero():
    # 모두 잔액 0
    accs = [_acc(f"p{i}", 0) for i in range(5)]
    strata = suggest_strata(accs)
    assert len(strata) == 1
    assert strata[0].high == 0.0


def test_stratified_pps_deterministic_with_seed():
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    strata = [Strata(0, 1000, n_required=2),
              Strata(1000, 1_000_001, n_required=3)]
    s1 = stratified_pps(accs, strata, seed=42)
    s2 = stratified_pps(accs, strata, seed=42)
    assert [a.party_id for a in s1] == [a.party_id for a in s2]
