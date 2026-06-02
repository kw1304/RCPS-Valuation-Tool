from risk.infrastructure.news.researcher import NewsResearcher


def test_research_collects_hits():
    def fake(q):
        return [{"title": q, "url": "http://x", "snippet": "s", "date": "2026-01"}]
    r = NewsResearcher(fake)
    hits = r.research("ABC회사")
    assert len(hits) >= 16  # 키워드당 최소 1
    assert all(h.url == "http://x" for h in hits)


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
