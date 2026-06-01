from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(title="BC Confirmation Tool")
# CORS: 와일드카드(*) 대신 로컬·WAT 셸(8765) + Tailscale(*.ts.net)만 허용.
# 자체 프론트는 동일 origin(8766)이라 CORS 불필요하나, WAT 임베드/원격 접근 대비 화이트리스트.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8766", "http://localhost:8766",
        "http://127.0.0.1:8765", "http://localhost:8765",
    ],
    allow_origin_regex=r"https://[\w.-]+\.ts\.net(:\d+)?",
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    # DB 연결까지 확인 — 부팅 자동시작 환경에서 DB 깨짐을 조기 감지.
    try:
        from sqlalchemy import text
        from src.infrastructure.db.repository import get_engine
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return JSONResponse(status_code=503,
                            content={"status": "degraded", "db": str(e)})

from api.routes import projects as projects_route
from api.routes import sampling as sampling_route
from api.routes import crosscheck as crosscheck_route
from api.routes import response as response_route
from api.routes import workpaper as workpaper_route
app.include_router(projects_route.router)
app.include_router(sampling_route.router)
app.include_router(crosscheck_route.router)
app.include_router(response_route.router)
app.include_router(workpaper_route.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
