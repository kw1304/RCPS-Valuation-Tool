"""Repository 계층 — 도메인과 ORM 사이 변환 담당.

각 Repository 는 SQLAlchemy Session 을 주입받아 동작.
CRUD 외 AuditTrail 자동 기록 포함.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .models import Artifact, AuditTrail, Project, Workpaper

_ROOT = Path(__file__).resolve().parents[3]  # CC_SAMPLING_TOOL/
_ARTIFACT_BASE = _ROOT / "data" / "projects"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _trail(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    project_id: str | None = None,
    before: Any = None,
    after: Any = None,
    notes: str | None = None,
    user_email: str = "",
) -> None:
    trail = AuditTrail(
        project_id=project_id,
        user_email=user_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_value=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_value=json.dumps(after, ensure_ascii=False) if after is not None else None,
        notes=notes,
    )
    session.add(trail)


class ProjectRepository:
    """Project CRUD + AuditTrail"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create(
        self,
        company_name: str,
        period_end: str,
        kind: str = "both",
        audit_firm: str = "",
        created_by_email: str = "",
    ) -> Project:
        proj = Project(
            company_name=company_name,
            audit_firm=audit_firm,
            period_end=period_end,
            kind=kind,
            status="active",
            created_by_email=created_by_email,
        )
        self._s.add(proj)
        self._s.flush()  # id 확정
        _trail(
            self._s, "create", "Project", proj.id, proj.id,
            after={"company_name": company_name, "period_end": period_end, "kind": kind},
            user_email=created_by_email,
        )
        return proj

    def get(self, project_id: str) -> Project | None:
        return self._s.get(Project, project_id)

    def list_all(self) -> list[Project]:
        from sqlalchemy import select
        stmt = (
            select(Project)
            .where(Project.status != "archived")
            .order_by(Project.updated_at.desc())
        )
        return list(self._s.execute(stmt).scalars())

    def update(
        self,
        project_id: str,
        user_email: str = "",
        **fields: Any,
    ) -> Project | None:
        proj = self.get(project_id)
        if proj is None:
            return None
        allowed = {"company_name", "audit_firm", "period_end", "kind", "status"}
        before = {k: getattr(proj, k) for k in fields if k in allowed}
        for k, v in fields.items():
            if k in allowed:
                setattr(proj, k, v)
        proj.updated_at = _now()
        _trail(
            self._s, "update", "Project", project_id, project_id,
            before=before,
            after={k: v for k, v in fields.items() if k in allowed},
            user_email=user_email,
        )
        return proj

    def soft_delete(self, project_id: str, user_email: str = "") -> bool:
        proj = self.get(project_id)
        if proj is None:
            return False
        proj.status = "archived"
        proj.updated_at = _now()
        _trail(self._s, "delete", "Project", project_id, project_id, user_email=user_email)
        return True


class WorkpaperRepository:
    """Workpaper CRUD + 단계 완료 기록"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get_or_create(self, project_id: str, kind: str) -> Workpaper:
        """프로젝트+kind 단위로 워크페이퍼 1건 보장."""
        from sqlalchemy import select
        stmt = (
            select(Workpaper)
            .where(Workpaper.project_id == project_id)
            .where(Workpaper.kind == kind)
        )
        wp = self._s.execute(stmt).scalar_one_or_none()
        if wp is None:
            wp = Workpaper(project_id=project_id, kind=kind)
            self._s.add(wp)
            self._s.flush()
        return wp

    def get(self, workpaper_id: str) -> Workpaper | None:
        return self._s.get(Workpaper, workpaper_id)

    def save_sampling_result(
        self,
        workpaper_id: str,
        params_dict: dict,
        result_dict: dict,
        user_email: str = "",
    ) -> Workpaper | None:
        wp = self.get(workpaper_id)
        if wp is None:
            return None
        wp.sampling_params = json.dumps(params_dict, ensure_ascii=False, default=str)
        wp.sampling_result = json.dumps(result_dict, ensure_ascii=False, default=str)
        wp.step1_completed_at = _now()
        wp.updated_at = _now()
        _trail(
            self._s, "run_sampling", "Workpaper", workpaper_id, wp.project_id,
            notes=f"kind={wp.kind}",
            user_email=user_email,
        )
        return wp

    def mark_step(self, workpaper_id: str, step: int) -> None:
        wp = self.get(workpaper_id)
        if wp is None:
            return
        col = f"step{step}_completed_at"
        if hasattr(wp, col):
            setattr(wp, col, _now())
        wp.updated_at = _now()


class ArtifactRepository:
    """파일 저장 + Artifact 메타 등록"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def save_file(
        self,
        project_id: str,
        kind: str,
        source_path: Path,
        filename: str,
        workpaper_id: str | None = None,
        uploaded_by_email: str = "",
    ) -> Artifact:
        art = Artifact(
            project_id=project_id,
            workpaper_id=workpaper_id,
            kind=kind,
            filename=filename,
            stored_path="",   # flush 후 id 확정되면 업데이트
            uploaded_by_email=uploaded_by_email,
        )
        self._s.add(art)
        self._s.flush()

        dest_dir = _ARTIFACT_BASE / project_id / "artifacts"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{art.id}_{filename}"
        shutil.copy2(source_path, dest_path)

        art.stored_path = str(dest_path)
        art.sha256 = _sha256(dest_path)
        art.size_bytes = dest_path.stat().st_size

        _trail(
            self._s, "create", "Artifact", art.id, project_id,
            after={"kind": kind, "filename": filename},
            user_email=uploaded_by_email,
        )
        return art

    def get(self, artifact_id: str) -> Artifact | None:
        return self._s.get(Artifact, artifact_id)

    def list_by_project(self, project_id: str) -> list[Artifact]:
        from sqlalchemy import select
        stmt = select(Artifact).where(Artifact.project_id == project_id)
        return list(self._s.execute(stmt).scalars())
