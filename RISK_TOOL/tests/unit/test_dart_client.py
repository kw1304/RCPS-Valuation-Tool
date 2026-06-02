"""DartClient smoke — 네트워크 호출 없이 import·생성·early-return 가드."""
from risk.infrastructure.dart.client import DartClient, DartError, _normalize_name


def test_import_and_api_key():
    assert DartClient(api_key="x").api_key == "x"


def test_find_corp_code_empty_name_returns_none_without_network():
    # 빈/None 이름 → 네트워크 접근 전 early return None
    c = DartClient(api_key="x")
    assert c.find_corp_code("") is None
    assert c.find_corp_code(None) is None


def test_normalize_name_strips_legal_form():
    assert _normalize_name("(주)테스트 회사") == "테스트회사"
    assert _normalize_name("주식회사 ABC") == "abc"


def test_dart_error_is_exception():
    assert issubclass(DartError, Exception)
