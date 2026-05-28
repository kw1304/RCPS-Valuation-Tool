import pytest
from datetime import date
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import (
    Base, ProjectRow, AccountRow, SampleRow, ConfirmationRow,
)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session(engine)
    s = SessionFactory()
    yield s
    s.close()


def test_create_project(session):
    p = ProjectRow(client="ACME", period_end=date(2025, 12, 31),
                   base_ccy="KRW", materiality=500_000_000,
                   tolerable=250_000_000)
    session.add(p)
    session.commit()
    assert p.id is not None


def test_account_belongs_to_project(session):
    p = ProjectRow(client="ACME", period_end=date(2025, 12, 31),
                   base_ccy="KRW", materiality=1, tolerable=1)
    session.add(p)
    session.commit()
    a = AccountRow(project_id=p.id, kind="AR", party_id="P1",
                   name="갑", gl_account="11200",
                   balance_orig=1000, ccy="USD", fx_rate=1300,
                   balance_krw=1_300_000)
    session.add(a)
    session.commit()
    assert a.id is not None
    assert a.project_id == p.id


def test_kind_constraint_only_ar_ap(session):
    p = ProjectRow(client="X", period_end=date(2025, 12, 31),
                   base_ccy="KRW", materiality=1, tolerable=1)
    session.add(p)
    session.commit()
    from sqlalchemy.exc import IntegrityError
    a = AccountRow(project_id=p.id, kind="BAD", party_id="P1",
                   name="x", gl_account="x", balance_orig=0,
                   ccy="KRW", fx_rate=1, balance_krw=0)
    session.add(a)
    with pytest.raises((IntegrityError, ValueError)):
        session.commit()
