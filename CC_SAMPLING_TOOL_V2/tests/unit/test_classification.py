import pytest
from src.domain.entities import Account, SelectionReason
from src.domain.sampling.classification import classify_population


def _acc(pid, balance, **kw):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance, **kw)


def test_zero_balance_excluded():
    accs = [_acc("p", 0)]
    forced, excluded, remaining = classify_population(accs, key_threshold=1000)
    assert forced == []
    assert excluded[0][1] == SelectionReason.EXCLUDED_ZERO
    assert remaining == []


def test_bad_debt_full_provisioned_excluded():
    accs = [_acc("p", 1000, is_bad_debt=True, allowance_amt=1000)]
    forced, excluded, remaining = classify_population(accs, key_threshold=999_999_999)
    assert excluded[0][1] == SelectionReason.EXCLUDED_BAD


def test_bad_priority_over_rp():
    accs = [_acc("p", 1000, is_bad_debt=True, allowance_amt=1000,
                 is_related_party=True)]
    _, excluded, _ = classify_population(accs, key_threshold=999_999_999)
    assert excluded[0][1] == SelectionReason.EXCLUDED_BAD


def test_zero_priority_over_rp():
    accs = [_acc("p", 0, is_related_party=True)]
    _, excluded, _ = classify_population(accs, key_threshold=999)
    assert excluded[0][1] == SelectionReason.EXCLUDED_ZERO


def test_rp_forced():
    accs = [_acc("p", 100, is_related_party=True)]
    forced, _, _ = classify_population(accs, key_threshold=999_999_999)
    assert forced[0][1] == SelectionReason.FORCED_RP


def test_rp_skips_key_check():
    # RP인 acc은 잔액 >= key여도 FORCED_RP로 분류 (KEY 검사 skip)
    accs = [_acc("p", 9_999_999, is_related_party=True)]
    forced, _, _ = classify_population(accs, key_threshold=100)
    assert forced[0][1] == SelectionReason.FORCED_RP


def test_key_no_longer_forced():
    # 설계 변경: FORCED_KEY 제거 — 잔액 큰 거래처는 PPS 가중추출로 선정,
    # 강제포함은 RP만. (감사상 Key item 전수 보장 약화 — 별도 검토 대상)
    accs = [_acc("p", 5_000_000)]
    forced, _, remaining = classify_population(accs, key_threshold=1_000_000)
    assert not forced
    assert remaining == accs


def test_below_key_goes_to_remaining():
    accs = [_acc("p", 100)]
    _, _, remaining = classify_population(accs, key_threshold=1_000_000)
    assert remaining == accs


def test_classify_full_example():
    accs = [
        _acc("rp", 100, is_related_party=True),
        _acc("bad", 500, is_bad_debt=True, allowance_amt=500),
        _acc("zero", 0),
        _acc("key", 10_000_000),
        _acc("rep", 50_000),
    ]
    forced, excluded, remaining = classify_population(accs, key_threshold=1_000_000)
    forced_ids = {a.party_id for a, _ in forced}
    excluded_ids = {a.party_id for a, _ in excluded}
    remaining_ids = {a.party_id for a in remaining}
    # FORCED_KEY 제거 → 'key'는 강제포함 아닌 remaining(PPS 후보)으로
    assert forced_ids == {"rp"}
    assert excluded_ids == {"bad", "zero"}
    assert remaining_ids == {"rep", "key"}
