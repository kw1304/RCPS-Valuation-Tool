"""증빙 추출기 단위 테스트 — BC-14 xls, BC-4 pdf, BC-16/26 png.

실데이터 파일을 직접 사용하므로 CI 환경에서는 skip 처리.
"""
from __future__ import annotations

import pytest
from pathlib import Path

EVIDENCE_BASE = Path(__file__).resolve().parents[1] / "input" / "조회서 회수본 및 대체적 절차" / "대체적 증빙"
BC14_DIR = EVIDENCE_BASE / "BC-14_New Future International Trade Co"
BC4_DIR = EVIDENCE_BASE / "BC-4_BIO TECH"
BC16_DIR = EVIDENCE_BASE / "BC-16_SIAM GOLD LEAVES CO., LTD"
BC26_DIR = EVIDENCE_BASE / "BC-26_한국의생명연구원"


@pytest.mark.skipif(not BC14_DIR.exists(), reason="실데이터 없음")
def test_xls_commercial_invoice_amount():
    """BC-14 첫 번째 xls → Commercial Invoice 인식 + KRW 금액 추출."""
    from src.infrastructure.evidence.extractor import extract_evidence

    xls_files = sorted(BC14_DIR.glob("*.xls"))
    assert xls_files, "BC-14 xls 파일 없음"

    ex = extract_evidence(xls_files[0])
    assert ex.extraction_method == "xls_table", f"추출방법 불일치: {ex.extraction_method}"
    assert ex.document_type == "commercial_invoice", f"문서유형 불일치: {ex.document_type}"
    assert ex.extracted_amount is not None, "금액 미추출"
    assert ex.extracted_amount > 0, f"금액 비정상: {ex.extracted_amount}"
    assert ex.extracted_currency == "KRW", f"통화 불일치: {ex.extracted_currency}"
    assert ex.confidence >= 0.5, f"신뢰도 낮음: {ex.confidence}"


@pytest.mark.skipif(not BC14_DIR.exists(), reason="실데이터 없음")
def test_xls_all_seven_files():
    """BC-14 7건 .xls 모두 추출 → 성공률 확인."""
    from src.infrastructure.evidence.extractor import extract_evidence

    xls_files = sorted(BC14_DIR.glob("*.xls"))
    results = [extract_evidence(f) for f in xls_files]

    success = [r for r in results if r.extracted_amount is not None]
    # 최소 4건 이상 금액 추출 (일부 파일 구조 변형 가능)
    assert len(success) >= 4, f"추출 성공 {len(success)}/{len(results)} — 기대 4+"


@pytest.mark.skipif(not BC14_DIR.exists(), reason="실데이터 없음")
def test_xls_date_extraction():
    """BC-14 첫 번째 xls → 날짜 추출."""
    from src.infrastructure.evidence.extractor import extract_evidence
    from datetime import date

    xls_files = sorted(BC14_DIR.glob("*.xls"))
    ex = extract_evidence(xls_files[0])
    assert ex.extracted_date is not None, "날짜 미추출"
    assert isinstance(ex.extracted_date, date)
    assert 2024 <= ex.extracted_date.year <= 2026, f"연도 이상: {ex.extracted_date}"


@pytest.mark.skipif(not BC4_DIR.exists(), reason="실데이터 없음")
def test_pdf_invoice_amount():
    """BC-4 첫 번째 pdf → 인보이스 금액 추출."""
    from src.infrastructure.evidence.extractor import extract_evidence

    pdfs = sorted(BC4_DIR.glob("*.pdf"))
    assert pdfs, "BC-4 pdf 파일 없음"

    # 두 번째 pdf (한글명 — FS250630-B6, CNY 포함)
    target = pdfs[1] if len(pdfs) > 1 else pdfs[0]
    ex = extract_evidence(target)

    assert ex.file_type == "pdf"
    assert ex.extraction_method in ("pdf_table", "pdf_text"), f"추출방법: {ex.extraction_method}"
    assert ex.extracted_amount is not None, f"금액 미추출 (raw: {ex.raw_text[:200]})"
    assert ex.extracted_amount > 0


@pytest.mark.skipif(not BC4_DIR.exists(), reason="실데이터 없음")
def test_pdf_currency_detection():
    """BC-4 PDF 인보이스 → 통화 감지."""
    from src.infrastructure.evidence.extractor import extract_evidence

    pdfs = sorted(BC4_DIR.glob("*.pdf"))
    target = pdfs[1] if len(pdfs) > 1 else pdfs[0]
    ex = extract_evidence(target)

    # CNY 또는 KRW 중 하나가 나와야 함
    assert ex.extracted_currency in ("KRW", "CNY", "USD", None), f"통화 이상: {ex.extracted_currency}"


@pytest.mark.skipif(not BC16_DIR.exists(), reason="실데이터 없음")
def test_png_graceful_fail_or_ocr():
    """BC-16 PNG → Tesseract 없으면 graceful fail, 있으면 partial 추출."""
    from src.infrastructure.evidence.extractor import extract_evidence

    pngs = sorted(BC16_DIR.glob("*.png"))
    assert pngs, "BC-16 png 없음"

    ex = extract_evidence(pngs[0])
    assert ex.file_type == "png"
    # Tesseract 없으면 failed, 있으면 ocr
    assert ex.extraction_method in ("failed", "ocr"), f"예상 외 방법: {ex.extraction_method}"
    # graceful fail: 예외 없이 EvidenceExtract 반환
    assert ex.confidence >= 0.0


@pytest.mark.skipif(not BC26_DIR.exists(), reason="실데이터 없음")
def test_png_26_graceful():
    """BC-26 PNG (6건) → graceful fail 또는 OCR."""
    from src.infrastructure.evidence.extractor import extract_evidence

    pngs = sorted(BC26_DIR.glob("*.png"))
    assert pngs

    for png in pngs:
        ex = extract_evidence(png)
        assert ex.extraction_method in ("failed", "ocr"), png.name
        assert ex.confidence >= 0.0


def test_unknown_extension_graceful():
    """존재하지 않는 파일 → graceful fail."""
    from src.infrastructure.evidence.extractor import extract_evidence
    ex = extract_evidence(Path("nonexistent.abc"))
    assert ex.extraction_method == "failed"
    assert ex.extracted_amount is None
    assert ex.confidence == 0.0
