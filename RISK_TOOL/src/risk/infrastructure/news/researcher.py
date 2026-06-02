from __future__ import annotations
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

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
        """회사명+리스크키워드 검색. 회사명이 제목에 실제 등장하는 기사만 채택
        (검색엔진의 느슨한 매칭으로 무관기사가 섞이는 노이즈 차단).

        16개 키워드 검색은 ThreadPoolExecutor로 병렬(네트워크 I/O 대기 단축).
        결과 병합은 키워드 순서대로 처리해 dedup·채택을 결정론적으로 유지.
        """
        core = _core_name(company)

        def _search(kw):
            q = f"{company} {kw}" + (f" {industry}" if industry else "")
            try:
                return self.search_fn(q) or []
            except Exception:
                return []

        # 키워드 순서 보존하며 병렬 실행 (map은 입력 순서대로 결과 반환)
        with ThreadPoolExecutor(max_workers=8) as ex:
            per_kw = list(ex.map(_search, RISK_KEYWORDS))

        hits: list[NewsHit] = []
        seen_urls: set[str] = set()
        for kw, results in zip(RISK_KEYWORDS, per_kw):
            kept = 0
            for r in results:
                if kept >= 2:
                    break
                title = r.get("title", "")
                url = r.get("url", "")
                # 회사명(핵심어)이 제목에 실제로 있어야 채택. 네이버는 검색어를 요약에
                # 끼워넣어 무관기사도 요약매칭되므로, 정밀도 위해 제목 기준(감사용 오탐 차단).
                if core and core not in title.replace(" ", ""):
                    continue
                if url and url in seen_urls:
                    continue
                seen_urls.add(url)
                hits.append(NewsHit(title=title, date=r.get("date", ""),
                                    summary=r.get("snippet", ""), url=url, keyword=kw))
                kept += 1
        return hits


def _core_name(company: str) -> str:
    """회사명에서 법인격·공백 제거해 핵심 상호만. '(주)삼성전자' → '삼성전자'."""
    import re
    c = re.sub(r"\(?주\)?|\(?유\)?|주식회사|㈜|\s", "", company or "")
    return c.strip()
