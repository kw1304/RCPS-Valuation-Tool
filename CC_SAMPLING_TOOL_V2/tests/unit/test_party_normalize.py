import pytest
from src.domain.party_normalize import normalize_party_name, match_party


def test_normalize_strips_corp_prefix():
    assert normalize_party_name("(주)고객사001") == "고객사001"
    assert normalize_party_name("주식회사 고객사001") == "고객사001"
    assert normalize_party_name("(유)동방") == "동방"


def test_normalize_strips_whitespace():
    assert normalize_party_name("  고객사 001  ") == "고객사001"
    assert normalize_party_name("고객사\t001") == "고객사001"


def test_normalize_keeps_korean_chars():
    assert normalize_party_name("(주)대한물류") == "대한물류"


def test_normalize_lowers_english():
    assert normalize_party_name("ABC Co., Ltd.") == "abcco.,ltd."


def test_match_exact():
    assert match_party("고객사001", ["고객사001", "공급사001"]) == "고객사001"


def test_match_with_corp_prefix():
    assert match_party("(주)고객사001", ["고객사001"]) == "고객사001"
    assert match_party("주식회사 갑상사", ["갑상사"]) == "갑상사"


def test_match_no_match():
    assert match_party("전혀다른회사", ["갑상사", "을상사"]) is None


def test_match_picks_first_candidate_when_ambiguous():
    assert match_party("(주)갑", ["갑", "을갑"]) == "갑"
