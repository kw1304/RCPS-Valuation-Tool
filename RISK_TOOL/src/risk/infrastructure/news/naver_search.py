"""네이버 뉴스 검색 OpenAPI search_fn. 키 없으면 None 반환(호출측 degrade)."""
from __future__ import annotations
import os
import requests

_API_URL = "https://openapi.naver.com/v1/search/news.json"


def strip_html(s: str) -> str:
    """네이버가 매칭어를 <b>로 감싸므로 태그 제거 + 기본 HTML 엔티티 unescape."""
    if not s:
        return ""
    s = s.replace("<b>", "").replace("</b>", "")
    s = (s.replace("&quot;", '"')
          .replace("&lt;", "<")
          .replace("&gt;", ">")
          .replace("&amp;", "&"))
    return s


class NaverNewsSearch:
    def __init__(self, client_id=None, client_secret=None, timeout=10.0):
        self.client_id = client_id if client_id is not None else os.environ.get("NAVER_CLIENT_ID")
        self.client_secret = client_secret if client_secret is not None else os.environ.get("NAVER_CLIENT_SECRET")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.client_id) and bool(self.client_secret)

    def __call__(self, query: str) -> list[dict]:
        if not self.enabled:
            return []
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
        }
        params = {"query": query, "display": 5, "sort": "date"}
        try:
            resp = requests.get(_API_URL, headers=headers, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            data = resp.json()
            items = data.get("items", []) or []
        except requests.RequestException:
            return []
        except Exception:
            # JSON 파싱 등 어떤 오류도 뉴스는 degrade-safe — 절대 raise 금지
            return []
        out = []
        for it in items:
            out.append({
                "title": strip_html(it.get("title", "")),
                "url": it.get("originallink") or it.get("link", ""),
                "snippet": strip_html(it.get("description", "")),
                "date": it.get("pubDate", ""),
            })
        return out
