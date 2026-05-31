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
    from src.infrastructure.db.repository import ProjectRepo
    proj = ProjectRepo(g.session).get(pid)
    key_th_in = float(data.get("key_threshold", 0))
    if key_th_in <= 0:
        key_th_in = (proj.materiality or 0) * 0.5
        if key_th_in <= 0:
            key_th_in = float("inf")
    params = DesignParams(
        confidence=float(data.get("confidence", 0.95)),
        expected_ms_pct=float(data.get("expected_ms_pct", 0.0)),
        key_threshold=key_th_in,
        n_strata=int(data.get("n_strata", 4)),
        seed=data.get("seed"),
        n_override=n_override,
    )
    uc = DesignSamplingUC(g.session)
    try:
        result = uc.design(pid, kind, params)
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
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


@bp.post("/<int:pid>/sampling/exclude")
def exclude_sample(pid: int):
    """표본에서 특정 거래처 임의 제거 (사용자 판단)."""
    from src.infrastructure.db.repository import SampleRepo
    data = request.get_json(force=True)
    try:
        kind = Kind(data["kind"])
    except (KeyError, ValueError):
        return jsonify({"error": "kind required (AR/AP)"}), 400
    party_name = (data.get("party_name") or "").strip()
    if not party_name:
        return jsonify({"error": "party_name required"}), 400
    n = SampleRepo(g.session).delete_by_account_name(pid, kind, party_name)
    return jsonify({"deleted": n, "party_name": party_name})


@bp.post("/<int:pid>/sampling/design_combined")
def design_combined(pid: int):
    """통합 표본 설계 — 2가지 모드.

    mode="count": n_total 입력 → AR/AP 잔액 비례 분배 (사용자 지정)
    mode="materiality": n_total 미입력 → 수행중요성·tolerable·신뢰수준으로
                         AR/AP 각각 sample_size_mus로 자동 산정
    """
    from src.infrastructure.db.repository import AccountRepo
    data = request.get_json(force=True)
    mode = data.get("mode") or ("count" if data.get("n_total") else "materiality")

    acc_repo = AccountRepo(g.session)
    ar_accs = acc_repo.list_by_project_kind(pid, Kind.AR)
    ap_accs = acc_repo.list_by_project_kind(pid, Kind.AP)
    bv_ar = sum(abs(a.balance_krw) for a in ar_accs)
    bv_ap = sum(abs(a.balance_krw) for a in ap_accs)
    bv_total = bv_ar + bv_ap

    if bv_total <= 0:
        return jsonify({"error": "population BV is 0 — run ingest first"}), 400

    uc = DesignSamplingUC(g.session)
    # key_threshold default — 사용자 미입력(0)이면 수행중요성 * 0.5 (ISA 530 통상).
    # 그것도 0이면 inf로 두어 KEY 강제포함 비활성 (RP만 강제포함).
    from src.infrastructure.db.repository import ProjectRepo
    proj = ProjectRepo(g.session).get(pid)
    key_th_in = float(data.get("key_threshold", 0))
    if key_th_in <= 0:
        key_th_in = (proj.materiality or 0) * 0.5
        if key_th_in <= 0:
            key_th_in = float("inf")

    common = {
        "confidence": float(data.get("confidence", 0.95)),
        "expected_ms_pct": float(data.get("expected_ms_pct", 0.0)),
        "key_threshold": key_th_in,
        "n_strata": int(data.get("n_strata", 4)),
        "seed": data.get("seed"),
    }

    n_ar = 0
    n_ap = 0
    n_total_req = 0

    coverage_pct = 0.0
    if mode == "count":
        try:
            n_total_req = int(data["n_total"])
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "n_total required (int)"}), 400
        if n_total_req < 1:
            return jsonify({"error": "n_total must be >= 1"}), 400

        # 비례 분배
        n_ar = round(bv_ar / bv_total * n_total_req) if bv_total else 0
        n_ap = n_total_req - n_ar
        if n_ar < 1 and bv_ar > 0:
            n_ar = 1
            n_ap = n_total_req - 1
        if n_ap < 1 and bv_ap > 0:
            n_ap = 1
            n_ar = n_total_req - 1
    elif mode == "coverage":
        # AR 커버리지 % 기반 + AP는 활동량 자동 MUS
        coverage_pct = float(data.get("coverage_pct", 0.80))
        if coverage_pct <= 0 or coverage_pct > 1:
            return jsonify({"error": "coverage_pct must be 0~1 (예: 0.80)"}), 400

    results = {}
    for kind_code, bv_k, n_k in (("AR", bv_ar, n_ar), ("AP", bv_ap, n_ap)):
        if bv_k <= 0:
            results[kind_code] = None
            continue
        # mode=materiality·coverage면 자동 산정. AP는 coverage 모드 시 cap 30.
        n_override = n_k if mode == "count" and n_k > 0 else None
        if mode == "coverage" and kind_code == "AP":
            # AR은 커버리지 % 강제포함, AP는 score top N 직접 (기본 30).
            # 명시 0은 'AP 표본 0' 의도 → `or 30`로 삼키지 말 것.
            try:
                n_override = int(data.get("ap_n", 30))
            except (ValueError, TypeError):
                n_override = 30
            if n_override < 0:
                n_override = 30
        cov = coverage_pct if (mode == "coverage" and kind_code == "AR") else 0.0
        params = DesignParams(**common, n_override=n_override, coverage_pct=cov)
        try:
            r = uc.design(pid, Kind(kind_code), params)
        except KeyError:
            return jsonify({"error": "project not found"}), 404
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        results[kind_code] = {
            "kind": r.kind.value,
            "n_total": r.n_total,
            "n_forced": r.n_forced,
            "n_excluded": r.n_excluded,
            "n_representative": r.n_representative,
            "used_seed": r.used_seed,
            "population_bv": r.population_bv,
            "n_requested": n_k if mode == "count" else None,
        }

    actual_total = sum((r["n_total"] if r else 0) for r in results.values())
    note = None
    if mode == "count" and actual_total > n_total_req:
        note = ("강제포함(RP/KEY) 합계가 요청한 n_total을 초과하면 "
                "강제포함만 반영되어 실제 표본수가 더 많을 수 있습니다.")

    return jsonify({
        "mode": mode,
        "n_total_requested": n_total_req if mode == "count" else None,
        "n_total_actual": actual_total,
        "allocation": {"AR": n_ar, "AP": n_ap} if mode == "count" else None,
        "results": results,
        "note": note,
    })
