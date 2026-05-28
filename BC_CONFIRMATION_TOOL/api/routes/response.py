from fastapi import APIRouter, Depends
from sqlmodel import Session
from src.application.parse_response_uc import parse_responses
from src.infrastructure.db.repository import get_engine

router = APIRouter(prefix="/api/projects", tags=["response"])


def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s


@router.post("/{project_id}/response/parse")
def parse(project_id: int, s: Session = Depends(_session)):
    return parse_responses(s, project_id)
