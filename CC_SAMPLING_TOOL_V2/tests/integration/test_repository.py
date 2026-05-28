import pytest
from datetime import date
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session(engine)
    s = Session()
    yield s
    s.close()


def test_project_create_get(session):
    repo = ProjectRepo(session)
    pid = repo.create(client="ACME", period_end=date(2025, 12, 31),
                      base_ccy="KRW", materiality=500_000_000,
                      tolerable=250_000_000)
    assert pid > 0
    p = repo.get(pid)
    assert p.client == "ACME"
    assert p.tolerable == 250_000_000


def test_account_bulk_insert(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    accs = [
        Account(party_id=f"P{i}", name=f"갑{i}", gl_account="11200",
                balance_orig=1000 * (i + 1), ccy="KRW", fx_rate=1.0,
                balance_krw=1000 * (i + 1))
        for i in range(5)
    ]
    acc_repo.bulk_insert(project_id=pid, kind=Kind.AR, accounts=accs)
    fetched = acc_repo.list_by_project_kind(pid, Kind.AR)
    assert len(fetched) == 5
    assert fetched[0].party_id == "P0"


def test_account_split_by_kind(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    ar = [Account(party_id="AR1", name="ar", gl_account="x",
                  balance_orig=100, ccy="KRW", fx_rate=1.0, balance_krw=100)]
    ap = [Account(party_id="AP1", name="ap", gl_account="x",
                  balance_orig=200, ccy="KRW", fx_rate=1.0, balance_krw=200)]
    acc_repo.bulk_insert(pid, Kind.AR, ar)
    acc_repo.bulk_insert(pid, Kind.AP, ap)
    assert len(acc_repo.list_by_project_kind(pid, Kind.AR)) == 1
    assert len(acc_repo.list_by_project_kind(pid, Kind.AP)) == 1


def test_sample_persist(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    acc_repo.bulk_insert(pid, Kind.AR, [acc])
    accs = acc_repo.list_by_project_kind(pid, Kind.AR)

    sample_repo = SampleRepo(session)
    sample_repo.persist(
        project_id=pid, kind=Kind.AR,
        selections=[(accs[0], SelectionReason.FORCED_RP)],
    )
    rows = sample_repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0][1] == SelectionReason.FORCED_RP


def test_sample_replace_on_redesign(session):
    """재설계 시 기존 sample 삭제 후 신규 insert."""
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    acc = Account(party_id="P1", name="x", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    acc_repo.bulk_insert(pid, Kind.AR, [acc])
    accs = acc_repo.list_by_project_kind(pid, Kind.AR)

    sample_repo = SampleRepo(session)
    sample_repo.persist(pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    sample_repo.persist(pid, Kind.AR, [(accs[0], SelectionReason.FORCED_KEY)])
    rows = sample_repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0][1] == SelectionReason.FORCED_KEY


def test_project_get_missing_raises(session):
    repo = ProjectRepo(session)
    with pytest.raises(KeyError):
        repo.get(99999)


def test_sample_persist_unknown_party_raises(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    # acc은 DB에 없음
    ghost = Account(party_id="GHOST", name="g", gl_account="x",
                    balance_orig=100, ccy="KRW", fx_rate=1.0, balance_krw=100)
    sample_repo = SampleRepo(session)
    with pytest.raises(ValueError):
        sample_repo.persist(pid, Kind.AR, [(ghost, SelectionReason.FORCED_RP)])


def test_account_replace_all(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    accs1 = [Account(party_id=f"P{i}", name=f"갑{i}", gl_account="x",
                     balance_orig=100, ccy="KRW", fx_rate=1.0, balance_krw=100)
             for i in range(3)]
    acc_repo.bulk_insert(pid, Kind.AR, accs1)
    accs2 = [Account(party_id="Q1", name="을", gl_account="x",
                     balance_orig=200, ccy="KRW", fx_rate=1.0, balance_krw=200)]
    acc_repo.replace_all(pid, Kind.AR, accs2)
    fetched = acc_repo.list_by_project_kind(pid, Kind.AR)
    assert len(fetched) == 1
    assert fetched[0].party_id == "Q1"
