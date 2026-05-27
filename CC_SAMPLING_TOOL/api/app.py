"""웅계사's CC Sampling Tool — Flask 서버 (Week 3: PDF 회신 추출·매칭·차이판정 API)"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import pandas as pd
from flask import Flask, jsonify, request, send_file, send_from_directory

from src.domain.population import (
    ACCOUNT_GROUP_MAP_PAYABLE,
    ACCOUNT_GROUP_MAP_RECEIVABLE,
    PartyDecision,
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
    AlternativeProcedureRepository,
    ArtifactRepository,
    AuditTrail,
    ConfirmationReplyRepository,
    ProjectRepository,
    WorkpaperRepository,
    init_db,
    get_session,
)
from src.infrastructure.pdf import extract_text, parse_confirmation
from src.domain.matching import match_party
from src.domain.reconciliation import reconcile
from src.infrastructure.report.template_registry import list_templates, get_template
from src.infrastructure.confirmations.send_list_builder import build_send_list
from src.orchestrator import SamplingParams, run_sampling, write_report

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
UPLOAD_DIR = ROOT / "input" / "_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(FRONTEND))
log = logging.getLogger("cc_sampling")

# DB 초기화 (첫 실행 시 테이블 생성)
init_db()


# ── 전역 에러 핸들러 ──────────────────────────────────────────────────────────
@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    """처리되지 않은 예외 → JSON 500 응답 (trace_id 포함)."""
    trace_id = str(uuid.uuid4())
    log.exception(f"[trace_id={trace_id}] Unhandled exception: {e}")
    return jsonify({"error": "내부 서버 오류가 발생했습니다", "trace_id": trace_id}), 500


@app.errorhandler(400)
def handle_bad_request(e):
    return jsonify({"error": str(e.description) if hasattr(e, "description") else "잘못된 요청"}), 400


@app.errorhandler(404)
def handle_not_found(e):
    return jsonify({"error": "요청한 리소스를 찾을 수 없습니다"}), 404


# ── 파일 확장자 유효성 검증 헬퍼 ──────────────────────────────────────────────
_ALLOWED_EXCEL_EXTS = {".xlsx", ".xls", ".xlsm"}
_ALLOWED_PDF_EXT = {".pdf"}


def _validate_file_ext(filename: str, allowed: set[str]) -> bool:
    """파일명 확장자가 허용 목록에 있는지 확인."""
    return Path(filename).suffix.lower() in allowed

# ── in-memory STATE — Week 1 동안 DB와 병행 운영 ──────────────────────────
# 기존 /api/upload, /api/run, /api/download 는 project_id 연동으로 확장.
# project_id 없는 호출은 deprecation warning 로그 + 임시 프로젝트 자동 생성.
STATE: dict = {
    "ledger_path": None,
    "fs_path": None,
    "rp_path": None,
    "last_result": {},   # {"receivable": {"result": ..., "params": ...}, ...}
    "current_project_id": None,
    "workpaper_ids": {},  # {kind: workpaper_id}
    "kind": "receivable",
    "sheets": {},        # {"receivable": sheet_name, "payable": sheet_name}
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
            # 파일 형식 검증 — Excel(.xlsx/.xls/.xlsm)만 허용
            if not _validate_file_ext(f.filename, _ALLOWED_EXCEL_EXTS):
                ext = Path(f.filename).suffix.lower()
                return jsonify({
                    "error": f"'{kind}' 파일 형식 오류: {ext} 파일은 지원하지 않습니다. "
                             f"Excel 파일(.xlsx/.xls/.xlsm)을 업로드하세요."
                }), 400
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
        try:
            wb = openpyxl.load_workbook(STATE["ledger_path"], read_only=True, data_only=True)
            sheets = wb.sheetnames
            wb.close()
            result["sheets"] = sheets
            sheet_map = detect_ledger_sheets(sheets)
            result["sheet_map"] = sheet_map
            STATE["sheets"] = sheet_map
        except Exception as e:
            log.warning(f"거래처원장 시트 감지 실패: {e}")
            result["sheets_warning"] = f"시트 자동 감지 실패: {e!s}. 시트명을 직접 지정하세요."

    # 재무제표 자동 — 총자산
    if STATE.get("fs_path"):
        try:
            fs = load_fs_amounts(STATE["fs_path"])
            if not fs:
                result["fs_warning"] = "재무제표에서 금액 데이터를 읽지 못했습니다. 파일 구조를 확인하세요."
            else:
                result["total_assets"] = get_total_assets(fs)
                result["fs_amounts"] = {
                    k: v for k, v in fs.items() if any(g in k for g in [
                        "외상매출금", "받을어음", "미수금", "선급금", "대여금",
                        "임차보증금", "기타보증금", "외상매입금", "지급어음",
                        "미지급금", "선수금", "임대보증금",
                    ])
                }
        except Exception as e:
            log.warning(f"재무제표 로드 실패: {e}")
            result["fs_warning"] = f"재무제표 파싱 실패: {e!s}"

    if STATE.get("rp_path"):
        try:
            wb = openpyxl.load_workbook(STATE["rp_path"], read_only=True, data_only=True)
            wb.close()
            rp = load_related_parties(STATE["rp_path"])
            result["related_parties"] = sorted(rp)
        except Exception as e:
            log.warning(f"특관자리스트 로드 실패: {e}")
            result["rp_warning"] = f"특관자리스트 파싱 실패: {e!s}"

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
        return jsonify({"error": "거래처원장 파일을 먼저 업로드하세요 (Step 0)"}), 400

    pm_raw = data.get("performance_materiality", 0)
    try:
        pm = float(pm_raw)
    except (TypeError, ValueError):
        return jsonify({"error": f"수행 중요성(performance_materiality) 값이 잘못되었습니다: {pm_raw}"}), 400
    if pm <= 0:
        return jsonify({"error": "수행 중요성(PM)은 0보다 커야 합니다"}), 400

    if project_id is None:
        log.warning("project_id 없는 /api/run 호출 — 임시 프로젝트 생성 (deprecated)")
        with get_session() as s:
            project_id, _ = _get_or_create_temp_project(s, kind)

    try:
        df = pd.read_excel(STATE["ledger_path"], sheet_name=sheet)
    except Exception as e:
        return jsonify({"error": f"거래처원장 파일 읽기 실패: {e!s}. 파일을 다시 업로드하세요."}), 400

    if df.empty:
        return jsonify({"error": "거래처원장이 비어 있습니다. 데이터를 확인하세요."}), 400

    params = SamplingParams(
        company_name=data.get("company_name", ""),
        period_end=date.fromisoformat(data.get("period_end", "2025-12-31")),
        kind=kind,
        performance_materiality=pm,
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

    # Edge case: 모집단 0 또는 거래처 0건 → 사용자에게 명확한 안내
    if result.population_amount <= 0:
        kind_label = "채권" if kind == "receivable" else "채무"
        return jsonify({
            "error": (
                f"{kind_label} 모집단 잔액이 0입니다. "
                f"올바른 시트를 선택했는지 확인하세요. "
                f"(선택된 시트: {sheet or '자동감지'})"
            ),
            "population_amount": 0,
            "hint": "거래처원장 시트명이 채권/채무 중 어느 쪽인지 확인 후 sheet 파라미터를 명시적으로 지정해보세요.",
        }), 400

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
            "preparer": params.preparer,
            "reviewer": params.reviewer,
        }
        wp_repo.save_sampling_result(wp.id, params_dict, serialized)
        # AuditTrail: step1_sampling
        _audit(s, "step1_sampling", "Workpaper", wp.id, project_id,
               after={
                   "kind": kind,
                   "final_sample_size": result.size_result.final_sample_size,
                   "population_amount": result.population_amount,
               })

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
# 6. Template 목록
# ─────────────────────────────────────────────────────────────
@app.route("/api/templates")
def get_templates():
    """등록된 조서 양식 목록 반환 (Step 3 드롭다운용)."""
    templates = list_templates()
    return jsonify([
        {"id": t.id, "name": t.name, "firm_name": t.firm_name}
        for t in templates
    ])


# ─────────────────────────────────────────────────────────────
# 7. Step 2 — 발송명단
# ─────────────────────────────────────────────────────────────
@app.route("/api/project/<pid>/step2/build", methods=["POST"])
def step2_build(pid: str):
    """발송명단 Excel 생성 + Artifact 저장.

    body: {kind, reply_deadline, contact_info, party_contacts}
    """
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        data = request.json or {}
        kind = data.get("kind", STATE.get("kind") or "receivable")
        reply_deadline_str = data.get("reply_deadline")
        contact_info = data.get("contact_info") or {}
        party_contacts = data.get("party_contacts") or {}

        # Step 1 결과에서 decisions 복원
        # STATE cache는 현재 활성 프로젝트 데이터일 때만 사용 (다른 프로젝트 데이터 오염 방지)
        cached = STATE["last_result"].get(kind) if STATE.get("current_project_id") == pid else None
        if not cached:
            # DB에서 복원 — 해당 pid/kind workpaper의 sampling_result
            wp_repo = WorkpaperRepository(s)
            wp = wp_repo.get_or_create(pid, kind)
            if not wp.sampling_result:
                return jsonify({"error": "Step 1 샘플링을 먼저 실행하세요"}), 400
            result_dict = json.loads(wp.sampling_result)
            decisions = [
                PartyDecision(
                    name=d["name"],
                    balance=d["balance"],
                    is_excluded=d["is_excluded"],
                    is_related_party=d["is_related_party"],
                    is_key_item=d["is_key_item"],
                    is_representative=d["is_representative"],
                    final_sampled=d["final_sampled"],
                    exclusion_reason=d.get("exclusion_reason"),
                )
                for d in result_dict.get("decisions", [])
            ]
        else:
            decisions = cached["result"].decisions
            result_dict = _serialize_result(cached["result"], cached["params"])

        # 파싱
        try:
            reply_deadline = (
                date.fromisoformat(reply_deadline_str) if reply_deadline_str else None
            )
        except ValueError:
            reply_deadline = None

        project_info = {
            "company_name": proj.company_name,
            "period_end": proj.period_end,
            "audit_firm": proj.audit_firm,
            "preparer": contact_info.get("preparer", ""),
        }

        kind_label = "채권" if kind == "receivable" else "채무"
        fname = f"발송명단_{proj.company_name}_{proj.period_end}_{kind_label}.xlsx"
        out_dir = ROOT / "output"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / fname

        build_send_list(
            out_path=out_path,
            project_info=project_info,
            decisions=decisions,
            kind=kind,
            reply_deadline=reply_deadline,
            contact_info=contact_info,
            party_contacts=party_contacts,
        )

        # Artifact 저장
        art_repo = ArtifactRepository(s)
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        art = art_repo.save_file(
            project_id=pid,
            kind="send_list",
            source_path=out_path,
            filename=fname,
            workpaper_id=wp.id,
        )
        wp.send_list_artifact_id = art.id
        wp.updated_at = datetime.now(timezone.utc)

        # AuditTrail
        _audit(s, "step2_build_send_list", "Workpaper", wp.id, pid,
               after={"kind": kind, "filename": fname, "parties": len([d for d in decisions if d.final_sampled])})

        return jsonify({
            "artifact_id": art.id,
            "download_url": f"/api/project/{pid}/step2/download/{kind}",
            "filename": fname,
            "party_count": len([d for d in decisions if d.final_sampled]),
        }), 201


@app.route("/api/project/<pid>/step2/download/<kind>")
def step2_download(pid: str, kind: str):
    """생성된 발송명단 다운로드."""
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        if not wp.send_list_artifact_id:
            return jsonify({"error": "발송명단 미생성 — 먼저 build 실행"}), 404
        art = ArtifactRepository(s).get(wp.send_list_artifact_id)
        if art is None or not Path(art.stored_path).exists():
            return jsonify({"error": "파일 없음"}), 404
        return send_file(
            art.stored_path,
            as_attachment=True,
            download_name=art.filename,
        )


@app.route("/api/project/<pid>/step2/mark-sent", methods=["POST"])
def step2_mark_sent(pid: str):
    """발송명단 회사 송부 완료 기록."""
    data = request.json or {}
    kind = data.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        wp.step2_completed_at = datetime.now(timezone.utc)
        wp.updated_at = datetime.now(timezone.utc)
        _audit(s, "step2_mark_sent", "Workpaper", wp.id, pid, after={"kind": kind})
        return jsonify({"ok": True, "step2_completed_at": wp.step2_completed_at.isoformat()})


# ─────────────────────────────────────────────────────────────
# 8. Step 3 — 조서 생성
# ─────────────────────────────────────────────────────────────
@app.route("/api/project/<pid>/step3/build", methods=["POST"])
def step3_build(pid: str):
    """조서 Excel 생성 + Artifact 저장.

    body: {kind, template_id, preparer, reviewer}
    """
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        data = request.json or {}
        kind = data.get("kind", "receivable")
        template_id = data.get("template_id", "woongkye_standard")
        preparer = data.get("preparer", "")
        reviewer = data.get("reviewer", "")

        # Step 1 결과 복원
        cached = STATE["last_result"].get(kind)
        if not cached:
            wp_repo = WorkpaperRepository(s)
            wp = wp_repo.get_or_create(pid, kind)
            if not wp.sampling_result or not wp.sampling_params:
                return jsonify({"error": "Step 1 샘플링을 먼저 실행하세요"}), 400
            params_dict = json.loads(wp.sampling_params)
            params = SamplingParams(
                company_name=params_dict.get("company_name", proj.company_name),
                period_end=date.fromisoformat(params_dict.get("period_end", proj.period_end)),
                kind=kind,
                performance_materiality=float(params_dict.get("performance_materiality", 0)),
                risk_level=params_dict.get("risk_level", "유의적위험"),
                control_reliance=params_dict.get("control_reliance", "Y"),
                preparer=preparer or params_dict.get("preparer", ""),
                reviewer=reviewer or params_dict.get("reviewer", ""),
            )
            # DB 재실행 없이 임시 빌드를 위해 ledger 재로드 필요 — STATE 미캐시 상황
            # 이미 STATE에 ledger가 있으면 재실행, 없으면 에러
            if not STATE.get("ledger_path"):
                return jsonify({"error": "서버 재기동 후 Step 1을 다시 실행하세요"}), 400
            df = pd.read_excel(STATE["ledger_path"], sheet_name=STATE["sheets"].get(kind))
            result = run_sampling(df, params)
        else:
            result = cached["result"]
            params = cached["params"]
            if preparer:
                params.preparer = preparer
            if reviewer:
                params.reviewer = reviewer

        prefix = "C100" if kind == "receivable" else "AA100"
        fname = f"{prefix}_{proj.company_name}_{proj.period_end}.xlsx"
        out_path = ROOT / "output" / fname
        write_report(result, params, out_path, template_id=template_id)

        # Artifact 저장
        art_repo = ArtifactRepository(s)
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        art = art_repo.save_file(
            project_id=pid,
            kind="workpaper",
            source_path=out_path,
            filename=fname,
            workpaper_id=wp.id,
        )
        wp.workpaper_artifact_id = art.id
        wp.updated_at = datetime.now(timezone.utc)

        _audit(s, "step3_export_workpaper", "Workpaper", wp.id, pid,
               after={"kind": kind, "template_id": template_id, "filename": fname})

        return jsonify({
            "artifact_id": art.id,
            "download_url": f"/api/project/{pid}/step3/download/{kind}",
            "filename": fname,
        }), 201


@app.route("/api/project/<pid>/step3/download/<kind>")
def step3_download(pid: str, kind: str):
    """생성된 조서 다운로드."""
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        if not wp.workpaper_artifact_id:
            return jsonify({"error": "조서 미생성 — 먼저 build 실행"}), 404
        art = ArtifactRepository(s).get(wp.workpaper_artifact_id)
        if art is None or not Path(art.stored_path).exists():
            return jsonify({"error": "파일 없음"}), 404
        return send_file(
            art.stored_path,
            as_attachment=True,
            download_name=art.filename,
        )


@app.route("/api/project/<pid>/step3/mark-done", methods=["POST"])
def step3_mark_done(pid: str):
    """조서 작성 완료 기록."""
    data = request.json or {}
    kind = data.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        wp.step3_completed_at = datetime.now(timezone.utc)
        wp.updated_at = datetime.now(timezone.utc)
        _audit(s, "step3_mark_done", "Workpaper", wp.id, pid, after={"kind": kind})
        return jsonify({"ok": True, "step3_completed_at": wp.step3_completed_at.isoformat()})


# ─────────────────────────────────────────────────────────────
# Step 4: PDF 회신 업로드·자동처리·수동보정·완료 기록
# ─────────────────────────────────────────────────────────────
@app.route("/api/project/<pid>/step4/upload-replies", methods=["POST"])
def step4_upload_replies(pid: str):
    """PDF 회신 다중 업로드 → 자동 추출·매칭·차이판정 → ConfirmationReply 생성.

    multipart form-data: files[]=<pdf>, kind=receivable|payable, tolerance=0
    """
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        kind = request.form.get("kind", "receivable")
        try:
            tolerance = float(request.form.get("tolerance", "0") or "0")
        except ValueError:
            tolerance = 0.0

        # Step 1 결과에서 candidates (거래처명) + ledger_balance 가져오기
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        candidates: list[str] = []
        ledger_map: dict[str, float] = {}  # party_name → ledger_balance

        if wp.sampling_result:
            result_dict = json.loads(wp.sampling_result)
            for d in result_dict.get("decisions", []):
                if d.get("final_sampled"):
                    candidates.append(d["name"])
                    ledger_map[d["name"]] = float(d.get("balance", 0))

        files = request.files.getlist("files[]")
        if not files:
            return jsonify({"error": "업로드된 PDF 파일이 없습니다"}), 400

        art_repo = ArtifactRepository(s)
        reply_repo = ConfirmationReplyRepository(s)

        # PDF 형식 검증
        non_pdf = [f.filename for f in files if f.filename and not _validate_file_ext(f.filename, _ALLOWED_PDF_EXT)]
        if non_pdf:
            return jsonify({
                "error": f"PDF 파일이 아닌 파일이 포함되어 있습니다: {', '.join(non_pdf)}. PDF(.pdf)만 업로드하세요."
            }), 400

        results = []
        for f in files:
            if not f.filename:
                continue
            filename = f.filename

            # 1) Artifact 저장
            pdf_bytes = f.read()
            if len(pdf_bytes) == 0:
                results.append({"filename": filename, "status": "error", "error": "빈 파일입니다"})
                continue
            artifact = art_repo.save_bytes(
                project_id=pid,
                kind="pdf_reply",
                content=pdf_bytes,
                filename=filename,
                workpaper_id=wp.id,
            )

            # 2) 텍스트 추출 (tables 포함)
            from pathlib import Path as _Path
            extract_result = extract_text(_Path(artifact.stored_path))
            ocr_warnings = extract_result.warnings

            # 3) 파싱 — pdfplumber tables 우선 활용
            parsed = parse_confirmation(
                extract_result.full_text,
                kind=kind,
                tables=extract_result.tables if extract_result.tables else None,
            )

            # 4) 거래처 매칭
            raw_name = parsed.extracted_name or filename
            if candidates:
                match_result = match_party(raw_name, candidates)
                matched_name = match_result.matched_name
                match_conf = match_result.confidence
                match_method = match_result.method
            else:
                matched_name = None
                match_conf = 0.0
                match_method = "failed"

            # 5) 차이 판정
            ledger_bal = ledger_map.get(matched_name) if matched_name else None
            recon = reconcile(
                ledger_balance=ledger_bal if ledger_bal is not None else 0.0,
                extracted_balance=parsed.extracted_balance,
                tolerance=tolerance,
            )
            status = recon.status
            if matched_name is None:
                status = "needs_review"

            # 6) DB 저장
            reply = reply_repo.create(
                workpaper_id=wp.id,
                pdf_artifact_id=artifact.id,
                party_name_raw=raw_name,
                party_name_matched=matched_name,
                party_match_confidence=match_conf,
                party_match_method=match_method,
                extracted_balance=parsed.extracted_balance,
                extracted_balance_currency=parsed.balance_currency,
                reply_date=parsed.reply_date,
                ledger_balance=ledger_bal,
                difference=recon.difference,
                difference_pct=recon.difference_pct,
                status=status,
                extraction_method=extract_result.method,
                extraction_confidence=extract_result.confidence,
                notes="; ".join(ocr_warnings) if ocr_warnings else None,
            )

            _audit(s, "step4_upload_reply", "ConfirmationReply", reply.id, pid,
                   after={
                       "filename": filename,
                       "status": status,
                       "extracted_balance": parsed.extracted_balance,
                       "party_name_raw": raw_name,
                       "party_name_matched": matched_name,
                   })

            results.append(_serialize_reply(reply, ocr_warnings))

        return jsonify(results), 201


@app.route("/api/project/<pid>/step4/replies", methods=["GET"])
def step4_list_replies(pid: str):
    """워크페이퍼별 회신 일람 조회."""
    kind = request.args.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        reply_repo = ConfirmationReplyRepository(s)
        replies = reply_repo.list_by_workpaper(wp.id)
        return jsonify([_serialize_reply(r) for r in replies])


@app.route("/api/project/<pid>/step4/reply/<reply_id>", methods=["PATCH"])
def step4_patch_reply(pid: str, reply_id: str):
    """회신 수동 보정 — party_name, extracted_balance, reply_date, status."""
    data = request.json or {}
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404

        reply_repo = ConfirmationReplyRepository(s)
        reply = reply_repo.update_reviewer_confirmation(
            reply_id=reply_id,
            reviewer_confirmed_status="overridden",
            party_name_matched=data.get("party_name_matched"),
            extracted_balance=_f(data.get("extracted_balance")),
            reply_date=data.get("reply_date"),
            status=data.get("status"),
            notes=data.get("notes"),
        )
        if reply is None:
            return jsonify({"error": "reply not found"}), 404

        _audit(s, "step4_reviewer_override", "ConfirmationReply", reply_id, pid,
               after={k: v for k, v in data.items() if k in (
                   "party_name_matched", "extracted_balance", "reply_date", "status", "notes"
               )})

        return jsonify(_serialize_reply(reply))


@app.route("/api/project/<pid>/step4/mark-done", methods=["POST"])
def step4_mark_done(pid: str):
    """Step 4 완료 기록."""
    data = request.json or {}
    kind = data.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        wp.step4_completed_at = datetime.now(timezone.utc)
        wp.updated_at = datetime.now(timezone.utc)
        _audit(s, "step4_mark_done", "Workpaper", wp.id, pid, after={"kind": kind})
        return jsonify({"ok": True, "step4_completed_at": wp.step4_completed_at.isoformat()})


# ─────────────────────────────────────────────────────────────
# Step 5: 대체적 절차 — 미회신·차이 자동식별, 증빙 업로드, AlternativeProcedure CRUD
# ─────────────────────────────────────────────────────────────

@app.route("/api/project/<pid>/step5/pending", methods=["GET"])
def step5_pending(pid: str):
    """미회신·차이 거래처 자동 식별.

    미회신 = final_sampled 거래처 중 ConfirmationReply 가 없는 것
    차이   = ConfirmationReply.status == "mismatch"
    """
    kind = request.args.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)

        # Step 1 결과에서 최종 선택 거래처
        sampled_parties: dict[str, float] = {}  # party_name → ledger_balance
        if wp.sampling_result:
            result_dict = json.loads(wp.sampling_result)
            for d in result_dict.get("decisions", []):
                if d.get("final_sampled"):
                    sampled_parties[d["name"]] = float(d.get("balance", 0))

        # 회신 현황
        reply_repo = ConfirmationReplyRepository(s)
        replies = reply_repo.list_by_workpaper(wp.id)
        replied_map: dict[str, str] = {}  # matched_name → status
        for r in replies:
            if r.party_name_matched:
                replied_map[r.party_name_matched] = r.status

        pending: list[dict] = []
        for party, balance in sampled_parties.items():
            status = replied_map.get(party)
            if status is None:
                reason = "미회신"
            elif status == "mismatch":
                reason = "차이"
            else:
                continue  # 정상 회신 → 대체절차 불필요

            # 회신값·차이 조회
            reply_balance: float | None = None
            difference: float | None = None
            for r in replies:
                if r.party_name_matched == party and r.status == "mismatch":
                    reply_balance = r.extracted_balance
                    difference = r.difference
                    break

            pending.append({
                "party_name": party,
                "reason": reason,
                "ledger_balance": balance,
                "reply_balance": reply_balance,
                "difference": difference,
            })

        return jsonify({
            "kind": kind,
            "workpaper_id": wp.id,
            "pending": pending,
            "total": len(pending),
        })


@app.route("/api/project/<pid>/step5/upload-evidence", methods=["POST"])
def step5_upload_evidence(pid: str):
    """단일 거래처 증빙 다중 업로드 → 자동 추출 → AlternativeProcedure 생성/갱신.

    multipart form-data:
      files[]        — 증빙 파일 (1개 이상)
      party_name     — 거래처명
      kind           — receivable | payable
      procedure_type — 후속입금 | 매출증빙 | 발주서대조 | 후속송금 | 기타
      auditor_notes  — 감사인 메모
      ledger_balance — 장부가 (선택)
      reply_balance  — 회신금액 (선택)
    """
    from src.infrastructure.evidence.extractor import extract_evidence
    import tempfile

    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        kind = request.form.get("kind", "receivable")
        party_name = (request.form.get("party_name") or "").strip()
        procedure_type = request.form.get("procedure_type", "기타")
        auditor_notes = request.form.get("auditor_notes", "")
        ledger_balance = _f(request.form.get("ledger_balance"))
        reply_balance = _f(request.form.get("reply_balance"))

        if not party_name:
            return jsonify({"error": "party_name 필수"}), 400

        files = request.files.getlist("files[]")
        if not files:
            return jsonify({"error": "업로드 파일 없음"}), 400

        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        art_repo = ArtifactRepository(s)
        proc_repo = AlternativeProcedureRepository(s)

        # 기존 AlternativeProcedure 조회 (동일 거래처면 갱신)
        proc = proc_repo.get_by_party(wp.id, party_name)

        # 기존 artifact_ids 유지
        existing_ids: list[str] = []
        if proc and proc.evidence_artifact_ids:
            try:
                existing_ids = json.loads(proc.evidence_artifact_ids)
            except Exception:
                existing_ids = []

        # 파일 저장 + 추출
        new_ids: list[str] = []
        extracts = []
        for f in files:
            if not f.filename:
                continue
            file_bytes = f.read()
            art = art_repo.save_bytes(
                project_id=pid,
                kind="evidence",
                content=file_bytes,
                filename=f.filename,
                workpaper_id=wp.id,
            )
            new_ids.append(art.id)

            # 자동 추출
            stored_path = Path(art.stored_path)
            ex = extract_evidence(stored_path)
            extracts.append({
                "artifact_id": art.id,
                "filename": f.filename,
                "document_type": ex.document_type,
                "extracted_amount": ex.extracted_amount,
                "extracted_currency": ex.extracted_currency,
                "extracted_date": ex.extracted_date.isoformat() if ex.extracted_date else None,
                "extraction_method": ex.extraction_method,
                "confidence": ex.confidence,
            })

        all_ids = existing_ids + new_ids

        # 커버리지 계산
        covered_amount = _compute_covered_amount(extracts)
        coverage_ratio: float | None = None
        if ledger_balance and ledger_balance > 0 and covered_amount is not None:
            coverage_ratio = min(1.0, covered_amount / ledger_balance)

        # 결론 자동 판정
        conclusion = _auto_conclusion(coverage_ratio)

        if proc is None:
            # 신규 생성
            # reason 추론: Step 5 pending 에서 조회
            reason = _infer_reason(s, wp.id, party_name)
            proc = proc_repo.create(
                workpaper_id=wp.id,
                party_name=party_name,
                reason=reason,
                ledger_balance=ledger_balance,
                reply_balance=reply_balance,
                difference=(ledger_balance - reply_balance) if (ledger_balance and reply_balance) else None,
                procedure_type=procedure_type,
                evidence_artifact_ids=all_ids,
                covered_amount=covered_amount,
                coverage_ratio=coverage_ratio,
                conclusion=conclusion,
                auditor_notes=auditor_notes or None,
                status="pending",
            )
        else:
            # 갱신
            new_covered = (proc.covered_amount or 0.0) + (covered_amount or 0.0)
            new_lb = ledger_balance or proc.ledger_balance
            new_ratio: float | None = None
            if new_lb and new_lb > 0:
                new_ratio = min(1.0, new_covered / new_lb)
            proc_repo.update(
                proc.id,
                evidence_artifact_ids=all_ids,
                covered_amount=new_covered,
                coverage_ratio=new_ratio,
                conclusion=_auto_conclusion(new_ratio),
                procedure_type=procedure_type or proc.procedure_type,
                auditor_notes=auditor_notes or proc.auditor_notes,
            )

        _audit(s, "step5_upload_evidence", "AlternativeProcedure", proc.id, pid,
               after={
                   "party_name": party_name,
                   "files": len(new_ids),
                   "covered_amount": covered_amount,
                   "coverage_ratio": coverage_ratio,
                   "conclusion": conclusion,
               })

        return jsonify({
            "procedure_id": proc.id,
            "party_name": party_name,
            "evidence_count": len(all_ids),
            "extracts": extracts,
            "covered_amount": covered_amount,
            "coverage_ratio": coverage_ratio,
            "conclusion": conclusion,
        }), 201


@app.route("/api/project/<pid>/step5/upload-folder", methods=["POST"])
def step5_upload_folder(pid: str):
    """BC-N 폴더 zip 업로드 OR 다중 파일 (폴더명 자동 매핑).

    multipart form-data:
      folder_zip     — zip 파일 (선택)
      files[]        — 다중 파일 (선택; folder_zip 없을 때)
      folder_name    — 폴더명 힌트 (예: BC-14_New Future International Trade Co)
      kind           — receivable | payable
    """
    import zipfile, tempfile

    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        kind = request.form.get("kind", "receivable")
        folder_name_hint = request.form.get("folder_name", "")

        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        art_repo = ArtifactRepository(s)
        proc_repo = AlternativeProcedureRepository(s)

        from src.infrastructure.evidence.aggregator import aggregate_folder, parse_bc_folder_name
        from src.infrastructure.evidence.extractor import extract_evidence

        tmp_dir = Path(tempfile.mkdtemp())
        results: list[dict] = []

        try:
            zip_file = request.files.get("folder_zip")
            if zip_file and zip_file.filename:
                # zip 해제
                zip_bytes = zip_file.read()
                zip_path = tmp_dir / "upload.zip"
                zip_path.write_bytes(zip_bytes)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_dir / "extracted")
                work_dir = tmp_dir / "extracted"
            else:
                # 다중 파일 → 임시 폴더에 저장
                work_dir = tmp_dir / (folder_name_hint or "evidence")
                work_dir.mkdir(parents=True, exist_ok=True)
                for f in request.files.getlist("files[]"):
                    if f.filename:
                        dst = work_dir / f.filename
                        dst.write_bytes(f.read())

            # BC-{N} 하위 폴더 탐색
            bc_folders = [d for d in work_dir.iterdir() if d.is_dir() and d.name.startswith("BC-")]
            if not bc_folders:
                bc_folders = [work_dir]  # 단일 폴더

            for folder in bc_folders:
                bc_nums, party = parse_bc_folder_name(folder.name)
                if not party and folder_name_hint:
                    _, party = parse_bc_folder_name(folder_name_hint)
                if not party:
                    party = folder.name

                agg = aggregate_folder(folder, party_name=party)

                # 각 파일을 Artifact 저장
                artifact_ids: list[str] = []
                for ex in agg.extracts:
                    if ex.file_path.exists():
                        art = art_repo.save_file(
                            project_id=pid,
                            kind="evidence",
                            source_path=ex.file_path,
                            filename=ex.file_path.name,
                            workpaper_id=wp.id,
                        )
                        artifact_ids.append(art.id)

                # AlternativeProcedure 생성/갱신
                ledger_balance = _f(request.form.get("ledger_balance"))
                coverage_ratio: float | None = None
                if ledger_balance and ledger_balance > 0 and agg.total_amount:
                    coverage_ratio = min(1.0, agg.total_amount / ledger_balance)

                conclusion = _auto_conclusion(coverage_ratio)
                reason = _infer_reason(s, wp.id, party)

                proc = proc_repo.get_by_party(wp.id, party)
                if proc is None:
                    proc = proc_repo.create(
                        workpaper_id=wp.id,
                        party_name=party,
                        reason=reason,
                        ledger_balance=ledger_balance,
                        procedure_type="auto_detected",
                        evidence_artifact_ids=artifact_ids,
                        covered_amount=agg.total_amount,
                        coverage_ratio=coverage_ratio,
                        conclusion=conclusion,
                        status="pending",
                    )
                else:
                    proc_repo.update(
                        proc.id,
                        evidence_artifact_ids=artifact_ids,
                        covered_amount=agg.total_amount,
                        coverage_ratio=coverage_ratio,
                        conclusion=conclusion,
                    )

                _audit(s, "step5_upload_folder", "AlternativeProcedure", proc.id, pid,
                       after={
                           "party_name": party,
                           "bc_numbers": agg.bc_numbers,
                           "total_amount": agg.total_amount,
                           "total_currency": agg.total_currency,
                           "success_count": agg.success_count,
                           "failed_count": agg.failed_count,
                       })

                results.append({
                    "procedure_id": proc.id,
                    "party_name": party,
                    "bc_numbers": agg.bc_numbers,
                    "total_files": agg.total_files,
                    "success_count": agg.success_count,
                    "failed_count": agg.failed_count,
                    "total_amount": agg.total_amount,
                    "total_currency": agg.total_currency,
                    "amounts_by_currency": agg.amounts_by_currency,
                    "conclusion": conclusion,
                })

        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return jsonify(results), 201


@app.route("/api/project/<pid>/step5/procedures", methods=["GET"])
def step5_list_procedures(pid: str):
    """AlternativeProcedure 일람."""
    kind = request.args.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        proc_repo = AlternativeProcedureRepository(s)
        procs = proc_repo.list_by_workpaper(wp.id)
        return jsonify([_serialize_procedure(p) for p in procs])


@app.route("/api/project/<pid>/step5/procedure/<proc_id>", methods=["PATCH"])
def step5_patch_procedure(pid: str, proc_id: str):
    """AlternativeProcedure 수동 보정.

    body: {procedure_type, covered_amount, conclusion, auditor_notes, status}
    """
    data = request.json or {}
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404

        proc_repo = AlternativeProcedureRepository(s)
        proc = proc_repo.update(proc_id, **{
            k: v for k, v in data.items()
            if k in ("procedure_type", "covered_amount", "conclusion",
                     "auditor_notes", "status", "reason",
                     "ledger_balance", "reply_balance")
        })
        if proc is None:
            return jsonify({"error": "procedure not found"}), 404

        # coverage_ratio 재계산
        if proc.ledger_balance and proc.ledger_balance > 0 and proc.covered_amount:
            proc.coverage_ratio = min(1.0, proc.covered_amount / proc.ledger_balance)

        _audit(s, "step5_manual_update", "AlternativeProcedure", proc_id, pid,
               after={k: v for k, v in data.items()})

        return jsonify(_serialize_procedure(proc))


@app.route("/api/project/<pid>/step5/parse-reconciliation", methods=["POST"])
def step5_parse_reconciliation(pid: str):
    """불일치 소명 xlsx 업로드 → 자동 인식.

    multipart: file=<xlsx>
    """
    import tempfile
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None or proj.status == "archived":
            return jsonify({"error": "not found"}), 404

        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "파일 없음"}), 400

        kind = request.form.get("kind", "payable")
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        art_repo = ArtifactRepository(s)

        # Artifact 저장
        file_bytes = f.read()
        art = art_repo.save_bytes(
            project_id=pid,
            kind="reconciliation",
            content=file_bytes,
            filename=f.filename,
            workpaper_id=wp.id,
        )

        # 파싱
        try:
            sheets = parse_reconciliation_xlsx(Path(art.stored_path))
        except Exception as e:
            return jsonify({"error": f"파싱 실패: {e}"}), 400

        summary = sheets.summary_by_party()

        _audit(s, "step5_parse_reconciliation", "Artifact", art.id, pid,
               after={
                   "filename": f.filename,
                   "mismatch_rows": len(sheets.mismatch_rows),
                   "party_sheets": len(sheets.party_details),
                   "parties": list(summary.keys()),
               })

        return jsonify({
            "artifact_id": art.id,
            "mismatch_rows": len(sheets.mismatch_rows),
            "party_sheets": list(sheets.party_details.keys()),
            "summary_by_party": {
                party: {
                    "currency": v.get("currency"),
                    "sent_amount": v.get("sent_amount"),
                    "reply_amount": v.get("reply_amount"),
                    "difference": v.get("difference"),
                    "reasons": v.get("reasons", []),
                    "account_types": v.get("account_types", []),
                    "detail_rows": len(sheets.party_details.get(party, [])),
                }
                for party, v in summary.items()
            },
            "mismatch_detail": [
                {
                    "party_name": r.party_name,
                    "currency": r.currency,
                    "account_type": r.account_type,
                    "sent_amount": r.sent_amount,
                    "reply_amount": r.reply_amount,
                    "difference": r.difference,
                    "reason": r.reason,
                    "matched": r.matched,
                }
                for r in sheets.mismatch_rows
            ],
        })


@app.route("/api/project/<pid>/step5/mark-done", methods=["POST"])
def step5_mark_done(pid: str):
    """Step 5 완료 기록."""
    data = request.json or {}
    kind = data.get("kind", "receivable")
    with get_session() as s:
        proj = ProjectRepository(s).get(pid)
        if proj is None:
            return jsonify({"error": "not found"}), 404
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, kind)
        wp.step5_completed_at = datetime.now(timezone.utc)
        wp.updated_at = datetime.now(timezone.utc)
        _audit(s, "step5_mark_done", "Workpaper", wp.id, pid, after={"kind": kind})
        return jsonify({"ok": True, "step5_completed_at": wp.step5_completed_at.isoformat()})


# ─────────────────────────────────────────────────────────────
# 9. AuditTrail 조회
# ─────────────────────────────────────────────────────────────
@app.route("/api/project/<pid>/audit-trail")
def get_audit_trail(pid: str):
    """프로젝트 변경 이력 조회."""
    from sqlalchemy import select
    with get_session() as s:
        stmt = (
            select(AuditTrail)
            .where(AuditTrail.project_id == pid)
            .order_by(AuditTrail.timestamp.desc())
        )
        trails = list(s.execute(stmt).scalars())
        return jsonify([
            {
                "id": t.id,
                "timestamp": t.timestamp.isoformat(),
                "user_email": t.user_email,
                "action": t.action,
                "entity_type": t.entity_type,
                "entity_id": t.entity_id,
                "notes": t.notes,
                "after_value": t.after_value,
            }
            for t in trails
        ])


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────
def _audit(session, action: str, entity_type: str, entity_id: str | None,
           project_id: str | None, before=None, after=None, notes: str | None = None,
           user_email: str = "") -> None:
    """AuditTrail 레코드 추가 — 모든 중요 변경 지점에서 호출."""
    trail = AuditTrail(
        project_id=project_id,
        user_email=user_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_value=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_value=json.dumps(after, ensure_ascii=False) if after is not None else None,
        notes=notes,
    )
    session.add(trail)


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


def _serialize_reply(reply, warnings: list | None = None) -> dict:
    return {
        "id": reply.id,
        "workpaper_id": reply.workpaper_id,
        "pdf_artifact_id": reply.pdf_artifact_id,
        "party_name_raw": reply.party_name_raw,
        "party_name_matched": reply.party_name_matched,
        "party_match_confidence": reply.party_match_confidence,
        "party_match_method": reply.party_match_method,
        "extracted_balance": reply.extracted_balance,
        "extracted_balance_currency": reply.extracted_balance_currency,
        "reply_date": reply.reply_date,
        "ledger_balance": reply.ledger_balance,
        "difference": reply.difference,
        "difference_pct": reply.difference_pct,
        "status": reply.status,
        "reviewer_confirmed_status": reply.reviewer_confirmed_status,
        "extraction_method": reply.extraction_method,
        "extraction_confidence": reply.extraction_confidence,
        "notes": reply.notes,
        "created_at": reply.created_at.isoformat() if reply.created_at else None,
        "warnings": warnings or [],
    }


def _serialize_procedure(proc) -> dict:
    import json as _json
    ids: list[str] = []
    if proc.evidence_artifact_ids:
        try:
            ids = _json.loads(proc.evidence_artifact_ids)
        except Exception:
            ids = []
    return {
        "id": proc.id,
        "workpaper_id": proc.workpaper_id,
        "party_name": proc.party_name,
        "reason": proc.reason,
        "ledger_balance": proc.ledger_balance,
        "reply_balance": proc.reply_balance,
        "difference": proc.difference,
        "procedure_type": proc.procedure_type,
        "evidence_artifact_ids": ids,
        "evidence_count": len(ids),
        "covered_amount": proc.covered_amount,
        "coverage_ratio": proc.coverage_ratio,
        "conclusion": proc.conclusion,
        "auditor_notes": proc.auditor_notes,
        "status": proc.status,
        "created_at": proc.created_at.isoformat() if proc.created_at else None,
        "updated_at": proc.updated_at.isoformat() if proc.updated_at else None,
    }


def _compute_covered_amount(extracts: list[dict]) -> float | None:
    """추출 결과 목록에서 KRW 금액 합산 (통화 혼재 시 KRW 우선)."""
    amounts_by_cur: dict[str, float] = {}
    for ex in extracts:
        amt = ex.get("extracted_amount")
        cur = ex.get("extracted_currency") or "KRW"
        if amt and amt > 0:
            amounts_by_cur[cur] = amounts_by_cur.get(cur, 0.0) + float(amt)
    if not amounts_by_cur:
        return None
    if "KRW" in amounts_by_cur:
        return amounts_by_cur["KRW"]
    return sum(amounts_by_cur.values())


def _auto_conclusion(coverage_ratio: float | None) -> str:
    """커버리지 비율 → 결론 자동 판정.

    감사실무 기준:
      ≥ 0.95 → 충분
      ≥ 0.50 → 부분
      < 0.50 → 미해소
      None   → needs_review
    """
    if coverage_ratio is None:
        return "needs_review"
    if coverage_ratio >= 0.95:
        return "충분"
    if coverage_ratio >= 0.50:
        return "부분"
    return "미해소"


def _infer_reason(session, workpaper_id: str, party_name: str) -> str:
    """ConfirmationReply 에서 거래처 reason 추론.

    매칭된 회신이 없으면 → "미회신"
    mismatch 있으면 → "차이"
    """
    from sqlalchemy import select
    from src.infrastructure.persistence.models import ConfirmationReply
    stmt = (
        select(ConfirmationReply)
        .where(ConfirmationReply.workpaper_id == workpaper_id)
        .where(ConfirmationReply.party_name_matched == party_name)
    )
    reply = session.execute(stmt).scalar_one_or_none()
    if reply is None:
        return "미회신"
    if reply.status == "mismatch":
        return "차이"
    return "기타"


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
