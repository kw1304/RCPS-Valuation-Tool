"""Step 5 E2E 테스트 — AlternativeProcedure 생성·조회·갱신·완료."""
from __future__ import annotations

import json
import pytest
import tempfile
from pathlib import Path

# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    """Flask test client."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from api.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def project(client):
    """프로젝트 생성 + Step 1 샘플링 실행."""
    r = client.post("/api/project", json={
        "company_name": "테스트Step5",
        "period_end": "2025-12-31",
        "kind": "receivable",
        "audit_firm": "웅계감사",
    })
    assert r.status_code == 201
    return r.get_json()


# ── AlternativeProcedure CRUD ────────────────────────────────────────────────

def test_step5_pending_empty(client, project):
    """Step 1 미실행 → pending 목록 비어있음."""
    pid = project["id"]
    r = client.get(f"/api/project/{pid}/step5/pending?kind=receivable")
    assert r.status_code == 200
    data = r.get_json()
    assert data["pending"] == []


def test_step5_procedures_empty(client, project):
    """초기 AlternativeProcedure 없음."""
    pid = project["id"]
    r = client.get(f"/api/project/{pid}/step5/procedures?kind=receivable")
    assert r.status_code == 200
    assert r.get_json() == []


def test_step5_upload_evidence_creates_procedure(client, project):
    """증빙 파일 업로드 → AlternativeProcedure 생성."""
    pid = project["id"]

    # 임시 텍스트 파일 (실제 xls/pdf 대신)
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"TOTAL AMOUNT 5,000,000 KRW\nDate: 2025-06-30")
        tmp_path = Path(tmp.name)

    try:
        data = {
            "party_name": "테스트거래처A",
            "kind": "receivable",
            "procedure_type": "매출증빙",
            "auditor_notes": "인보이스 확인",
            "ledger_balance": "5000000",
        }
        with open(tmp_path, "rb") as f:
            r = client.post(
                f"/api/project/{pid}/step5/upload-evidence",
                data={**data, "files[]": (f, "test_invoice.txt")},
                content_type="multipart/form-data",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    assert r.status_code == 201, r.get_json()
    resp = r.get_json()
    assert resp["party_name"] == "테스트거래처A"
    assert resp["evidence_count"] >= 1
    assert "procedure_id" in resp


def test_step5_procedures_after_upload(client, project):
    """업로드 후 procedures 목록에서 조회 가능."""
    pid = project["id"]

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"TOTAL 3000000 KRW")
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "rb") as f:
            client.post(
                f"/api/project/{pid}/step5/upload-evidence",
                data={
                    "party_name": "조회거래처B",
                    "kind": "receivable",
                    "procedure_type": "후속입금",
                    "ledger_balance": "3000000",
                    "files[]": (f, "receipt.txt"),
                },
                content_type="multipart/form-data",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    r = client.get(f"/api/project/{pid}/step5/procedures?kind=receivable")
    assert r.status_code == 200
    procs = r.get_json()
    assert any(p["party_name"] == "조회거래처B" for p in procs)


def test_step5_patch_procedure(client, project):
    """AlternativeProcedure PATCH — 결론 수동 보정."""
    pid = project["id"]

    # 먼저 생성
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"Amount 100000")
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "rb") as f:
            r_create = client.post(
                f"/api/project/{pid}/step5/upload-evidence",
                data={
                    "party_name": "패치테스트거래처",
                    "kind": "receivable",
                    "procedure_type": "기타",
                    "ledger_balance": "1000000",
                    "files[]": (f, "doc.txt"),
                },
                content_type="multipart/form-data",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    proc_id = r_create.get_json()["procedure_id"]

    # PATCH
    r_patch = client.patch(
        f"/api/project/{pid}/step5/procedure/{proc_id}",
        json={"conclusion": "충분", "auditor_notes": "감사인 검토 완료"},
    )
    assert r_patch.status_code == 200
    patched = r_patch.get_json()
    assert patched["conclusion"] == "충분"
    assert "감사인 검토 완료" in (patched["auditor_notes"] or "")


def test_step5_mark_done(client, project):
    """Step 5 완료 기록."""
    pid = project["id"]
    r = client.post(f"/api/project/{pid}/step5/mark-done",
                    json={"kind": "receivable"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "step5_completed_at" in data


def test_step5_parse_reconciliation_file(client, project):
    """불일치 소명 xlsx 업로드 → 파싱 API."""
    pid = project["id"]

    RECON_XLSX = (
        Path(__file__).resolve().parents[1]
        / "input" / "조회서 회수본 및 대체적 절차" / "대체적 증빙"
        / "BC-5,12_채권채무조회서_불일치 소명.xlsx"
    )
    if not RECON_XLSX.exists():
        pytest.skip("실데이터 없음")

    with open(RECON_XLSX, "rb") as f:
        r = client.post(
            f"/api/project/{pid}/step5/parse-reconciliation",
            data={"file": (f, RECON_XLSX.name), "kind": "payable"},
            content_type="multipart/form-data",
        )

    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    assert data["mismatch_rows"] >= 3
    assert "summary_by_party" in data


def test_step5_audit_trail(client, project):
    """step5 액션이 AuditTrail 에 기록됨."""
    pid = project["id"]

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"TOTAL 2000000 KRW")
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "rb") as f:
            client.post(
                f"/api/project/{pid}/step5/upload-evidence",
                data={
                    "party_name": "감사추적테스트",
                    "kind": "receivable",
                    "procedure_type": "발주서대조",
                    "ledger_balance": "2000000",
                    "files[]": (f, "po.txt"),
                },
                content_type="multipart/form-data",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    r_trail = client.get(f"/api/project/{pid}/audit-trail")
    assert r_trail.status_code == 200
    trails = r_trail.get_json()
    actions = [t["action"] for t in trails]
    assert "step5_upload_evidence" in actions, f"step5 액션 없음: {actions}"


def test_step5_project_not_found(client):
    """존재하지 않는 프로젝트 → 404."""
    r = client.get("/api/project/nonexistent/step5/pending")
    assert r.status_code == 404


def test_step5_upload_no_party(client, project):
    """party_name 없이 업로드 → 400."""
    pid = project["id"]
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp.write(b"content")
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "rb") as f:
            r = client.post(
                f"/api/project/{pid}/step5/upload-evidence",
                data={"kind": "receivable", "files[]": (f, "f.txt")},
                content_type="multipart/form-data",
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    assert r.status_code == 400


def test_step5_auto_conclusion_logic():
    """_auto_conclusion 함수 단위 테스트."""
    from api.app import _auto_conclusion
    assert _auto_conclusion(None) == "needs_review"
    assert _auto_conclusion(0.0) == "미해소"
    assert _auto_conclusion(0.3) == "미해소"
    assert _auto_conclusion(0.5) == "부분"
    assert _auto_conclusion(0.8) == "부분"
    assert _auto_conclusion(0.95) == "충분"
    assert _auto_conclusion(1.0) == "충분"
