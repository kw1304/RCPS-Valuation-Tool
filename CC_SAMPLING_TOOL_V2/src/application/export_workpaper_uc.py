"""ExportWorkpaperUC — state 집계 → 통합 조서 xlsx."""
from __future__ import annotations
from src.domain.entities import Kind
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
    ConfirmationRepo, AltProcRepo, ProjectionRepo,
)
from src.infrastructure.excel_writer.workpaper import build_workpaper


class ExportWorkpaperUC:
    def __init__(self, session):
        self.s = session

    def build(self, project_id: int, template_name: str) -> bytes:
        state = self._collect_state(project_id)
        return build_workpaper(template_name, state)

    def _collect_state(self, pid: int) -> dict:
        proj = ProjectRepo(self.s).get(pid)
        out = {
            "project": {
                "client": proj.client,
                "period_end": proj.period_end.isoformat(),
                "base_ccy": proj.base_ccy,
                "materiality": proj.materiality,
                "tolerable": proj.tolerable,
            },
            "populations": {}, "samples": {},
            "confirmations": {}, "alternatives": {}, "projection": {},
        }
        acc_repo = AccountRepo(self.s)
        sample_repo = SampleRepo(self.s)
        conf_repo = ConfirmationRepo(self.s)
        alt_repo = AltProcRepo(self.s)
        proj_repo = ProjectionRepo(self.s)
        for k in (Kind.AR, Kind.AP):
            accs = acc_repo.list_by_project_kind(pid, k)
            out["populations"][k.value] = {
                "count": len(accs),
                "total_krw": sum(abs(a.balance_krw) for a in accs),
            }
            sample = sample_repo.list_by_project_kind(pid, k)
            out["samples"][k.value] = {
                "count": len(sample),
                "total_krw": sum(abs(a.balance_krw) for a, _ in sample),
                "items": [
                    {
                        "party_id": a.party_id, "name": a.name,
                        "gl_account": a.gl_account,
                        "balance_krw": a.balance_krw, "ccy": a.ccy,
                        "selection_reason": r.value,
                        "is_related_party": a.is_related_party,
                        "is_bad_debt": a.is_bad_debt,
                    }
                    for a, r in sample
                ],
            }
            confs = conf_repo.list_by_project_kind(pid, k)
            out["confirmations"][k.value] = [
                {
                    "party_id": c.party_id, "name": c.name,
                    "expected": c.expected, "confirmed": c.confirmed,
                    "diff": c.diff, "diff_reason": c.diff_reason,
                    "verdict": c.verdict.value if c.verdict else None,
                    "status": c.status.value,
                    "pdf_path": c.pdf_path,
                }
                for c in confs
            ]
            out["alternatives"][k.value] = alt_repo.list_by_project_kind(pid, k)
            out["projection"][k.value] = proj_repo.get_latest(pid, k)
        return out
