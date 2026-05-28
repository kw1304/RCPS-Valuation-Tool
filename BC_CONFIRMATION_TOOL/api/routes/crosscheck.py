from fastapi import APIRouter, Depends
from sqlmodel import Session
from src.application.crosscheck_uc import run_crosscheck
from src.infrastructure.db.repository import get_engine

router = APIRouter(prefix="/api/projects", tags=["crosscheck"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("/{project_id}/crosscheck/run")
def run(project_id: int, s: Session = Depends(_session)):
    return run_crosscheck(s, project_id)
