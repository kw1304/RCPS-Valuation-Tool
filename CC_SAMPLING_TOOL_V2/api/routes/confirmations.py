"""Confirmations routes — sendlist download + PDF upload."""
from __future__ import annotations
import io
import tempfile
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, g
from src.domain.entities import Kind
from src.application.send_list_uc import SendListUC
from src.application.match_response_uc import MatchResponseUC


bp = Blueprint("confirmations", __name__, url_prefix="/api/projects")


@bp.get("/<int:pid>/sendlist")
def download_sendlist(pid: int):
    try:
        blob = SendListUC(g.session).build(pid)
    except KeyError:
        return jsonify({"error": "project not found"}), 404
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"sendlist_{pid}.xlsx",
    )


@bp.post("/<int:pid>/confirmations/upload")
def upload_confirmation(pid: int):
    if "pdf" not in request.files:
        return jsonify({"error": "pdf file required"}), 400
    kind_str = request.form.get("kind", "AR")
    try:
        kind = Kind(kind_str)
    except ValueError:
        return jsonify({"error": "kind must be AR or AP"}), 400
    diff_reason = request.form.get("diff_reason") or None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        pdf_path = Path(td) / "conf.pdf"
        request.files["pdf"].save(pdf_path)
        uc = MatchResponseUC(g.session)
        result = uc.match_one(pid, kind, pdf_path, diff_reason=diff_reason)
    return jsonify({
        "matched_party": result.matched_party,
        "confirmed": result.confirmed,
        "verdict": result.verdict.value if result.verdict else None,
        "extraction_confidence": result.extraction_confidence,
    })
