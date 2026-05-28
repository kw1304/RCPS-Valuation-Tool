"""SendListUC — 표본 → 발송명단 Excel."""
from __future__ import annotations
from src.domain.entities import Kind
from src.infrastructure.db.repository import ProjectRepo, SampleRepo
from src.infrastructure.excel_writer.sendlist import build_sendlist


class SendListUC:
    def __init__(self, session):
        self.s = session

    def build(self, project_id: int) -> bytes:
        proj = ProjectRepo(self.s).get(project_id)
        sample_repo = SampleRepo(self.s)
        samples = {
            Kind.AR: sample_repo.list_by_project_kind(project_id, Kind.AR),
            Kind.AP: sample_repo.list_by_project_kind(project_id, Kind.AP),
        }
        return build_sendlist(
            client_name=proj.client,
            period_end=proj.period_end.isoformat(),
            samples=samples,
        )
