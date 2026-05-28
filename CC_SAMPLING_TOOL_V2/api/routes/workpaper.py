"""Workpaper download route."""
from __future__ import annotations
import io
from flask import Blueprint, send_file, jsonify, g
from src.application.export_workpaper_uc import ExportWorkpaperUC


bp = Blueprint("workpaper", __name__, url_prefix="/api/projects")

_ALLOWED_TEMPLATES = {"c100", "aa100"}


@bp.get("/<int:pid>/workpaper/<template>")
def download_workpaper(pid: int, template: str):
    if template not in _ALLOWED_TEMPLATES:
        return jsonify({"error": f"unknown template {template!r}"}), 404
    try:
        blob = ExportWorkpaperUC(g.session).build(pid, template)
    except KeyError:
        return jsonify({"error": "project not found"}), 404
    except FileNotFoundError:
        return jsonify({"error": f"template {template} missing"}), 404
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"{template}_{pid}.xlsx",
    )
