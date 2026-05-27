"""SQLite 영속화 레이어 유닛 테스트

in-memory SQLite DB 를 사용하므로 실제 data/projects.db 에 영향 없음.
"""
import sys
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.infrastructure.persistence.models import Base
from src.infrastructure.persistence.repos import (
    ProjectRepository,
    WorkpaperRepository,
    ArtifactRepository,
)


@pytest.fixture
def session():
    """각 테스트마다 독립 in-memory DB."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    yield s
    s.close()


# ── Project CRUD ────────────────────────────────────────────
def test_project_create(session):
    repo = ProjectRepository(session)
    proj = repo.create(
        company_name="테스트회사",
        period_end="2025-12-31",
        kind="receivable",
        audit_firm="삼일회계법인",
        created_by_email="tester@example.com",
    )
    session.flush()
    assert proj.id is not None
    assert proj.company_name == "테스트회사"
    assert proj.status == "active"


def test_project_list(session):
    repo = ProjectRepository(session)
    repo.create(company_name="A사", period_end="2025-12-31")
    repo.create(company_name="B사", period_end="2025-12-31")
    session.flush()
    projects = repo.list_all()
    assert len(projects) == 2


def test_project_update(session):
    repo = ProjectRepository(session)
    proj = repo.create(company_name="구이름", period_end="2025-12-31")
    session.flush()
    updated = repo.update(proj.id, company_name="새이름")
    assert updated.company_name == "새이름"


def test_project_soft_delete(session):
    repo = ProjectRepository(session)
    proj = repo.create(company_name="삭제예정", period_end="2025-12-31")
    session.flush()
    ok = repo.soft_delete(proj.id)
    assert ok
    # soft delete 후 list_all 에서 제외
    active = repo.list_all()
    assert all(p.id != proj.id for p in active)


# ── Workpaper CRUD ──────────────────────────────────────────
def test_workpaper_get_or_create(session):
    repo = ProjectRepository(session)
    proj = repo.create(company_name="채권테스트", period_end="2025-12-31")
    session.flush()

    wp_repo = WorkpaperRepository(session)
    wp1 = wp_repo.get_or_create(proj.id, "receivable")
    wp2 = wp_repo.get_or_create(proj.id, "receivable")
    assert wp1.id == wp2.id  # 동일 워크페이퍼 반환


def test_workpaper_save_sampling_result(session):
    repo = ProjectRepository(session)
    proj = repo.create(company_name="결과저장", period_end="2025-12-31")
    session.flush()

    wp_repo = WorkpaperRepository(session)
    wp = wp_repo.get_or_create(proj.id, "receivable")
    wp_repo.save_sampling_result(
        wp.id,
        params_dict={"kind": "receivable", "pm": 1_000_000},
        result_dict={"final_sample_size": 5},
    )
    session.flush()

    loaded = wp_repo.get(wp.id)
    assert loaded.step1_completed_at is not None
    assert "receivable" in loaded.sampling_params


# ── AuditTrail 자동 기록 ─────────────────────────────────────
def test_audit_trail_auto_create(session):
    repo = ProjectRepository(session)
    proj = repo.create(company_name="감사추적", period_end="2025-12-31", created_by_email="auditor@firm.com")
    session.flush()

    # AuditTrail 확인
    from src.infrastructure.persistence.models import AuditTrail
    from sqlalchemy import select
    trails = list(session.execute(select(AuditTrail).where(AuditTrail.project_id == proj.id)).scalars())
    assert len(trails) >= 1
    assert trails[0].action == "create"
    assert trails[0].entity_type == "Project"
