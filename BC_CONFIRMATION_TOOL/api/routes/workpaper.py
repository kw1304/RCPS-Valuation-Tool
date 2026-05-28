from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session
from src.application.export_4150_uc import export_4150
from src.infrastructure.db.repository import get_engine

router = APIRouter(prefix="/api/projects", tags=["workpaper"])


def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s


@router.post("/{project_id}/workpaper/export")
def export(project_id: int, s: Session = Depends(_session)):
    path = export_4150(s, project_id)
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
