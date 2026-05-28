import pytest
from pathlib import Path
from datetime import date
from src.application.match_response_uc import MatchResponseUC, MatchResult
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)


def _make_pdf(path, text):
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    except ImportError:
        pytest.skip("reportlab not installed")
    # Korean CID font 등록 — default Helvetica는 한글 글리프 미지원
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    except Exception:
        pass
    c = canvas.Canvas(str(path))
    c.setFont("HYSMyeongJo-Medium", 12)
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_sample(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="고객사001", gl_account="11200",
                  balance_orig=1_500_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_500_000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(
        pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    return pid


def test_match_response_persists_confirmation(session, project_with_sample, tmp_path):
    # filename 기반 매칭 — 거래처명(고객사001) 포함 파일명 필수.
    pdf = tmp_path / "고객사001_conf.pdf"
    _make_pdf(pdf, "조회처: 고객사001\n잔액: 1,500,000원")
    uc = MatchResponseUC(session)
    result = uc.match_one(pid=project_with_sample, kind=Kind.AR, pdf_path=pdf)
    assert isinstance(result, MatchResult)
    assert result.matched_party == "P1"
    assert result.confirmed == 1_500_000
    assert result.verdict == Verdict.MATCH

    rows = ConfirmationRepo(session).list_by_project_kind(
        project_with_sample, Kind.AR)
    assert len(rows) == 1
    assert rows[0].verdict == Verdict.MATCH


def test_match_response_discrepancy(session, project_with_sample, tmp_path):
    # filename 기반 매칭 — 거래처명(고객사001) 포함 파일명 필수.
    pdf = tmp_path / "고객사001_conf.pdf"
    _make_pdf(pdf, "조회처: 고객사001\n잔액: 1,100,000원")
    uc = MatchResponseUC(session)
    r = uc.match_one(project_with_sample, Kind.AR, pdf)
    assert r.verdict == Verdict.DISCREPANCY


def test_match_response_extract_failure(session, project_with_sample, tmp_path):
    pdf = tmp_path / "blank.pdf"
    _make_pdf(pdf, "")
    uc = MatchResponseUC(session)
    r = uc.match_one(project_with_sample, Kind.AR, pdf)
    assert r.confirmed is None
    assert r.verdict == Verdict.NO_RESPONSE
