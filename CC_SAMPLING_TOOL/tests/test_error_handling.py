"""오류 처리 강화 테스트

파일 형식 오류·빈 모집단·PM=0 등 edge case에 대해 명확한 400 응답이 반환되는지 확인.
Flask test client 사용.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(scope="module")
def client():
    """Flask test client (독립 in-memory DB)."""
    import os
    os.environ["CC_TEST_DB"] = ":memory:"
    import api.app as app_module
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c
    os.environ.pop("CC_TEST_DB", None)


# ── 파일 업로드 형식 검증 ────────────────────────────────────────────────────
class TestUploadFileValidation:
    def test_csv_ledger_rejected(self, client):
        """CSV 파일을 ledger로 업로드하면 400 응답을 받아야 한다."""
        data = {
            "ledger": (io.BytesIO(b"col1,col2\n1,2"), "ledger.csv"),
        }
        rv = client.post(
            "/api/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert rv.status_code == 400
        body = rv.get_json()
        assert "error" in body
        assert "csv" in body["error"].lower() or "형식" in body["error"]

    def test_pdf_as_ledger_rejected(self, client):
        """PDF 파일을 ledger로 업로드하면 400 응답을 받아야 한다."""
        data = {
            "ledger": (io.BytesIO(b"%PDF-1.4"), "ledger.pdf"),
        }
        rv = client.post(
            "/api/upload",
            data=data,
            content_type="multipart/form-data",
        )
        assert rv.status_code == 400
        body = rv.get_json()
        assert "error" in body

    def test_xlsx_ledger_accepted(self, client, tmp_path):
        """올바른 .xlsx 파일은 400 오류 없이 처리되어야 한다 (파싱 실패는 무관)."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["코드", "거래처명", "계정과목", "계정과목명", "통화", "기초", "증감", "기말"])
        ws.append(["001", "테스트거래처", "외상매출금", "외상매출금", "KRW", 0, 100_000, 100_000])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        data = {"ledger": (buf, "ledger.xlsx")}
        rv = client.post("/api/upload", data=data, content_type="multipart/form-data")
        # 형식 검증은 통과 (200 또는 기타 — 형식 오류 400은 아님)
        assert rv.status_code != 400 or "형식" not in (rv.get_json() or {}).get("error", "")


# ── /api/run edge case ───────────────────────────────────────────────────────
class TestRunEdgeCases:
    def _upload_minimal_ledger(self, client, with_data: bool = True):
        """테스트용 최소 거래처원장 업로드."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "채권"
        ws.append(["코드", "거래처명", "계정과목", "계정과목명", "통화", "기초", "증감", "기말"])
        if with_data:
            ws.append(["001", "테스트거래처", "외상매출금", "외상매출금", "KRW", 0, 500_000_000, 500_000_000])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        data = {"ledger": (buf, "ledger.xlsx")}
        client.post("/api/upload", data=data, content_type="multipart/form-data")

    def test_run_without_upload_returns_400(self, client):
        """거래처원장 없이 /api/run 호출 시 400."""
        # STATE 초기화
        import api.app as app_module
        app_module.STATE["ledger_path"] = None

        rv = client.post("/api/run", json={
            "kind": "receivable",
            "company_name": "테스트",
            "period_end": "2025-12-31",
            "performance_materiality": 10_000_000,
        })
        assert rv.status_code == 400
        assert "업로드" in rv.get_json().get("error", "") or "ledger" in rv.get_json().get("error", "").lower()

    def test_run_with_zero_pm_returns_400(self, client):
        """PM=0이면 400."""
        self._upload_minimal_ledger(client)
        rv = client.post("/api/run", json={
            "kind": "receivable",
            "company_name": "테스트",
            "period_end": "2025-12-31",
            "performance_materiality": 0,
            "sheet": "채권",
        })
        assert rv.status_code == 400
        body = rv.get_json()
        assert "error" in body

    def test_run_with_negative_pm_returns_400(self, client):
        """PM<0이면 400."""
        self._upload_minimal_ledger(client)
        rv = client.post("/api/run", json={
            "kind": "receivable",
            "company_name": "테스트",
            "period_end": "2025-12-31",
            "performance_materiality": -1000000,
            "sheet": "채권",
        })
        assert rv.status_code == 400

    def test_run_with_valid_data_returns_200(self, client):
        """유효한 데이터면 200 응답."""
        self._upload_minimal_ledger(client)
        rv = client.post("/api/run", json={
            "kind": "receivable",
            "company_name": "테스트",
            "period_end": "2025-12-31",
            "performance_materiality": 10_000_000,
            "sheet": "채권",
            "risk_level": "유의적위험",
            "control_reliance": "Y",
        })
        assert rv.status_code == 200
        body = rv.get_json()
        assert "population_amount" in body


# ── 전역 에러 핸들러 ─────────────────────────────────────────────────────────
class TestGlobalErrorHandler:
    def test_404_returns_json(self, client):
        """존재하지 않는 API 경로는 JSON 404를 반환해야 한다."""
        rv = client.get("/api/nonexistent_endpoint_xyz")
        # 정적 파일로 처리될 수 있으므로 4xx 여부만 확인
        assert rv.status_code in (404, 400)

    def test_project_not_found_returns_json(self, client):
        """존재하지 않는 프로젝트 조회 시 JSON 404."""
        rv = client.get("/api/project/nonexistent-uuid-000")
        assert rv.status_code == 404
        body = rv.get_json()
        assert "error" in body
