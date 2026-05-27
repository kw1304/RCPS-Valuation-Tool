"""웅계사's CC Sampling Tool — Flask 서버 (Week 1: SQLite + Project CRUD)"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import pandas as pd
from flask import Flask, jsonify, request, send_file, send_from_directory

from src.domain.population import (
    ACCOUNT_GROUP_MAP_PAYABLE,
    ACCOUNT_GROUP_MAP_RECEIVABLE,
    aggregate_by_party,
    load_ledger_rows,
)
from src.domain.sample_size import (
    CONFIDENCE_FACTOR_MATRIX,
    KEY_ITEM_RATIO_MATRIX,
)
from src.infrastructure.loaders import get_total_assets, load_fs_amounts, load_related_parties
from src.infrastructure.schemas.ledger_schema import detect_ledger_sheets
from src.infrastructure.persistence import (
    ArtifactRepository,
    ProjectRepository,
    WorkpaperRepository,
    init_db,
    get_session,
)
from src.orchestrator import SamplingParams, run_sampling, write_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
UPLOAD_DIR = ROOT / "input" / "_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(FRONTEND))
log = logging.getLogger("cc_sampling")

# DB 초기화 (첫 실행 시 테이블 생성)
init_db()

# ── in-memory STATE — Week 1 동안 DB와 병행 운영 ──────────────────────────
# 기존 /api/upload, /api/run, /api/download 는 project_id 연동으로 확장.
# project_id 없는 호출은 deprecation warning 로그 + 임시 프로젝트 자동 생성.
STATE: dict = {
    "ledger_path": None,
    "fs_path": None,
    "rp_path": None,
    "last_result": {},   # {"receivable": {...}, "payable": {...}}
    "current_project_id": None,
    "workpaper_ids": {},  # {kind: workpaper_id}
}


def _get_or_create_temp_project(session, kind: str = "both") -> tuple[str, str]:
    """project_id 없는 legacy 호출용 임시 프로젝트 생성.
    (project_id, workpaper_id) 반환.
    """
    proj_repo = ProjectRepository(session)
    wp_repo = WorkpaperRepository(session)

    # STATE 에 이미 있으면 재사용
    if STATE.get("current_project_id"):
        pid = STATE["current_project_id"]
        proj = proj_repo.get(pid)
        if proj and proj.status != "archived":
            wp = wp_repo.get_or_create(pid, kind)
            return pid, wp.id

    proj = proj_repo.create(
        company_name="임시프로젝트",
        period_end=date.today().isoformat(),
        kind="both",
    )
    STATE["current_project_id"] = proj.id
    wp = wp_repo.get_or_create(proj.id, kind)
    STATE["workpaper_ids"][kind] = wp.id
    return proj.id, wp.id


# ─────────────────────────────────────────────────────────────
# 헬스체크 + 정적 파일
# ─────────────────────────────────────────────────────────────
@app.route("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.route("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


@app.route("/<path:p>")
def static_files(p):
    return send_from_directory(FRONTEND, p)


# ─────────────────────────────────────────────────────────────
# Project CRUD
# ─────────────────────────────────────────────────────────────
@app.route("/api/project", methods=["POST"])
def create_project():
    """신규 프로젝트 생성.
    body: {company_name, period_end, kind, audit_firm, preparer_email}
    """
    data = request.json or {}
    company_name = data.get("company_name", "").strip()
    period_end = data.get("period_end", date.today().isoformat())
    kind = data.get("kind", "both")
    audit_firm = data.get("audit_firm", "")
    preparer_email = data.get("preparer_email", "")

    if not company_name:
        return jsonify({"error": "company_name 필수"}), 400

    with get_session() as s:
        repo = ProjectRepository(s)
        proj = repo.create(
            company_name=company_name,
            period_end=period_end,
            kind=kind,
            audit_firm=audit_firm,
            created_by_email=preparer_email,
        )
        # 채권·채무 워크페이퍼 미리 생성
        wp_repo = WorkpaperRepository(s)
        wps = {}
        if kind in ("receivable", "both"):
            wp = wp_repo.get_or_create(proj.id, "receivable")
            wps["receivable"] = wp.id
        if kind in ("payable", "both"):
            wp = wp_repo.get_or_create(proj.id, "payable")
            wps["payable"] = wp.id

        # 현재 세션 업데이트
        STATE["current_project_id"] = proj.id
        STATE["workpaper_ids"] = wps

        return jsonify({
            "id": proj.id,
            "company_name": proj.company_name,
            "period_end": proj.period_end,
            "kind": proj.kind,
            "audit_firm": proj.audit_firm,
            "status": proj.status,
            "workpapers": wps,
            "created_at": proj.created_at.isoformat(),
        }), 201


@app.route("/api/project", methods=["GET"])
def list_projects():
    """프로젝트 목록 (최근 수정 순, archived 제외)."""
    with get_session() as s:
        repo = ProjectRepository(s)
        projects = repo.list_all()
        return jsonify([_serialize_project(p) for p in projects])


@app.route("/api/project/<pid>", methods=["GET"])
def get_project(pid: str):
    """단일 프로젝트 상세 + 워크페이퍼 + 상태."""
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        workpapers = []
        for wp in proj.workpapers:
            workpapers.append({
                "id": wp.id,
                "kind": wp.kind,
                "step1_done": wp.step1_completed_at is not None,
                "step2_done": wp.step2_completed_at is not None,
                "step3_done": wp.step3_completed_at is not None,
                "step4_done": wp.step4_completed_at is not None,
                "step5_done": wp.step5_completed_at is not None,
                "updated_at": wp.updated_at.isoformat() if wp.updated_at else None,
            })
        result = _serialize_project(proj)
        result["workpapers"] = workpapers
        return jsonify(result)


@app.route("/api/project/<pid>", methods=["PATCH"])
def update_project(pid: str):
    """프로젝트 메타정보 수정."""
    data = request.json or {}
    user_email = data.pop("user_email", "")
    with get_session() as s:
        proj = ProjectRepository(s).update(pid, user_email=user_email, **data)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(_serialize_project(proj))


@app.route("/api/project/<pid>", methods=["DELETE"])
def delete_project(pid: str):
    """Soft delete — status=archived. Artifact 파일은 유지."""
    user_email = request.args.get("user_email", "")
    with get_session() as s:
        ok = ProjectRepository(s).soft_delete(pid, user_email=user_email)
        if not ok:
            return jsonify({"error": "not found"}), 404
        return jsonify({"deleted": pid})


@app.route("/api/project/<pid>/activate", methods=["POST"])
def activate_project(pid: str):
    """프로젝트를 현재 세션으로 활성화 (브라우저 셀렉터 전환용)."""
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wps = {wp.kind: wp.id for wp in proj.workpapers}

        STATE["current_project_id"] = pid
        STATE["workpaper_ids"] = wps
        # STATE 파일 경로 초기화 (다른 프로젝트 파일이 남아있을 수 있음)
        STATE["ledger_path"] = None
        STATE["fs_path"] = None
        STATE["rp_path"] = None
        STATE["last_result"] = {}

        return jsonify({
            "activated": pid,
            "company_name": proj.company_name,
            "period_end": proj.period_end,
            "workpapers": wps,
        })


# ─────────────────────────────────────────────────────────────
# 1. 파일 업로드 (기존 + project_id 확장)
# ─────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload():
    """ledger + fs + rp 파일 업로드. multipart form-data.
    project_id 쿼리 파라미터 옵션: ?project_id=<uuid>
    """
    project_id = request.args.get("project_id") or request.form.get("project_id")
    result = {}

    for kind in ("ledger", "fs", "rp"):
        f = request.files.get(kind)
        if f and f.filename:
            path = UPLOAD_DIR / f"_{kind}.xlsx"
            f.save(path)
            STATE[f"{kind}_path"] = str(path)
            result[kind] = path.name

            # Artifact DB 저장
            if project_id:
                try:
                    with get_session() as s:
                        art_repo = ArtifactRepository(s)
                        wp_id = STATE["workpaper_ids"].get(
                            "receivable" if kind in ("ledger", "fs") else "receivable"
                        )
                        art = art_repo.save_file(
                            project_id=project_id,
                            kind=kind,
                            source_path=path,
                            filename=f.filename,
                            workpaper_id=wp_id,
                        )
                        result[f"{kind}_artifact_id"] = art.id
                except Exception as e:
                    log.warning(f"Artifact 저장 실패 (비치명적): {e}")

    # project_id 없는 레거시 호출 — 임시 프로젝트 자동 생성
    if not project_id and (STATE.get("ledger_path") or STATE.get("fs_path")):
        log.warning("project_id 없는 /api/upload 호출 — 임시 프로젝트 생성 (deprecated)")

    # ledger 시트 감지
    if STATE.get("ledger_path"):
        wb = openpyxl.load_workbook(STATE["ledger_path"], read_only=True, data_only=True)
        sheets = wb.sheetnames
        wb.close()
        result["sheets"] = sheets
        sheet_map = detect_ledger_sheets(sheets)
        result["sheet_map"] = sheet_map

    # 재무제표 자동 — 총자산
    if STATE.get("fs_path"):
        fs = load_fs_amounts(STATE["fs_path"])
        result["total_assets"] = get_total_assets(fs)
        result["fs_amounts"] = {
            k: v for k, v in fs.items() if any(g in k for g in [
                "외상매출금", "받을어음", "미수금", "선급금", "대여금",
                "임차보증금", "기타보증금", "외상매입금", "지급어음",
                "미지급금", "선수금", "임대보증금",
            ])
        }

    if STATE.get("rp_path"):
        wb = openpyxl.load_workbook(STATE["rp_path"], read_only=True, data_only=True)
        sheets_rp = wb.sheetnames
        wb.close()
        rp = load_related_parties(STATE["rp_path"])
        result["related_parties"] = sorted(rp)

    return jsonify(result)


# ─────────────────────────────────────────────────────────────
# 2. 모집단 미리보기
# ─────────────────────────────────────────────────────────────
@app.route("/api/inspect", methods=["POST"])
def inspect():
    data = request.json or {}
    kind = data.get("kind", "receivable")
    sheet = data.get("sheet")

    if not STATE.get("ledger_path"):
        return jsonify({"error": "ledger not uploaded"}), 400

    df = pd.read_excel(STATE["ledger_path"], sheet_name=sheet)
    rows = load_ledger_rows(df, kind=kind)
    parties = aggregate_by_party(rows, kind=kind, sign_normalize=True)

    group_totals: dict[str, float] = {}
    for pb in parties.values():
        for g, amt in pb.by_account.items():
            group_totals[g] = group_totals.get(g, 0.0) + amt

    return jsonify({
        "party_count": len(parties),
        "total": sum(pb.total for pb in parties.values()),
        "groups": [{"name": g, "amount": v} for g, v in sorted(group_totals.items(), key=lambda x: -x[1])],
    })


# ─────────────────────────────────────────────────────────────
# 3. 샘플링 실행
# ─────────────────────────────────────────────────────────────
@app.route("/api/run", methods=["POST"])
def run():
    data = request.json or {}
    kind = data.get("kind", "receivable")
    sheet = data.get("sheet")
    project_id = data.get("project_id") or STATE.get("current_project_id")

    if not STATE.get("ledger_path"):
        return jsonify({"error": "ledger not uploaded"}), 400

    if project_id is None:
        log.warning("project_id 없는 /api/run 호출 — 임시 프로젝트 생성 (deprecated)")
        with get_session() as s:
            project_id, _ = _get_or_create_temp_project(s, kind)

    df = pd.read_excel(STATE["ledger_path"], sheet_name=sheet)

    params = SamplingParams(
        company_name=data.get("company_name", ""),
        period_end=date.fromisoformat(data.get("period_end", "2025-12-31")),
        kind=kind,
        performance_materiality=float(data.get("performance_materiality", 0)),
        risk_level=data.get("risk_level", "유의적위험"),
        control_reliance=data.get("control_reliance", "Y"),
        key_item_ratio_override=_f(data.get("key_item_ratio")),
        confidence_factor_override=_f(data.get("confidence_factor")),
        fs_amounts_by_group=data.get("fs_amounts_by_group") or {},
        completeness_notes=data.get("completeness_notes") or {},
        excluded_parties=data.get("excluded_parties") or {},
        related_parties=set(data.get("related_parties") or []),
        force_include_related=bool(data.get("force_include_related", True)),
        random_seed=_i(data.get("seed", 42)),
        preparer=data.get("preparer", ""),
        reviewer=data.get("reviewer", ""),
    )

    result = run_sampling(df, params)
    serialized = _serialize_result(result, params)
    STATE["last_result"][kind] = {"result": result, "params": params}

    # Workpaper DB 저장
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(project_id, kind)
        STATE["workpaper_ids"][kind] = wp.id
        params_dict = {
            "company_name": params.company_name,
            "period_end": str(params.period_end),
            "kind": params.kind,
            "performance_materiality": params.performance_materiality,
            "risk_level": params.risk_level,
            "control_reliance": params.control_reliance,
        }
        wp_repo.save_sampling_result(wp.id, params_dict, serialized)

    return jsonify(serialized)


# ─────────────────────────────────────────────────────────────
# 4. 조서 다운로드
# ─────────────────────────────────────────────────────────────
@app.route("/api/download/<kind>")
def download(kind):
    cached = STATE["last_result"].get(kind)
    if not cached:
        return jsonify({"error": "no result"}), 404

    result = cached["result"]
    params = cached["params"]
    prefix = "C100" if kind == "receivable" else "AA100"
    fname = f"{prefix}_{params.company_name}_{params.period_end}.xlsx"
    out_path = ROOT / "output" / fname
    write_report(result, params, out_path)

    # Artifact DB 저장
    project_id = STATE.get("current_project_id")
    if project_id:
        try:
            with get_session() as s:
                wp_id = STATE["workpaper_ids"].get(kind)
                art = ArtifactRepository(s).save_file(
                    project_id=project_id,
                    kind="workpaper",
                    source_path=out_path,
                    filename=fname,
                    workpaper_id=wp_id,
                )
        except Exception as e:
            log.warning(f"조서 Artifact 저장 실패 (비치명적): {e}")

    return send_file(out_path, as_attachment=True, download_name=fname)


# ─────────────────────────────────────────────────────────────
# 5. 매트릭스 메타정보
# ─────────────────────────────────────────────────────────────
@app.route("/api/matrix")
def matrix():
    return jsonify({
        "key_item_ratio": {f"{k[0]}|{k[1]}": v for k, v in KEY_ITEM_RATIO_MATRIX.items()},
        "confidence_factor": {f"{k[0]}|{k[1]}": v for k, v in CONFIDENCE_FACTOR_MATRIX.items()},
    })


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────
def _serialize_project(proj) -> dict:
    return {
        "id": proj.id,
        "company_name": proj.company_name,
        "audit_firm": proj.audit_firm,
        "period_end": proj.period_end,
        "kind": proj.kind,
        "status": proj.status,
        "created_at": proj.created_at.isoformat() if proj.created_at else None,
        "updated_at": proj.updated_at.isoformat() if proj.updated_at else None,
        "created_by_email": proj.created_by_email,
    }


def _f(v, default=None):
    if v in (None, "", "null"):
        return default
    try:
        return float(v)
    except Exception:
        return default


def _i(v, default=None):
    if v in (None, "", "null"):
        return default
    try:
        return int(v)
    except Exception:
        return default


def _serialize_result(result, params):
    size = result.size_result
    return {
        "population_amount": result.population_amount,
        "completeness": {
            "rows": [
                {"group": r["group"], "ledger": r["ledger"], "fs": r["fs"],
                 "diff": r["diff"], "note": r["note"]}
                for r in result.completeness.by_group
            ],
            "total_ledger": result.completeness.total_ledger,
            "total_fs": result.completeness.total_fs,
            "total_diff": result.completeness.total_diff,
        },
        "size": {
            "key_item_threshold": size.key_item_threshold,
            "key_item_ratio": size.key_item_ratio,
            "confidence_factor": size.confidence_factor,
            "base_sample_size": size.base_sample_size,
            "final_sample_size": size.final_sample_size,
            "sample_interval": size.sample_interval,
            "remaining_population": size.remaining_population,
        },
        "decisions": [
            {
                "name": d.name, "balance": d.balance,
                "is_excluded": d.is_excluded, "is_related_party": d.is_related_party,
                "is_key_item": d.is_key_item, "is_representative": d.is_representative,
                "final_sampled": d.final_sampled, "exclusion_reason": d.exclusion_reason,
            }
            for d in result.decisions
        ],
        "mus": {
            "sample_interval": result.mus_result.sample_interval,
            "random_start": result.mus_result.random_start,
            "selections": [
                {
                    "name": s.name, "balance": s.balance, "cumulative": s.cumulative,
                    "selections": s.selections, "remainder_after": s.remainder_after, "hit": s.hit,
                }
                for s in result.mus_result.selections
            ],
            "sampled_names": result.mus_result.sampled_names,
        },
    }


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8520, debug=False, use_reloader=False)
