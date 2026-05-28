from src.domain.crosscheck import (
    bidirectional_compare, prior_compare, listed_in_cs
)


def test_bidirectional_extracted_only():
    extracted = [("국민은행", None), ("신한은행", "도쿄지점")]
    cs        = [("국민은행", None)]
    result = bidirectional_compare(extracted, cs)
    # 우리만 있는 것 (신한 도쿄) → status="missing_in_cs"
    statuses = {(r["canonical"], r["branch"]): r["status"] for r in result}
    assert statuses[("국민은행", None)] == "both"
    assert statuses[("신한은행", "도쿄지점")] == "missing_in_cs"


def test_bidirectional_cs_only_flagged():
    extracted = [("국민은행", None)]
    cs        = [("국민은행", None), ("우리은행", None)]
    result = bidirectional_compare(extracted, cs)
    statuses = {(r["canonical"], r["branch"]): r["status"] for r in result}
    assert statuses[("우리은행", None)] == "extra_in_cs"


def test_prior_fuzzy_match():
    current = [("KEB하나은행", None)]
    prior   = [("하나은행", None)]
    result = prior_compare(current, prior, threshold=0.85)
    # canonical 다르지만 fuzzy로 매칭됨
    assert any(r["status"] == "both" and r["canonical"] == "KEB하나은행" for r in result)


def test_listed_in_cs_simple():
    cs = [("국민은행", None), ("신한은행", None)]
    targets = [("국민은행", None), ("우리은행", None)]
    result = listed_in_cs(targets, cs)
    by_key = {(r["canonical"], r["branch"]): r for r in result}
    assert by_key[("국민은행", None)]["present"] is True
    assert by_key[("우리은행", None)]["present"] is False
