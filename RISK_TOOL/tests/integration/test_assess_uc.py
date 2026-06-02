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
