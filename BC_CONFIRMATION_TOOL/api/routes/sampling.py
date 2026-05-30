from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from src.application.sampling_uc import run_sampling
from src.infrastructure.db.models import FileAsset, Counterparty
from src.infrastructure.db.repository import get_engine, list_counterparties, delete_counterparty

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
    # 제거 버튼용으로 거래처 DB id를 (canonical, branch) 기준 매핑해 같이 내려줌
    id_map = {(c.canonical_name, c.branch): c.id for c in list_counterparties(s, project_id)}
    return {
        "parties": [
            {
                "id": id_map.get((p.party.canonical, p.party.branch)),
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


@router.delete("/{project_id}/counterparty/{cp_id}")
def remove_counterparty(project_id: int, cp_id: int, s: Session = Depends(_session)):
    """샘플링된 거래처 1건 제거 (감사인 판단으로 조회대상 제외)."""
    ok = delete_counterparty(s, project_id, cp_id)
    if not ok:
        raise HTTPException(404, "counterparty not found")
    remaining = len(list_counterparties(s, project_id))
    return {"removed": cp_id, "remaining": remaining}
