from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from src.application.sampling_uc import run_sampling
from src.infrastructure.db.models import FileAsset, Counterparty
from src.infrastructure.db.repository import get_engine, list_counterparties

router = APIRouter(prefix="/api/projects", tags=["sampling"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("/{project_id}/sampling/run")
def run(project_id: int, s: Session = Depends(_session)):
    gl = s.exec(select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.kind == "gl")).first()
    if not gl:
        raise HTTPException(400, "G/L not uploaded")
    parties = run_sampling(s, project_id, Path(gl.stored_path))
    return {
        "parties": [
            {
                "canonical": p.party.canonical,
                "branch": p.party.branch,
                "is_foreign": p.party.is_foreign,
                "bs_amount": p.bs_amount,
                "pl_amount": p.pl_amount,
                "bs_accounts": sorted(p.bs_accounts),
                "pl_accounts": sorted(p.pl_accounts),
                "row_count": p.row_count,
                "confidence": p.confidence,
            } for p in parties
        ]
    }
