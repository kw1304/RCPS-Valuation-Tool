"""Sampling design route."""
from __future__ import annotations
from flask import Blueprint, request, jsonify, g
from src.domain.entities import Kind
from src.application.design_sampling_uc import (
    DesignSamplingUC, DesignParams,
)


bp = Blueprint("sampling", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/sampling/design")
def design_sampling(pid: int):
    data = request.get_json(force=True)
    try:
        kind = Kind(data["kind"])
    except (KeyError, ValueError):
        return jsonify({"error": "kind must be 'AR' or 'AP'"}), 400
    params = DesignParams(
        confidence=float(data.get("confidence", 0.95)),
        expected_ms_pct=float(data.get("expected_ms_pct", 0.0)),
        key_threshold=float(data.get("key_threshold", 0)),
        n_strata=int(data.get("n_strata", 4)),
        seed=data.get("seed"),
    )
    uc = DesignSamplingUC(g.session)
    try:
        result = uc.design(pid, kind, params)
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404
    return jsonify({
        "kind": result.kind.value,
        "n_total": result.n_total,
        "n_forced": result.n_forced,
        "n_excluded": result.n_excluded,
        "n_representative": result.n_representative,
        "used_seed": result.used_seed,
        "population_bv": result.population_bv,
        "strata": [
            {"low": s.low, "high": s.high, "n_required": s.n_required}
            for s in result.strata
        ],
    })
