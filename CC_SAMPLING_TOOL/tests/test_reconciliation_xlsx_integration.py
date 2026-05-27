"""불일치 소명 xlsx 통합 테스트 — step5/parse-reconciliation DB 자동 통합."""
from __future__ import annotations

import io
import json
import pytest
import openpyxl
from pathlib import Path


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_mismatch_xlsx(parties: list[dict]) -> bytes:
    """회신-불일치 시트만 포함한 최소 xlsx 생성.

    parties: [{party_name, currency, sent_amount, reply_amount, reason}]
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "회신-불일치"
    headers = ["기업명", "조회차수", "사업자등록번호", "담당자명", "담당자이메일",
               "일치여부", "통화", "구분", "발송금액", "회신금액", "차이금액",
               "최초발송일시", "회신일시", "사유"]
    ws.append(headers)
    for p in parties:
        diff = (p.get("sent_amount") or 0) - (p.get("reply_amount") or 0)
        ws.append([
            p.get("party_name", ""),
            1, "", "", "", "N",
            p.get("currency", "KRW"), "채권",
            p.get("sent_amount", 0), p.get("reply_amount", 0), diff,
            None, None,
            p.get("reason", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from api.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def project_with_replies(client):
    """프로젝트 생성 + 채권 sampling_result + mismatch 회신 주입."""
    r = client.post("/api/project", json={
        "company_name": "Reconcile-Test",
        "period_end": "2025-12-31",
        "kind": "both",
        "audit_firm": "테스트감사",
    })
    assert r.status_code == 201
    proj = r.get_json()
    pid = proj["id"]

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.infrastructure.persistence import get_session, WorkpaperRepository, ConfirmationReplyRepository
    import json as _json

    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp_r = wp_repo.get_or_create(pid, "receivable")
        wp_r.sampling_result = _json.dumps({"decisions": [
            {"name": "COSMAX USA", "balance": 50000000, "final_sampled": True},
            {"name": "거래처Z",    "balance": 10000000, "final_sampled": True},
        ]})
        reply_repo = ConfirmationReplyRepository(s)
        # COSMAX USA → mismatch
        reply_repo.create(
            workpaper_id=wp_r.id,
            party_name_raw="COSMAX USA",
            party_name_matched="COSMAX USA",
            status="mismatch",
            ledger_balance=50000000,
            extracted_balance=48000000,
        )

    return pid


# ── 기본 파싱 및 DB 통합 ─────────────────────────────────────────────────────

def test_parse_reconciliation_returns_summary(client, project_with_replies):
    """xlsx 업로드 → summary_by_party 반환."""
    pid = project_with_replies
    xlsx_bytes = _make_mismatch_xlsx([
        {"party_name": "COSMAX USA", "sent_amount": 50000000, "reply_amount": 48000000,
         "reason": "기간귀속차이"},
    ])
    r = client.post(
        f"/api/project/{pid}/step5/parse-reconciliation",
        data={"file": (io.BytesIO(xlsx_bytes), "test_mismatch.xlsx"), "kind": "receivable"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert "COSMAX USA" in data["summary_by_party"]
    assert data["mismatch_rows"] >= 1


def test_parse_reconciliation_updates_reply_notes(client, project_with_replies):
    """불일치 소명 xlsx 업로드 → 기존 ConfirmationReply.notes 갱신."""
    pid = project_with_replies
    xlsx_bytes = _make_mismatch_xlsx([
        {"party_name": "COSMAX USA", "sent_amount": 50000000, "reply_amount": 48000000,
         "reason": "기간귀속차이"},
    ])
    client.post(
        f"/api/project/{pid}/step5/parse-reconciliation",
        data={"file": (io.BytesIO(xlsx_bytes), "test_mismatch.xlsx"), "kind": "receivable"},
        content_type="multipart/form-data",
    )

    from src.infrastructure.persistence import get_session, WorkpaperRepository, ConfirmationReplyRepository
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp_r = wp_repo.get_or_create(pid, "receivable")
        reply_repo = ConfirmationReplyRepository(s)
        replies = reply_repo.list_by_workpaper(wp_r.id)
        cosmax_replies = [r for r in replies if r.party_name_matched == "COSMAX USA"]
        assert len(cosmax_replies) >= 1
        # notes에 소명 사유 포함
        assert any("기간귀속차이" in (r.notes or "") for r in cosmax_replies)


def test_parse_reconciliation_status_upgrade_with_reason(client, project_with_replies):
    """사유 명시된 경우 → 회신 status를 matched로 상향."""
    pid = project_with_replies
    xlsx_bytes = _make_mismatch_xlsx([
        {"party_name": "COSMAX USA", "sent_amount": 50000000, "reply_amount": 48000000,
         "reason": "기간귀속차이 소명 완료"},
    ])
    client.post(
        f"/api/project/{pid}/step5/parse-reconciliation",
        data={"file": (io.BytesIO(xlsx_bytes), "test_mismatch.xlsx"), "kind": "receivable"},
        content_type="multipart/form-data",
    )

    from src.infrastructure.persistence import get_session, WorkpaperRepository, ConfirmationReplyRepository
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp_r = wp_repo.get_or_create(pid, "receivable")
        reply_repo = ConfirmationReplyRepository(s)
        replies = reply_repo.list_by_workpaper(wp_r.id)
        cosmax_replies = [r for r in replies if r.party_name_matched == "COSMAX USA"]
        assert any(r.status == "matched" for r in cosmax_replies)


def test_parse_reconciliation_no_file_returns_400(client, project_with_replies):
    """파일 없으면 400."""
    pid = project_with_replies
    r = client.post(f"/api/project/{pid}/step5/parse-reconciliation")
    assert r.status_code == 400


def test_parse_reconciliation_empty_party_no_crash(client, project_with_replies):
    """거래처 행 없는 xlsx → 오류 없이 빈 결과."""
    pid = project_with_replies
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "회신-불일치"
    ws.append(["기업명", "조회차수", "사업자등록번호", "담당자명", "담당자이메일",
               "일치여부", "통화", "구분", "발송금액", "회신금액", "차이금액",
               "최초발송일시", "회신일시", "사유"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(
        f"/api/project/{pid}/step5/parse-reconciliation",
        data={"file": (io.BytesIO(buf.getvalue()), "empty.xlsx"), "kind": "receivable"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["mismatch_rows"] == 0
    assert data["summary_by_party"] == {}
