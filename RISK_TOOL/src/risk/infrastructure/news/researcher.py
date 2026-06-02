from __future__ import annotations
from dataclasses import dataclass

RISK_KEYWORDS = [
    "소송", "횡령", "배임", "분식회계", "적자전환", "자본잠식", "감자", "부도",
    "영업정지", "대표이사 변경", "회생", "워크아웃", "관리종목", "상장폐지",
    "세무조사", "리콜",
]


@dataclass(frozen=True)
class NewsHit:
    title: str
    date: str
    summary: str
    url: str
    keyword: str


class NewsResearcher:
    def __init__(self, search_fn):
        """search_fn(query:str) -> list[{title,url,snippet,date}]. application이 주입."""
        self.search_fn = search_fn

    def research(self, company: str, industry: str = "") -> list[NewsHit]:
        hits: list[NewsHit] = []
        for kw in RISK_KEYWORDS:
            q = f"{company} {kw}" + (f" {industry}" if industry else "")
            try:
                results = self.search_fn(q) or []
            except Exception:
                continue
            for r in results[:2]:
                hits.append(NewsHit(title=r.get("title", ""), date=r.get("date", ""),
                                    summary=r.get("snippet", ""), url=r.get("url", ""),
                                    keyword=kw))
        return hits
