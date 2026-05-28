"""Projection compute route."""
from __future__ import annotations
from flask import Blueprint, request, jsonify, g
from src.domain.entities import Kind
from src.application.projection_uc import ProjectionUC


bp = Blueprint("projection", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/projection")
def compute_projection(pid: int):
    data = request.get_json(force=True) if request.is_json else {}
    try:
        kind = Kind(data.get("kind", "AR"))
    except ValueError:
        return jsonify({"error": "kind must be AR or AP"}), 400
    confidence = float(data.get("confidence", 0.95))
    try:
        view = ProjectionUC(g.session).compute(pid, kind, confidence)
    except KeyError:
        return jsonify({"error": "project not found"}), 404
    return jsonify({
        "kind": view.kind.value,
        "projected_misstatement": view.projected_misstatement,
        "basic_precision": view.basic_precision,
        "incremental_allowance": view.incremental_allowance,
        "upper_limit": view.upper_limit,
        "tolerable": view.tolerable,
        "verdict": view.verdict,
        "sample_size": view.sample_size,
        "sampling_interval": view.sampling_interval,
    })
