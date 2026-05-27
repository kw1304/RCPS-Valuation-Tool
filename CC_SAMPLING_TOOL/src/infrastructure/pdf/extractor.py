"""PDF 텍스트 추출 — pdfplumber 1차, OCR 폴백.

품질 판정 기준:
  - 페이지당 추출 문자 < 50자 → 이미지 기반 PDF 로 판단 → OCR 시도
  - OCR 불가(Tesseract 미설치) → method="failed", confidence=0, 경고 반환
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("cc_sampling.pdf")


@dataclass
class ExtractResult:
    pages: list[str]          # 페이지별 텍스트 (index 0 = 1페이지)
    method: str               # "pdfplumber" | "ocr" | "failed" | "failed_ocr_not_installed"
    confidence: float         # 0.0 ~ 1.0
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(self.pages)

    @property
    def ok(self) -> bool:
        return self.method not in ("failed", "failed_ocr_not_installed") and bool(self.full_text.strip())


_MIN_CHARS_PER_PAGE = 50


def extract_text(pdf_path: Path) -> ExtractResult:
    """PDF에서 텍스트를 추출한다.

    1. pdfplumber 로 텍스트 layer 추출 시도
    2. 텍스트가 빈약(페이지 평균 < _MIN_CHARS_PER_PAGE)하면 OCR 폴백
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return ExtractResult(
            pages=[],
            method="failed",
            confidence=0.0,
            warnings=["pdfplumber 패키지 미설치 — pip install pdfplumber"],
        )

    pages: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages.append(text)
    except Exception as exc:
        log.warning("pdfplumber 추출 오류: %s", exc)
        return ExtractResult(pages=[], method="failed", confidence=0.0, warnings=[str(exc)])

    total_chars = sum(len(p) for p in pages)
    avg_chars = total_chars / max(len(pages), 1)

    if avg_chars >= _MIN_CHARS_PER_PAGE:
        # 텍스트 layer 품질 충분
        confidence = min(1.0, avg_chars / 300)
        return ExtractResult(pages=pages, method="pdfplumber", confidence=confidence)

    # 빈약 → OCR 폴백
    log.info("pdfplumber 텍스트 빈약 (평균 %.0f자) — OCR 폴백 시도", avg_chars)
    from .ocr import extract_text_ocr  # noqa: PLC0415  (지연 임포트)
    ocr_result = extract_text_ocr(pdf_path)
    if ocr_result.ok:
        return ocr_result

    # OCR도 실패 → pdfplumber 결과라도 반환 (비어있어도)
    warn_msg = "텍스트 layer 빈약하고 OCR도 실패했습니다."
    return ExtractResult(
        pages=pages,
        method="failed",
        confidence=0.0,
        warnings=[warn_msg] + ocr_result.warnings,
    )
