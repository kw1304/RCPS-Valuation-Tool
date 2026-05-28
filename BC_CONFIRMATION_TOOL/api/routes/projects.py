from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File
from sqlmodel import Session
from src.infrastructure.db.repository import get_engine, create_project
from src.infrastructure.db.models import Project, FileAsset

router = APIRouter(prefix="/api/projects", tags=["projects"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("")
def create(payload: dict, s: Session = Depends(_session)):
    p = create_project(s, payload["name"], payload["fiscal_date"])
    return {"id": p.id, "name": p.name, "fiscal_date": p.fiscal_date}

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "data" / "uploads"

@router.post("/{project_id}/upload/{kind}")
def upload(project_id: int, kind: str, file: UploadFile = File(...), s: Session = Depends(_session)):
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_ROOT / f"p{project_id}_{kind}_{file.filename}"
    dest.write_bytes(file.file.read())
    asset = FileAsset(project_id=project_id, kind=kind, original_name=file.filename, stored_path=str(dest))
    s.add(asset); s.commit(); s.refresh(asset)
    return {"id": asset.id, "stored_path": str(dest)}
