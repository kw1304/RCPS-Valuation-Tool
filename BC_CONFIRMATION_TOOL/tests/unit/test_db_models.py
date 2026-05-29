import pytest
from sqlmodel import Session, SQLModel, create_engine
from src.infrastructure.db.models import Project, Counterparty

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng

def test_create_project_and_counterparty(engine):
    with Session(engine) as s:
        p = Project(name="코스맥스비티아이", fiscal_date="2025-12-31")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Counterparty(project_id=p.id, bc_no="BC-1", canonical_name="국민은행")
        s.add(c)
        s.commit()
        s.refresh(c)
        assert c.id is not None
        assert c.canonical_name == "국민은행"


def test_extracted_record_manual_review_flag():
    from src.infrastructure.db.models import ExtractedRecord
    r = ExtractedRecord(project_id=1, counterparty_id=1, ac_section="AC2",
                        payload_json="{}", needs_manual_review=True, form_family="unknown")
    assert r.needs_manual_review is True
    assert r.form_family == "unknown"
