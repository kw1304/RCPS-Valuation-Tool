from __future__ import annotations
from dataclasses import dataclass, field
from risk.domain.financial import FinancialYear
from risk.domain.materiality import performance_materiality, Materiality
from risk.domain.thresholds import evaluate_axes, Signal
from risk.domain.risk_grade import overall_grade, RiskGrade


@dataclass
class RiskResult:
    company: str
    years: list[FinancialYear]
    materiality: Materiality | None
    signals: list[Signal] = field(default_factory=list)
    grade: RiskGrade | None = None
    comments: dict[str, str] = field(default_factory=dict)
    news: list = field(default_factory=list)
    error: str = ""


class AssessRiskUseCase:
    def __init__(self, extractor, corp_resolver, news, commenter):
        self.extractor = extractor
        self.corp_resolver = corp_resolver  # name -> {corp_code,...}|None
        self.news = news
        self.commenter = commenter

    def run(self, company: str, end_year: int) -> RiskResult:
        corp = self.corp_resolver(company)
        if not corp:
            return RiskResult(company, [], None,
                              error="DART에서 회사를 찾지 못했습니다. 회사명 확인 또는 수기입력.")
        years = self.extractor.fetch(corp["corp_code"], end_year)
        if not years:
            return RiskResult(company, [], None,
                              error="DART 재무자료 없음 — 과거실적 수기입력 필요.")
        try:
            pm = performance_materiality(years[-1])
        except ValueError as e:
            return RiskResult(company, years, None, error=str(e))
        signals = evaluate_axes(years, pm)
        grade = overall_grade(signals)
        comments = self.commenter.comment_signals(company, signals)
        news = self.news.research(company)
        return RiskResult(company, years, pm, signals, grade, comments, news)
