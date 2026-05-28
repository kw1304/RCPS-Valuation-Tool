"""Dashboard state — 좌측패널·테이블에 필요한 모든 정보 한방."""
from __future__ import annotations
from flask import Blueprint, jsonify, g
from src.domain.entities import Kind
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
    ConfirmationRepo, AltProcRepo, ProjectionRepo,
)


bp = Blueprint("state", __name__, url_prefix="/api/projects")


@bp.get("/<int:pid>/state")
def project_state(pid: int):
    proj_repo = ProjectRepo(g.session)
    acc_repo = AccountRepo(g.session)
    sample_repo = SampleRepo(g.session)
    conf_repo = ConfirmationRepo(g.session)
    alt_repo = AltProcRepo(g.session)
    proj_repo_e = ProjectionRepo(g.session)
    try:
        p = proj_repo.get(pid)
    except KeyError:
        return jsonify({"error": "not found"}), 404

    out = {
        "project": {
            "id": p.id, "client": p.client,
            "period_end": p.period_end.isoformat(),
            "base_ccy": p.base_ccy,
            "materiality": p.materiality, "tolerable": p.tolerable,
        },
        "populations": {}, "samples": {},
        "confirmations": {}, "alternatives": {}, "projection": {},
    }
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
        out["projection"][k.value] = proj_repo_e.get_latest(pid, k)
    return jsonify(out)
