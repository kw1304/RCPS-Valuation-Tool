"""전원 소명 검증 스크립트 테스트 — scripts/verify_full_coverage.py."""
from __future__ import annotations

import json
import sys
import pytest
from pathlib import Path


# ── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def project_full():
    """채권 3건 + 채무 2건 샘플링, 다양한 소명 상태 주입."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.infrastructure.persistence import (
        get_session, ProjectRepository, WorkpaperRepository,
        ConfirmationReplyRepository, AlternativeProcedureRepository,
    )
    import json as _json

    with get_session() as s:
        proj = ProjectRepository(s).create(
            company_name="Coverage-Test",
            period_end="2025-12-31",
            kind="both",
        )
        pid = proj.id

        wp_repo = WorkpaperRepository(s)
        # 채권 3건
        wp_r = wp_repo.get_or_create(pid, "receivable")
        wp_r.sampling_result = _json.dumps({"decisions": [
            {"name": "A사", "balance": 10000000, "final_sampled": True},   # → matched
            {"name": "B사", "balance": 5000000,  "final_sampled": True},   # → 대체적_충분
            {"name": "C사", "balance": 3000000,  "final_sampled": True},   # → unresolved
        ]})
        # 채무 2건
        wp_p = wp_repo.get_or_create(pid, "payable")
        wp_p.sampling_result = _json.dumps({"decisions": [
            {"name": "D사", "balance": 8000000, "final_sampled": True},    # → matched
            {"name": "E사", "balance": 2000000, "final_sampled": True},    # → 대체적_pending
        ]})

        reply_repo = ConfirmationReplyRepository(s)
        proc_repo = AlternativeProcedureRepository(s)

        # A사: matched 회신
        reply_repo.create(workpaper_id=wp_r.id, party_name_raw="A사",
                          party_name_matched="A사", status="matched")
        # B사: 대체적 충분
        proc_repo.create(workpaper_id=wp_r.id, party_name="B사",
                         reason="미회신", conclusion="충분", status="completed")
        # C사: 아무것도 없음 → unresolved (생성 안 함)
        # D사: matched 회신 (채무)
        reply_repo.create(workpaper_id=wp_p.id, party_name_raw="D사",
                          party_name_matched="D사", status="matched")
        # E사: pending placeholder
        proc_repo.create(workpaper_id=wp_p.id, party_name="E사",
                         reason="미회신", conclusion="needs_review", status="pending")

    return pid


# ── 검증 스크립트 테스트 ──────────────────────────────────────────────────────

def test_verify_coverage_returns_unresolved_count(project_full):
    """verify_full_coverage.run() → C사만 unresolved → 1건."""
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib, importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_full_coverage",
        str(ROOT / "scripts" / "verify_full_coverage.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    unresolved = mod.run(project_full, threshold=5)
    # C사 unresolved 1건
    assert unresolved == 1


def test_verify_coverage_classify_matched():
    """classify_party: reply_status=matched → matched."""
    ROOT = Path(__file__).resolve().parents[1]
    spec = __import__("importlib").util.spec_from_file_location(
        "vcf2", str(ROOT / "scripts" / "verify_full_coverage.py")
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.classify_party("A사", "receivable", 10000, "matched", None) == "matched"


def test_verify_coverage_classify_unresolved():
    """classify_party: 아무것도 없음 → unresolved."""
    ROOT = Path(__file__).resolve().parents[1]
    spec = __import__("importlib").util.spec_from_file_location(
        "vcf3", str(ROOT / "scripts" / "verify_full_coverage.py")
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.classify_party("C사", "receivable", 3000000, None, None) == "unresolved"


def test_verify_coverage_classify_alt_sufficient():
    """classify_party: alt_conclusion=충분 → 대체적_충분."""
    ROOT = Path(__file__).resolve().parents[1]
    spec = __import__("importlib").util.spec_from_file_location(
        "vcf4", str(ROOT / "scripts" / "verify_full_coverage.py")
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.classify_party("B사", "receivable", 5000000, None, "충분") == "대체적_충분"


def test_verify_coverage_classify_pending():
    """classify_party: alt_conclusion=needs_review → 대체적_pending."""
    ROOT = Path(__file__).resolve().parents[1]
    spec = __import__("importlib").util.spec_from_file_location(
        "vcf5", str(ROOT / "scripts" / "verify_full_coverage.py")
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.classify_party("E사", "payable", 2000000, None, "needs_review") == "대체적_pending"
