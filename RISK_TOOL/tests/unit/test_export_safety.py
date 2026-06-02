from risk.interface.api.app import _safe_stem


def test_safe_stem_strips_path_traversal():
    s = _safe_stem("../../evil")
    assert "/" not in s
    assert "\\" not in s
    assert ".." not in s


def test_safe_stem_preserves_korean():
    assert _safe_stem("삼성전자") == "삼성전자"


def test_safe_stem_empty_falls_back():
    assert _safe_stem("") == "company"
    assert _safe_stem("///") == "company" or "/" not in _safe_stem("///")


def test_safe_stem_truncates_long_names():
    assert len(_safe_stem("가" * 200)) <= 50
