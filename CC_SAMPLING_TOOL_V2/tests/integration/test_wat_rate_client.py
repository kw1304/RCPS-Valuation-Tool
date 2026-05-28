import pytest
from unittest.mock import patch, MagicMock
from datetime import date
from src.infrastructure.fx.wat_rate_client import WatRateClient, RateLookupError


def _mock_response(status, body):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    return m


def test_lookup_rate_success():
    body = {"date": "2025-12-31", "rates": {"USD": 1300, "EUR": 1450}}
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               return_value=_mock_response(200, body)):
        c = WatRateClient(base_url="http://localhost:9090")
        rate = c.lookup("USD", date(2025, 12, 31))
        assert rate == 1300


def test_lookup_krw_returns_one():
    c = WatRateClient(base_url="http://localhost:9090")
    assert c.lookup("KRW", date(2025, 12, 31)) == 1.0


def test_lookup_unknown_ccy_raises():
    body = {"date": "2025-12-31", "rates": {"USD": 1300}}
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               return_value=_mock_response(200, body)):
        c = WatRateClient(base_url="http://localhost:9090")
        with pytest.raises(RateLookupError):
            c.lookup("EUR", date(2025, 12, 31))


def test_lookup_http_error_raises():
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               return_value=_mock_response(500, {})):
        c = WatRateClient(base_url="http://localhost:9090")
        with pytest.raises(RateLookupError):
            c.lookup("USD", date(2025, 12, 31))


def test_lookup_caches_per_date():
    body = {"date": "2025-12-31", "rates": {"USD": 1300}}
    mock_get = MagicMock(return_value=_mock_response(200, body))
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               mock_get):
        c = WatRateClient(base_url="http://localhost:9090")
        c.lookup("USD", date(2025, 12, 31))
        c.lookup("USD", date(2025, 12, 31))  # 캐시 적중
        assert mock_get.call_count == 1


def test_lookup_ttl_expires():
    """TTL 짧게 설정하면 캐시 만료 후 재호출."""
    import time
    from unittest.mock import patch, MagicMock
    body = {"date": "2025-12-31", "rates": {"USD": 1300}}
    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = body
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               mock_get):
        c = WatRateClient(base_url="http://localhost:9090", cache_ttl=0.1)
        c.lookup("USD", date(2025, 12, 31))
        time.sleep(0.2)
        c.lookup("USD", date(2025, 12, 31))
        assert mock_get.call_count == 2
