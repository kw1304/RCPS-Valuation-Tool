import json, pathlib
from risk.domain.financial import FinancialYear
from risk.application.assess_risk_uc import AssessRiskUseCase, RiskResult


def _years():
    raw = json.loads((pathlib.Path(__file__).parent / "fixtures/listed_5y.json").read_text("utf-8"))
    return [FinancialYear(**y) for y in raw]


def test_assess_produces_grade_and_signals():
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: _years()})(),
        corp_resolver=lambda name: {"corp_code": "0001", "corp_name": name, "stock_code": "0"},
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
    )
    res = uc.run("테스트회사", end_year=2025)
    assert isinstance(res, RiskResult)
    assert res.grade.grade in ("높음", "보통", "낮음")
    assert len(res.signals) > 0
    assert res.materiality.pm > 0


def test_assess_handles_no_financials():
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: []})(),
        corp_resolver=lambda name: {"corp_code": "0001", "corp_name": name, "stock_code": "0"},
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
    )
    res = uc.run("없는회사", end_year=2025)
    assert res.error and "수기입력" in res.error


def test_assess_handles_corp_not_found():
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: _years()})(),
        corp_resolver=lambda name: None,
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
    )
    res = uc.run("유령회사", end_year=2025)
    assert res.error and "회사" in res.error


def _raise(*a, **k):
    raise RuntimeError("DART_API_KEY 미설정")


def test_assess_corp_resolver_raises_returns_graceful_error():
    # DART 키 미설정 등 corp_resolver 예외 → 500 아닌 우아한 에러
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: _years()})(),
        corp_resolver=_raise,
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
    )
    res = uc.run("키없음", end_year=2025)
    assert res.error and "DART" in res.error
    assert res.grade is None


def test_assess_degrades_when_news_and_comment_fail():
    # 보조기능(뉴스·코멘트) 예외는 핵심 신호 결과를 막지 않음
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: _years()})(),
        corp_resolver=lambda name: {"corp_code": "0001", "corp_name": name, "stock_code": "0"},
        news=type("N", (), {"research": lambda self, c, i="": (_ for _ in ()).throw(RuntimeError("net"))})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: (_ for _ in ()).throw(RuntimeError("llm"))})(),
    )
    res = uc.run("정상회사", end_year=2025)
    assert res.grade is not None and len(res.signals) > 0
    assert res.comments == {} and res.news == []


def _uc_with_fetcher(fetcher):
    return AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: _years()})(),
        corp_resolver=lambda name: {"corp_code": "0001", "corp_name": name, "stock_code": "0"},
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
        disclosure_fetcher=fetcher,
    )


def test_assess_filters_disclosures_to_risk_relevant():
    # 소송 등 리스크 보고서만 통과, 분기보고서는 제외
    fetcher = lambda cc: [
        {"rcept_dt": "20250601", "report_nm": "소송등의제기", "rcept_no": "X"},
        {"rcept_dt": "20250101", "report_nm": "분기보고서", "rcept_no": "Y"},
    ]
    res = _uc_with_fetcher(fetcher).run("정상회사", end_year=2025)
    nms = [d["report_nm"] for d in res.disclosures]
    assert "소송등의제기" in nms
    assert "분기보고서" not in nms


def test_assess_degrades_when_disclosure_fetcher_raises():
    fetcher = lambda cc: (_ for _ in ()).throw(RuntimeError("dart down"))
    res = _uc_with_fetcher(fetcher).run("정상회사", end_year=2025)
    assert res.disclosures == []
    assert res.grade is not None  # 핵심 신호는 정상
