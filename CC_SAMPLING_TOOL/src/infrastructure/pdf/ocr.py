"""OCR 폴백 — pdfplumber 이미지 + pytesseract.

Tesseract binary 미설치 시 graceful fail:
  method="failed_ocr_not_installed", confidence=0, 경고 메시지 포함.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .extractor import ExtractResult

log = logging.getLogger("cc_sampling.pdf.ocr")

_OCR_LANG = "kor+eng"


def extract_text_ocr(pdf_path: Path) -> ExtractResult:
    """PDF 페이지를 이미지로 변환 후 pytesseract OCR 적용."""
    # 의존성 체크
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return ExtractResult(
            pages=[], method="failed_ocr_not_installed", confidence=0.0,
            warnings=["pdfplumber 패키지 미설치"],
        )

    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore  # noqa: F401
    except ImportError:
        return ExtractResult(
            pages=[], method="failed_ocr_not_installed", confidence=0.0,
            warnings=["pytesseract 또는 Pillow 패키지 미설치 — pip install pytesseract Pillow"],
        )

    # Tesseract binary 가용 여부 확인 (빠른 probe)
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return ExtractResult(
            pages=[], method="failed_ocr_not_installed", confidence=0.0,
            warnings=[
                "Tesseract OCR 엔진이 설치되지 않았습니다. "
                "https://github.com/UB-Mannheim/tesseract/wiki 에서 설치 후 재시도하세요."
            ],
        )

    pages: list[str] = []
    warnings: list[str] = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    # pdfplumber → PIL Image 변환 (72 → 200 dpi)
                    img = page.to_image(resolution=200).original
                    text = pytesseract.image_to_string(img, lang=_OCR_LANG)
                    pages.append(text)
                except Exception as exc:
                    log.warning("OCR 페이지 %d 실패: %s", i + 1, exc)
                    pages.append("")
                    warnings.append(f"p{i+1} OCR 오류: {exc}")
    except Exception as exc:
        return ExtractResult(
            pages=[], method="failed", confidence=0.0, warnings=[str(exc)]
        )

    total_chars = sum(len(p) for p in pages)
    if total_chars == 0:
        return ExtractResult(
            pages=pages, method="failed", confidence=0.0,
            warnings=warnings + ["OCR 결과가 모두 비어 있습니다."],
        )

    confidence = min(0.85, total_chars / (len(pages) * 300))
    return ExtractResult(pages=pages, method="ocr", confidence=confidence, warnings=warnings)
