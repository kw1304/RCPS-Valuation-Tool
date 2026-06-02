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
    disclosures: list = field(default_factory=list)
    events: list = field(default_factory=list)
    error: str = ""


# 축4 DART 공시이벤트 — 리스크 관련 보고서명 키워드 (report_nm 부분일치)
_DISCLOSURE_KEYWORDS = ["감자", "소송", "횡령", "배임", "채무보증", "부도",
                        "영업양수도", "주요사항", "증자", "합병", "감사의견", "계속기업"]


class AssessRiskUseCase:
    def __init__(self, extractor, corp_resolver, news, commenter, disclosure_fetcher=None):
        self.extractor = extractor
        self.corp_resolver = corp_resolver  # name -> {corp_code,...}|None
        self.news = news
        self.commenter = commenter
        self.disclosure_fetcher = disclosure_fetcher  # corp_code -> list[dict]|None

    def run(self, company: str, end_year: int,
            materiality_opts: dict | None = None) -> RiskResult:
        # 외부 DART I/O — 키 미설정·네트워크 오류는 우아한 에러로 환원(500 금지)
        try:
            corp = self.corp_resolver(company)
        except Exception as e:  # DartError 등
            return RiskResult(company, [], None,
                              error=f"DART 조회 실패: {e} — DART_API_KEY 확인 또는 수기입력.")
        if not corp:
            return RiskResult(company, [], None,
                              error="DART에서 회사를 찾지 못했습니다. 회사명 확인 또는 수기입력.")
        try:
            years = self.extractor.fetch(corp["corp_code"], end_year)
        except Exception as e:
            return RiskResult(company, [], None,
                              error=f"DART 재무자료 조회 실패: {e} — 과거실적 수기입력 필요.")
        if not years:
            return RiskResult(company, [], None,
                              error="DART 재무자료 없음 — 과거실적 수기입력 필요.")
        try:
            pm = performance_materiality(years[-1], **(materiality_opts or {}))
        except ValueError as e:
            return RiskResult(company, years, None, error=str(e))
        signals = evaluate_axes(years, pm)
        grade = overall_grade(signals)
        # 보조기능(AI 코멘트·뉴스)은 실패해도 핵심 신호 결과를 막지 않음(degrade)
        try:
            comments = self.commenter.comment_signals(company, signals)
        except Exception:
            comments = {}
        try:
            news = self.news.research(company)
        except Exception:
            news = []
        # 축4 DART 공시이벤트 (결정론적). 실패해도 핵심 신호 막지 않음(degrade)
        disclosures: list = []
        if self.disclosure_fetcher:
            try:
                raw = self.disclosure_fetcher(corp["corp_code"]) or []
                disclosures = [d for d in raw
                               if any(k in (d.get("report_nm") or "") for k in _DISCLOSURE_KEYWORDS)]
            except Exception:
                disclosures = []
        # 뉴스·공시 AI 구조화 (degrade []). 핵심 신호 결과를 막지 않음.
        try:
            events = self.commenter.structure_events(company, news, disclosures)
        except Exception:
            events = []
        return RiskResult(company, years, pm, signals, grade, comments,
                          news, disclosures, events)
