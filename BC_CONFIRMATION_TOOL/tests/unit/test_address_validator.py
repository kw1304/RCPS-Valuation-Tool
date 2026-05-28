import httpx
from unittest.mock import patch, MagicMock
from src.infrastructure.address_validator import AddressValidator

def test_validate_ok(monkeypatch):
    # juso.go.kr response stub
    fake = {
        "results": {
            "common": {"totalCount": "1"},
            "juso": [{"roadAddr": "서울특별시 종로구 종로 14", "zipNo": "03187"}]
        }
    }
    def mock_get(*args, **kwargs):
        m = MagicMock(); m.json = lambda: fake; m.raise_for_status = lambda: None; return m
    monkeypatch.setattr("httpx.get", mock_get)
    v = AddressValidator(confm_key="TEST")
    r = v.validate("서울특별시 종로구 종로 14")
    assert r["status"] == "ok"
    assert "03187" in r["zipcode"]

def test_validate_not_found(monkeypatch):
    fake = {"results": {"common": {"totalCount": "0"}, "juso": []}}
    def mock_get(*args, **kwargs):
        m = MagicMock(); m.json = lambda: fake; m.raise_for_status = lambda: None; return m
    monkeypatch.setattr("httpx.get", mock_get)
    v = AddressValidator(confm_key="TEST")
    r = v.validate("이상한 주소")
    assert r["status"] == "not_found"
