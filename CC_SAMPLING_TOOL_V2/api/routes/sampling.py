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
    n_override_raw = data.get("n_override")
    n_override = (
        int(n_override_raw)
        if n_override_raw not in (None, "", 0) else None
    )
    params = DesignParams(
        confidence=float(data.get("confidence", 0.95)),
        expected_ms_pct=float(data.get("expected_ms_pct", 0.0)),
        key_threshold=float(data.get("key_threshold", 0)),
        n_strata=int(data.get("n_strata", 4)),
        seed=data.get("seed"),
        n_override=n_override,
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


@bp.post("/<int:pid>/sampling/design_combined")
def design_combined(pid: int):
    """통합 표본 설계 — 단일 N을 AR/AP 모집단 잔액 비례로 분배 후 각각 design."""
    from src.infrastructure.db.repository import AccountRepo
    data = request.get_json(force=True)
    try:
        n_total = int(data["n_total"])
    except (KeyError, ValueError, TypeError):
        return jsonify({"error": "n_total required (int)"}), 400
    if n_total < 1:
        return jsonify({"error": "n_total must be >= 1"}), 400

    acc_repo = AccountRepo(g.session)
    ar_accs = acc_repo.list_by_project_kind(pid, Kind.AR)
    ap_accs = acc_repo.list_by_project_kind(pid, Kind.AP)
    bv_ar = sum(abs(a.balance_krw) for a in ar_accs)
    bv_ap = sum(abs(a.balance_krw) for a in ap_accs)
    bv_total = bv_ar + bv_ap

    if bv_total <= 0:
        return jsonify({"error": "population BV is 0 — run ingest first"}), 400

    # 비례 분배 (round + 잔여 조정)
    n_ar = round(bv_ar / bv_total * n_total)
    n_ap = n_total - n_ar
    # 둘 다 최소 1 (양쪽 모집단 있으면)
    if n_ar < 1 and bv_ar > 0:
        n_ar = 1
        n_ap = n_total - 1
    if n_ap < 1 and bv_ap > 0:
        n_ap = 1
        n_ar = n_total - 1

    uc = DesignSamplingUC(g.session)
    common = {
        "confidence": float(data.get("confidence", 0.95)),
        "expected_ms_pct": float(data.get("expected_ms_pct", 0.0)),
        "key_threshold": float(data.get("key_threshold", 0)),
        "n_strata": int(data.get("n_strata", 4)),
        "seed": data.get("seed"),
    }

    results = {}
    for kind, n_k in (("AR", n_ar), ("AP", n_ap)):
        if n_k <= 0:
            results[kind] = None
            continue
        params = DesignParams(**common, n_override=n_k)
        try:
            r = uc.design(pid, Kind(kind), params)
        except KeyError:
            return jsonify({"error": "project not found"}), 404
        results[kind] = {
            "kind": r.kind.value,
            "n_total": r.n_total,
            "n_forced": r.n_forced,
            "n_excluded": r.n_excluded,
            "n_representative": r.n_representative,
            "used_seed": r.used_seed,
            "population_bv": r.population_bv,
            "n_requested": n_k,
        }

    actual_total = sum((r["n_total"] if r else 0) for r in results.values())
    return jsonify({
        "n_total_requested": n_total,
        "n_total_actual": actual_total,
        "allocation": {"AR": n_ar, "AP": n_ap},
        "results": results,
        "note": ("강제포함(RP/KEY) 합계가 요청한 n_total을 초과하면 "
                 "강제포함만 반영되어 실제 표본수가 더 많을 수 있습니다.")
        if actual_total > n_total else None,
    })
