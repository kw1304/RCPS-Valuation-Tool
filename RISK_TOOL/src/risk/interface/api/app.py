from __future__ import annotations
import os, io, re, datetime
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


def _safe_stem(name: str) -> str:
    """파일명 stem 살균 — path traversal/구분자 제거. 한글·영숫자·-만 보존."""
    safe = re.sub(r"[^\w가-힣-]", "_", name or "")
    safe = safe.strip("_")[:50]
    return safe or "company"


def _build_uc():
    client = DartClient(api_key=os.environ.get("DART_API_KEY", ""))
    extractor = RiskExtractor(client)
    # 네이버 뉴스 검색 OpenAPI — NAVER 키 있으면 실뉴스, 없으면 no-op degrade
    from risk.infrastructure.news.naver_search import NaverNewsSearch
    _nv = NaverNewsSearch()
    news = NewsResearcher(search_fn=_nv if _nv.enabled else (lambda q: []))
    # AI는 anthropic SDK가 아니라 로그인된 claude CLI 서브프로세스로 구동 (이 머신엔 API 키 없음)
    from risk.infrastructure.llm.claude_cli import claude_available, claude_complete
    llm = Commenter(complete_fn=claude_complete if claude_available() else None)
    # 축4 DART 공시이벤트 — 감사대상기간+직전연도 커버 (~540일 윈도우)
    today = datetime.date.today()
    end_de = today.strftime("%Y%m%d")
    bgn_de = (today - datetime.timedelta(days=540)).strftime("%Y%m%d")
    disclosure_fetcher = lambda cc: client.list_disclosures(cc, bgn_de, end_de)
    return AssessRiskUseCase(extractor, client.find_corp_code, news, llm,
                             disclosure_fetcher=disclosure_fetcher,
                             financial_resolver=client.is_financial)


class AssessReq(BaseModel):
    company: str
    end_year: int
    # 수행중요성 — 자동(기본) 또는 직접지정. benchmark 지정 시 직접모드.
    mat_benchmark: str | None = None        # revenue|total_assets|pretax_income|total_equity
    mat_ratio_pct: float | None = None      # 중요성 비율(%) 예: 0.5
    pm_ratio_pct: float | None = None       # 수행중요성 비율(%) 예: 75


def _materiality_opts(req: "AssessReq") -> dict | None:
    """AssessReq → performance_materiality kwargs (%→소수 변환). 직접모드만 dict."""
    if not req.mat_benchmark:
        return None
    opts: dict = {"benchmark": req.mat_benchmark}
    if req.mat_ratio_pct is not None:
        opts["materiality_ratio"] = req.mat_ratio_pct / 100.0
    if req.pm_ratio_pct is not None:
        opts["pm_ratio"] = req.pm_ratio_pct / 100.0
    return opts


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/assess")
def assess(req: AssessReq):
    uc = _build_uc()
    res = uc.run(req.company, req.end_year, materiality_opts=_materiality_opts(req))
    return JSONResponse({
        "company": res.company, "error": res.error,
        "grade": asdict(res.grade) if res.grade else None,
        "materiality": asdict(res.materiality) if res.materiality else None,
        "signals": [asdict(s) for s in res.signals],
        "comments": res.comments,
        "years": [asdict(y) for y in res.years],
        "news": [vars(h) for h in res.news],
        "disclosures": res.disclosures,
        "events": res.events,
        "warnings": res.warnings,
    })


@app.post("/api/export")
def export(req: AssessReq):
    uc = _build_uc()
    res = uc.run(req.company, req.end_year, materiality_opts=_materiality_opts(req))
    safe = _safe_stem(req.company)
    tmp = pathlib.Path(tempfile.gettempdir()) / f"risk_{safe}_{req.end_year}.xlsx"
    build_workpaper(res, str(tmp))
    return FileResponse(str(tmp), filename=f"risk_{safe}_{req.end_year}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


app.mount("/", StaticFiles(directory=str(_FRONT), html=True), name="static")
