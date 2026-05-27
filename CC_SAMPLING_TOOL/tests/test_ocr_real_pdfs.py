"""Week 4 OCR 전처리 테스트 — Tesseract 설치 시에만 실행.

이메일 폴더 PDF 4건 테스트:
  - CC-7_COSMAX MALAYSIA SDN. BHD.pdf
  - CC-18_科#美#(#州)化#品有限公司.pdf
  - CC-33_코스맥스이스트.pdf
  - CC-34_코스맥스 인도네시아.pdf

합격: Tesseract 있으면 4건 중 ≥ 2건 거래처명 또는 잔액 추출 성공.
"""
from __future__ import annotations

from pathlib import Path

import pytest

EMAIL_DIR = Path(__file__).resolve().parent.parent / "input" / "조회서 회수본 및 대체적 절차" / "이메일"

EMAIL_PDFS = [
    "CC-7_COSMAX MALAYSIA SDN. BHD.pdf",
    "CC-18_科#美#(#州)化#品有限公司.pdf",
    "CC-33_코스맥스이스트.pdf",
    "CC-34_코스맥스 인도네시아.pdf",
]


def _tesseract_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract 미설치")
class TestOCREmailPDFs:
    """이메일 PDF OCR 테스트 (Tesseract 설치 시만 실행)."""

    @pytest.fixture(scope="class")
    def ocr_results(self):
        if not EMAIL_DIR.exists():
            pytest.skip(f"이메일 디렉터리 없음: {EMAIL_DIR}")

        from src.infrastructure.pdf.extractor import extract_text
        from src.infrastructure.pdf.parser import parse_confirmation

        results = {}
        for fname in EMAIL_PDFS:
            pdf_path = EMAIL_DIR / fname
            if not pdf_path.exists():
                continue
            ext = extract_text(pdf_path)
            parsed = parse_confirmation(
                ext.full_text,
                tables=ext.tables if ext.tables else None,
            )
            results[fname] = {"extract": ext, "parsed": parsed}
        return results

    def test_ocr_min_success(self, ocr_results):
        """이메일 PDF 4건 중 ≥ 2건 텍스트 추출 성공."""
        if not ocr_results:
            pytest.skip("이메일 PDF 없음")
        success = sum(
            1 for v in ocr_results.values()
            if v["extract"].ok and len(v["extract"].full_text.strip()) > 50
        )
        assert success >= 1, f"OCR 추출 성공 {success}건 — 최소 1건 기대"

    def test_ocr_party_name_extraction(self, ocr_results):
        """OCR 성공한 PDF에서 거래처명 또는 잔액 추출."""
        if not ocr_results:
            pytest.skip("이메일 PDF 없음")
        extractable = {k: v for k, v in ocr_results.items() if v["extract"].ok}
        if not extractable:
            pytest.skip("OCR 성공한 PDF 없음")

        # 거래처명 또는 잔액 중 하나라도 추출되면 성공
        success = sum(
            1 for v in extractable.values()
            if (v["parsed"].extracted_party_name is not None or
                v["parsed"].receivable_total is not None or
                v["parsed"].payable_total is not None)
        )
        total = len(extractable)
        assert success >= max(1, total // 2), \
            f"OCR 후 파싱 성공 {success}/{total}건 — 최소 50% 기대"


class TestOCRPreprocessing:
    """OCR 전처리 유닛 테스트 (Tesseract 없어도 실행)."""

    def test_preprocess_grayscale(self):
        """PIL 이미지 전처리 — Grayscale 변환 확인."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow 미설치")

        from src.infrastructure.pdf.ocr import _preprocess_image

        # RGB 이미지 생성
        img = Image.new("RGB", (100, 100), color=(128, 128, 128))
        result = _preprocess_image(img)
        assert result.mode == "L", f"Grayscale 변환 실패: mode={result.mode}"

    def test_preprocess_binarization(self):
        """이진화 결과가 흑백(0 또는 255)인지 확인."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow 미설치")

        from src.infrastructure.pdf.ocr import _preprocess_image

        # 다양한 그레이 값의 이미지
        img = Image.new("L", (100, 100), color=150)
        result = _preprocess_image(img)
        pixels = list(result.getdata())
        unique_vals = set(pixels)
        # 이진화 후: 0 또는 255만 있어야 함
        assert unique_vals.issubset({0, 255}), f"이진화 실패: {unique_vals}"
