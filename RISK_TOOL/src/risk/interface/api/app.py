from __future__ import annotations
import os, io
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pathlib, tempfile

from risk.infrastructure.dart.client import DartClient
from risk.infrastructure.dart.risk_extractor import RiskExtractor
from risk.infrastructure.news.researcher import NewsResearcher
from risk.infrastructure.llm.commenter import Commenter
from risk.application.assess_risk_uc import AssessRiskUseCase
from risk.infrastructure.excel.workpaper import build_workpaper
from dataclasses import asdict

app = FastAPI(title="감사전 리스크 확인 툴")
_FRONT = pathlib.Path(__file__).parent / "frontend"


def _build_uc():
    client = DartClient(api_key=os.environ.get("DART_API_KEY", ""))
    extractor = RiskExtractor(client)
    # WebSearch는 런타임 도구 → 서버에선 None search_fn(축4 degrade) 기본
    news = NewsResearcher(search_fn=lambda q: [])
    try:
        import anthropic
        llm = Commenter(anthropic.Anthropic()) if os.environ.get("ANTHROPIC_API_KEY") else Commenter(None)
    except Exception:
        llm = Commenter(None)
    return AssessRiskUseCase(extractor, client.find_corp_code, news, llm)


class AssessReq(BaseModel):
    company: str
    end_year: int


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/assess")
def assess(req: AssessReq):
    uc = _build_uc()
    res = uc.run(req.company, req.end_year)
    return JSONResponse({
        "company": res.company, "error": res.error,
        "grade": asdict(res.grade) if res.grade else None,
        "materiality": asdict(res.materiality) if res.materiality else None,
        "signals": [asdict(s) for s in res.signals],
        "comments": res.comments,
        "years": [asdict(y) for y in res.years],
        "news": [vars(h) for h in res.news],
    })


@app.post("/api/export")
def export(req: AssessReq):
    uc = _build_uc()
    res = uc.run(req.company, req.end_year)
    tmp = pathlib.Path(tempfile.gettempdir()) / f"risk_{req.company}_{req.end_year}.xlsx"
    build_workpaper(res, str(tmp))
    return FileResponse(str(tmp), filename=tmp.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


app.mount("/", StaticFiles(directory=str(_FRONT), html=True), name="static")
