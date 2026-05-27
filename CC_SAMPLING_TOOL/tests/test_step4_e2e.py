"""Step 4 E2E 테스트 — 프로젝트 생성 → 샘플링 → PDF 업로드 → ConfirmationReply."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Flask 앱 임포트 전 환경 설정
os.environ.setdefault("FLASK_ENV", "testing")

from api.app import app as flask_app
from src.infrastructure.persistence import get_session, init_db
from src.infrastructure.persistence.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ── 테스트 전용 인메모리 DB ─────────────────────────────────────
@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Flask test client with in-memory SQLite."""
    test_db = tmp_path_factory.mktemp("db") / "test.db"

    import src.infrastructure.persistence.db as db_module
    _orig_engine = db_module.engine
    _orig_factory = db_module.SessionFactory

    test_engine = create_engine(
        f"sqlite:///{test_db}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy import event as sa_event
    @sa_event.listens_for(test_engine, "connect")
    def _set_wal(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(test_engine)
    test_factory = sessionmaker(bind=test_engine, expire_on_commit=False)

    db_module.engine = test_engine
    db_module.SessionFactory = test_factory

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c

    # 복원
    db_module.engine = _orig_engine
    db_module.SessionFactory = _orig_factory


def _create_minimal_pdf_bytes(text: str) -> bytes:
    """pdfplumber로 읽을 수 있는 최소 텍스트 PDF 생성."""
    try:
        import fpdf  # type: ignore

        pdf = fpdf.FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        # 한글은 Helvetica에서 안 되므로 영문만
        safe_text = text.encode("ascii", errors="replace").decode("ascii")
        for line in safe_text.splitlines():
            pdf.cell(0, 8, line, ln=True)
        return pdf.output(dest="S").encode("latin-1")
    except ImportError:
        pass

    # fpdf 없으면 최소 PDF 구조 직접 작성 (pdfplumber가 텍스트 읽기 어려울 수 있음)
    content = text.encode("utf-8", errors="replace")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length " + str(len(content)).encode() + b">>\n"
        b"stream\n" + content + b"\nendstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n0000000000 65535 f\n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )


# ── 헬퍼: Step 1 샘플링 세팅 ─────────────────────────────────────
def _setup_project_with_sampling(client, tmp_path_factory):
    """프로젝트 + 간단한 샘플링 결과 직접 DB에 삽입 (원장 파일 없이)."""
    # 1) 프로젝트 생성
    r = client.post("/api/project", json={
        "company_name": "테스트회사",
        "period_end": "2025-12-31",
        "kind": "receivable",
    })
    assert r.status_code == 201, r.get_data(as_text=True)
    pid = r.get_json()["id"]

    # 2) 워크페이퍼에 sampling_result 직접 삽입
    fake_result = {
        "decisions": [
            {"name": "삼성전자", "balance": 1_234_567_890, "final_sampled": True,
             "is_key_item": True, "is_representative": False,
             "is_related_party": False, "is_excluded": False, "exclusion_reason": None},
            {"name": "LG전자", "balance": 500_000_000, "final_sampled": True,
             "is_key_item": False, "is_representative": True,
             "is_related_party": False, "is_excluded": False, "exclusion_reason": None},
        ],
        "population_amount": 5_000_000_000,
    }
    from src.infrastructure.persistence import get_session
    from src.infrastructure.persistence.repos import WorkpaperRepository
    with get_session() as s:
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(pid, "receivable")
        wp.sampling_result = json.dumps(fake_result, ensure_ascii=False)
        wp.sampling_params = json.dumps({"kind": "receivable"}, ensure_ascii=False)
        wp.step1_completed_at = __import__("datetime").datetime.utcnow()

    return pid


class TestStep4Upload:
    def test_upload_pdf_creates_reply(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)

        # PDF 텍스트 — 삼성전자 회신
        pdf_text = (
            "Samsung Electronics Co. Ltd.\n"
            "Balance: 1,234,567,890\n"
            "Reply Date: 2026-01-15\n"
            "Confirmed (sign)"
        )
        pdf_bytes = _create_minimal_pdf_bytes(pdf_text)

        data = {
            "kind": "receivable",
            "tolerance": "0",
        }
        r = client.post(
            f"/api/project/{pid}/step4/upload-replies",
            data={**data, "files[]": (io.BytesIO(pdf_bytes), "samsung_reply.pdf")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 201, r.get_data(as_text=True)
        replies = r.get_json()
        assert len(replies) == 1
        reply = replies[0]
        assert reply["id"] is not None
        assert reply["extraction_method"] in ("pdfplumber", "ocr", "failed", "failed_ocr_not_installed")

    def test_upload_creates_audit_trail(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)
        pdf_bytes = _create_minimal_pdf_bytes("잔액: 500,000,000원\n(인)")

        client.post(
            f"/api/project/{pid}/step4/upload-replies",
            data={"kind": "receivable", "tolerance": "0",
                  "files[]": (io.BytesIO(pdf_bytes), "reply.pdf")},
            content_type="multipart/form-data",
        )

        r = client.get(f"/api/project/{pid}/audit-trail")
        trails = r.get_json()
        actions = [t["action"] for t in trails]
        assert "step4_upload_reply" in actions

    def test_list_replies(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)
        pdf_bytes = _create_minimal_pdf_bytes("잔액: 100,000원\n확인\n2026-01-01")

        client.post(
            f"/api/project/{pid}/step4/upload-replies",
            data={"kind": "receivable", "files[]": (io.BytesIO(pdf_bytes), "r.pdf")},
            content_type="multipart/form-data",
        )

        r = client.get(f"/api/project/{pid}/step4/replies?kind=receivable")
        assert r.status_code == 200
        replies = r.get_json()
        assert isinstance(replies, list)
        assert len(replies) >= 1

    def test_patch_reply(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)
        pdf_bytes = _create_minimal_pdf_bytes("잔액: 1,000,000원\n(인)")

        upload_r = client.post(
            f"/api/project/{pid}/step4/upload-replies",
            data={"kind": "receivable", "files[]": (io.BytesIO(pdf_bytes), "p.pdf")},
            content_type="multipart/form-data",
        )
        reply_id = upload_r.get_json()[0]["id"]

        patch_r = client.patch(
            f"/api/project/{pid}/step4/reply/{reply_id}",
            json={
                "party_name_matched": "삼성전자",
                "extracted_balance": 1_234_567_890,
                "status": "matched",
                "notes": "수동 보정",
            },
        )
        assert patch_r.status_code == 200
        patched = patch_r.get_json()
        assert patched["party_name_matched"] == "삼성전자"
        assert patched["reviewer_confirmed_status"] == "overridden"

    def test_patch_creates_audit_trail(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)
        pdf_bytes = _create_minimal_pdf_bytes("잔액: 999,000원\n확인")

        upload_r = client.post(
            f"/api/project/{pid}/step4/upload-replies",
            data={"kind": "receivable", "files[]": (io.BytesIO(pdf_bytes), "q.pdf")},
            content_type="multipart/form-data",
        )
        reply_id = upload_r.get_json()[0]["id"]

        client.patch(
            f"/api/project/{pid}/step4/reply/{reply_id}",
            json={"status": "mismatch", "notes": "검토 필요"},
        )

        r = client.get(f"/api/project/{pid}/audit-trail")
        actions = [t["action"] for t in r.get_json()]
        assert "step4_reviewer_override" in actions

    def test_mark_done(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)

        r = client.post(
            f"/api/project/{pid}/step4/mark-done",
            json={"kind": "receivable"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["step4_completed_at"] is not None

    def test_no_files_returns_400(self, client, tmp_path_factory):
        pid = _setup_project_with_sampling(client, tmp_path_factory)
        r = client.post(
            f"/api/project/{pid}/step4/upload-replies",
            data={"kind": "receivable"},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400
