from risk.infrastructure.news.researcher import NewsResearcher


def test_research_collects_hits():
    # 회사명이 제목에 있고 URL이 매번 달라야 채택·중복제거 통과 (실데이터 모사)
    n = {"i": 0}

    def fake(q):
        n["i"] += 1
        return [{"title": q + " 기사", "url": f"http://x/{n['i']}",
                 "snippet": "s", "date": "2026-01"}]
    r = NewsResearcher(fake)
    hits = r.research("ABC회사")
    assert len(hits) >= 16  # 키워드당 최소 1 (회사명 포함)
    assert all("ABC회사" in h.title for h in hits)


def test_research_filters_unrelated_hits():
    # 회사명 없는 기사는 노이즈로 제외
    def fake(q):
        return [{"title": "전혀 무관한 정치 뉴스", "url": "http://u", "snippet": "x", "date": ""}]
    r = NewsResearcher(fake)
    assert r.research("ABC회사") == []


def test_research_dedupes_same_url():
    def fake(q):
        return [{"title": "ABC회사 소송 기사", "url": "http://same", "snippet": "", "date": ""}]
    r = NewsResearcher(fake)
    hits = r.research("ABC회사")
    assert len(hits) == 1  # 동일 URL은 1건만


def test_research_swallows_search_fn_exception():
    def boom(q):
        raise RuntimeError("network down")
    r = NewsResearcher(boom)
    assert r.research("ABC회사") == []


def test_research_empty_results():
    def empty(q):
        return []
    r = NewsResearcher(empty)
    assert r.research("ABC회사") == []
