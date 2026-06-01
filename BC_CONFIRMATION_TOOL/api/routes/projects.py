from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, delete
from src.infrastructure.db.repository import get_engine, create_project
from src.infrastructure.db.models import Project, FileAsset

router = APIRouter(prefix="/api/projects", tags=["projects"])

# 허용 파일 종류 + 종류별 확장자 화이트리스트.
# 원장·CS·전기CS는 엑셀, 회신본은 PDF, 월보·담보·보증은 엑셀/PDF 혼용 가능.
_EXCEL = {".xlsx", ".xls"}
_PDF = {".pdf"}
_KIND_EXT: dict[str, set[str]] = {
    "gl": _EXCEL, "cs": _EXCEL, "prior_cs": _EXCEL,
    "union": _EXCEL | _PDF, "collateral": _EXCEL | _PDF, "guarantee": _EXCEL | _PDF,
    "response": _PDF,
}
# 회신본은 BC-N별 여러 파일을 누적, 그 외 종류는 프로젝트당 1개(재업로드=교체).
_MULTI_KINDS = {"response"}
_MAX_BYTES = 300 * 1024 * 1024  # 300MB (보조부원장 대용량 대비)


def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s


class CreateProjectIn(BaseModel):
    name: str
    fiscal_date: str


@router.post("")
def create(payload: CreateProjectIn, s: Session = Depends(_session)):
    p = create_project(s, payload.name, payload.fiscal_date)
    return {"id": p.id, "name": p.name, "fiscal_date": p.fiscal_date}


UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "data" / "uploads"


@router.post("/{project_id}/upload/{kind}")
def upload(project_id: int, kind: str, file: UploadFile = File(...),
           s: Session = Depends(_session)):
    # (1) 종류 검증 — path param 화이트리스트(임의 kind로 경로 조작 차단)
    if kind not in _KIND_EXT:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 파일 종류: {kind}")
    # (2) 프로젝트 존재 검증 — 고아 FileAsset 방지
    if s.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail=f"프로젝트 {project_id} 없음")
    # (3) 파일명 정제 — 경로 traversal 차단(basename만)
    raw_name = file.filename or "upload"
    safe_name = Path(raw_name).name
    ext = Path(safe_name).suffix.lower()
    if ext not in _KIND_EXT[kind]:
        allowed = ", ".join(sorted(_KIND_EXT[kind]))
        raise HTTPException(status_code=400,
                            detail=f"{kind}는 {allowed}만 허용 (받음: {ext or '확장자없음'})")

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_ROOT / f"p{project_id}_{kind}_{safe_name}"

    # (4) 크기 제한 스트리밍 쓰기 — 전체 메모리 적재(OOM) 방지
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413,
                                        detail=f"파일이 너무 큼(> {_MAX_BYTES // (1024*1024)}MB)")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {e}")

    # (5) 멱등 upsert — 단일 종류는 기존 FileAsset 교체, 회신본은 동일 파일명만 교체
    if kind in _MULTI_KINDS:
        existing = s.exec(
            select(FileAsset).where(
                FileAsset.project_id == project_id,
                FileAsset.kind == kind,
                FileAsset.original_name == safe_name,
            )
        ).first()
        if existing:
            existing.stored_path = str(dest)
            asset = existing
            s.add(asset)
        else:
            asset = FileAsset(project_id=project_id, kind=kind,
                              original_name=safe_name, stored_path=str(dest))
            s.add(asset)
    else:
        # 단일 종류: 같은 (project, kind) 기존 행 + 다른 경로 파일 제거 후 새로 등록
        olds = s.exec(
            select(FileAsset).where(
                FileAsset.project_id == project_id, FileAsset.kind == kind
            )
        ).all()
        for old in olds:
            if old.stored_path and old.stored_path != str(dest):
                Path(old.stored_path).unlink(missing_ok=True)
        s.exec(delete(FileAsset).where(
            FileAsset.project_id == project_id, FileAsset.kind == kind
        ))
        asset = FileAsset(project_id=project_id, kind=kind,
                          original_name=safe_name, stored_path=str(dest))
        s.add(asset)

    s.commit()
    s.refresh(asset)
    return {"id": asset.id, "stored_path": str(dest)}
