"""Ingest route — multipart 파일 업로드."""
from __future__ import annotations
import tempfile
from pathlib import Path
from flask import Blueprint, request, jsonify, g, current_app
from src.application.ingest_uc import IngestUC
from src.infrastructure.fx.wat_rate_client import WatRateClient


bp = Blueprint("ingest", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/ingest")
def ingest_files(pid: int):
    if "ledger" not in request.files:
        return jsonify({"error": "ledger file required"}), 400

    # ignore_cleanup_errors: Windows에서 openpyxl read_only가 핸들을 늦게
    # 놓아 rmtree가 PermissionError를 던지는 경우가 있어 cleanup 실패 무시.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tdp = Path(td)
        ledger_path = tdp / "ledger.xlsx"
        request.files["ledger"].save(ledger_path)

        fs_path = None
        if "fs" in request.files and request.files["fs"].filename:
            fs_path = tdp / "fs.xlsx"
            request.files["fs"].save(fs_path)

        rp_path = None
        if "rp" in request.files and request.files["rp"].filename:
            rp_path = tdp / "rp.xlsx"
            request.files["rp"].save(rp_path)

        allow_path = None
        if "allowance" in request.files and request.files["allowance"].filename:
            allow_path = tdp / "allow.xlsx"
            request.files["allowance"].save(allow_path)

        fx_client = current_app.config.get("FX_CLIENT") or WatRateClient()
        uc = IngestUC(g.session, fx_client=fx_client)
        try:
            result = uc.ingest(pid, ledger_path, fs_path, rp_path, allow_path)
        except KeyError:
            return jsonify({"error": f"project {pid} not found"}), 404

    return jsonify({
        "project_id": result.project_id,
        "ar_count": result.ar_count,
        "ap_count": result.ap_count,
        "ar_total_krw": result.ar_total_krw,
        "ap_total_krw": result.ap_total_krw,
        "confidence_ar": result.confidence_ar,
        "confidence_ap": result.confidence_ap,
        "fs_totals": result.fs_totals,
        "needs_mapping_confirmation": result.needs_mapping_confirmation,
    })


@bp.post("/<int:pid>/ingest/confirm-mapping")
def confirm_mapping(pid: int):
    """사용자가 자동매핑 검토 후 명시적 confirm. 현재는 단순 ack."""
    return jsonify({"status": "confirmed", "project_id": pid})
