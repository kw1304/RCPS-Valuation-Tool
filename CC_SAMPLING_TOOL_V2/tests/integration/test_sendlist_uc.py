import pytest
import io
import openpyxl
from datetime import date
from src.application.send_list_uc import SendListUC
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo, AccountRepo, SampleRepo


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


def test_sendlist_uc_builds_xlsx(session):
    pid = ProjectRepo(session).create(
        client="ACME", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    acc = Account(party_id="P1", name="갑", gl_account="11200",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs[0], SelectionReason.FORCED_RP)])

    uc = SendListUC(session)
    blob = uc.build(pid)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    rows = list(wb["발송명단"].iter_rows(values_only=True))
    body = [r for r in rows if r and r[0] in ("AR", "AP")]
    assert len(body) == 1


def test_sendlist_marks_sent_at(session):
    from src.infrastructure.db.repository import ConfirmationRepo
    from src.infrastructure.db.models import ConfirmationRow
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs[0], SelectionReason.FORCED_RP)])
    SendListUC(session).build(pid)
    confs = ConfirmationRepo(session).list_by_project_kind(pid, Kind.AR)
    assert len(confs) == 1
    row = session.query(ConfirmationRow).filter_by(project_id=pid).first()
    assert row.sent_at is not None
