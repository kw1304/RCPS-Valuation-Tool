from pathlib import Path
from src.domain.party_normalize import PartyNormalizer

CFG_DIR = Path(__file__).resolve().parents[2] / "configs"

def test_canonical_simple():
    n = PartyNormalizer.load(CFG_DIR)
    assert n.normalize("KB국민은행").canonical == "국민은행"
    assert n.normalize("국민銀").canonical == "국민은행"

def test_domestic_branch_collapses_to_head():
    n = PartyNormalizer.load(CFG_DIR)
    a = n.normalize("신한은행 강남지점")
    b = n.normalize("신한은행 용인지점")
    assert a.canonical == "신한은행"
    assert a.branch is None
    assert a.is_foreign is False
    assert b.canonical == "신한은행"
    assert a.entity_key() == b.entity_key()

def test_foreign_branch_separate():
    n = PartyNormalizer.load(CFG_DIR)
    a = n.normalize("신한은행 강남지점")
    b = n.normalize("신한은행 도쿄지점")
    c = n.normalize("신한은행 홍콩")
    d = n.normalize("국민은행 런던지점")
    assert b.canonical == "신한은행"
    assert b.branch == "도쿄지점"
    assert b.is_foreign is True
    assert c.branch == "홍콩지점"
    assert d.branch == "런던지점"
    assert a.entity_key() != b.entity_key()
    assert b.entity_key() != c.entity_key()

def test_long_candidate_wins():
    n = PartyNormalizer.load(CFG_DIR)
    assert n.normalize("KEB하나은행 강남지점").canonical == "KEB하나은행"

def test_unknown_returns_raw():
    n = PartyNormalizer.load(CFG_DIR)
    r = n.normalize("XYZ캐피탈")
    assert r.canonical == "XYZ캐피탈"
