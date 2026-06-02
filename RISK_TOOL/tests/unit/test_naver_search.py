import pytest
from risk.infrastructure.news import naver_search
from risk.infrastructure.news.naver_search import NaverNewsSearch, strip_html


def test_disabled_without_keys(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    monkeypatch.delenv("NAVER_CLIENT_SECRET", raising=False)
    nv = NaverNewsSearch(client_id=None, client_secret=None)
    assert nv.enabled is False
    assert nv("x") == []


def test_disabled_with_empty_strings():
    nv = NaverNewsSearch(client_id="", client_secret="")
    assert nv.enabled is False
    assert nv("x") == []


def test_strip_html():
    assert strip_html("<b>삼성</b> &amp; 횡령") == "삼성 & 횡령"
    assert strip_html("&lt;a&gt; &quot;q&quot;") == '<a> "q"'
    assert strip_html("") == ""


class _FakeResp:
    status_code = 200

    def json(self):
        return {
            "items": [
                {
                    "title": "<b>삼성</b> 횡령 의혹",
                    "originallink": "http://orig",
                    "link": "http://naver",
                    "description": "<b>삼성</b> &amp; 관련 보도",
                    "pubDate": "Mon, 01 Jun 2026 09:00:00 +0900",
                }
            ]
        }


def test_call_maps_items(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert headers["X-Naver-Client-Id"] == "cid"
        assert headers["X-Naver-Client-Secret"] == "csec"
        assert params["query"] == "삼성 횡령"
        return _FakeResp()

    monkeypatch.setattr(naver_search.requests, "get", fake_get)
    nv = NaverNewsSearch(client_id="cid", client_secret="csec")
    assert nv.enabled is True
    out = nv("삼성 횡령")
    assert len(out) == 1
    hit = out[0]
    assert hit["title"] == "삼성 횡령 의혹"
    assert hit["url"] == "http://orig"
    assert hit["snippet"] == "삼성 & 관련 보도"
    assert hit["date"] == "Mon, 01 Jun 2026 09:00:00 +0900"


def test_call_uses_link_when_no_originallink(monkeypatch):
    class _R:
        status_code = 200

        def json(self):
            return {"items": [{"title": "t", "link": "http://naver", "description": "d", "pubDate": "x"}]}

    monkeypatch.setattr(naver_search.requests, "get", lambda *a, **k: _R())
    nv = NaverNewsSearch(client_id="cid", client_secret="csec")
    out = nv("q")
    assert out[0]["url"] == "http://naver"


def test_call_swallows_request_exception(monkeypatch):
    def boom(*a, **k):
        raise naver_search.requests.RequestException("network down")

    monkeypatch.setattr(naver_search.requests, "get", boom)
    nv = NaverNewsSearch(client_id="cid", client_secret="csec")
    assert nv("q") == []


def test_call_non_200_returns_empty(monkeypatch):
    class _R:
        status_code = 500

        def json(self):
            raise AssertionError("should not parse on non-200")

    monkeypatch.setattr(naver_search.requests, "get", lambda *a, **k: _R())
    nv = NaverNewsSearch(client_id="cid", client_secret="csec")
    assert nv("q") == []
