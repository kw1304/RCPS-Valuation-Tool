"""Alternative procedure route."""
from __future__ import annotations
from flask import Blueprint, request, jsonify, g
from src.domain.entities import Kind
from src.application.alternative_uc import AlternativeUC


bp = Blueprint("alternative", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/alternative")
def register_alternative(pid: int):
    data = request.get_json(force=True)
    try:
        kind = Kind(data["kind"])
    except (KeyError, ValueError):
        return jsonify({"error": "kind must be AR or AP"}), 400
    try:
        r = AlternativeUC(g.session).register(
            pid, kind,
            party_id=data["party_id"],
            procedure_type=data.get("procedure_type", "기타"),
            evidence_sum=float(data.get("evidence_sum", 0)),
            note=data.get("note"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "coverage_pct": r.coverage_pct,
        "verdict": r.verdict,
        "covered_amt": r.covered_amt,
        "non_response_total": r.non_response_total,
    })
