"""Project CRUD routes."""
from __future__ import annotations
from datetime import date
from flask import Blueprint, request, jsonify, g
from src.infrastructure.db.repository import ProjectRepo


bp = Blueprint("projects", __name__, url_prefix="/api/projects")


def _proj_to_json(p):
    return {
        "id": p.id,
        "client": p.client,
        "period_end": p.period_end.isoformat(),
        "base_ccy": p.base_ccy,
        "materiality": p.materiality,
        "tolerable": p.tolerable,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@bp.post("")
def create_project():
    data = request.get_json(force=True)
    repo = ProjectRepo(g.session)
    pid = repo.create(
        client=data["client"],
        period_end=date.fromisoformat(data["period_end"]),
        base_ccy=data.get("base_ccy", "KRW"),
        materiality=float(data["materiality"]),
        tolerable=float(data["tolerable"]),
    )
    return jsonify(_proj_to_json(repo.get(pid))), 201


@bp.get("")
def list_projects():
    repo = ProjectRepo(g.session)
    return jsonify([_proj_to_json(p) for p in repo.list_all()])


@bp.get("/<int:pid>")
def get_project(pid: int):
    repo = ProjectRepo(g.session)
    try:
        return jsonify(_proj_to_json(repo.get(pid)))
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404


@bp.delete("/<int:pid>")
def delete_project(pid: int):
    repo = ProjectRepo(g.session)
    try:
        repo.delete(pid)
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404
    return jsonify({"status": "deleted", "id": pid})
