"""PDF 텍스트 추출 — pdfplumber 1차, OCR 폴백 (Week 4: tables 전달 지원).

품질 판정 기준:
  - 페이지당 추출 문자 < 50자 → 이미지 기반 PDF 로 판단 → OCR 시도
  - (cid:X) 패턴 다수 → 인코딩 불량 폰트 → OCR 폴백
  - OCR 불가(Tesseract 미설치) → method="failed", confidence=0, 경고 반환
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("cc_sampling.pdf")

_CID_PATTERN = re.compile(r"\(cid:\d+\)")


@dataclass
class ExtractResult:
    pages: list[str]          # 페이지별 텍스트 (index 0 = 1페이지)
    method: str               # "pdfplumber" | "ocr" | "failed" | "failed_ocr_not_installed"
    confidence: float         # 0.0 ~ 1.0
    warnings: list[str] = field(default_factory=list)
    tables: list[list[list]] = field(default_factory=list)  # pdfplumber tables (표 파싱용)

    @property
    def full_text(self) -> str:
        return "\n".join(self.pages)

    @property
    def ok(self) -> bool:
        return self.method not in ("failed", "failed_ocr_not_installed") and bool(self.full_text.strip())


_MIN_CHARS_PER_PAGE = 50
_MAX_CID_RATIO = 0.3  # (cid:X) 비율이 30% 초과 → 인코딩 불량 폰트


def _has_encoding_corruption(text: str) -> bool:
    """(cid:X) 패턴이 전체 텍스트의 30% 초과이면 인코딩 불량."""
    if not text:
        return False
    cid_count = len(_CID_PATTERN.findall(text))
    total_tokens = len(text.split())
    if total_tokens == 0:
        return False
    return cid_count / total_tokens > _MAX_CID_RATIO


def extract_text(pdf_path: Path) -> ExtractResult:
    """PDF에서 텍스트와 표를 추출한다.

    1. pdfplumber로 텍스트 layer + 표 추출 시도
    2. 텍스트가 빈약(페이지 평균 < 50자) 또는 인코딩 불량이면 OCR 폴백
    3. tables는 항상 pdfplumber 결과를 반환 (OCR 폴백 시에도)
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
    all_tables: list[list[list]] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages.append(text)
                # 표 추출 — 인코딩 불량 폰트도 표 구조는 KRW 숫자 포함 가능
                try:
                    tbls = page.extract_tables() or []
                    all_tables.extend(tbls)
                except Exception:
                    pass
    except Exception as exc:
        log.warning("pdfplumber 추출 오류: %s", exc)
        return ExtractResult(pages=[], method="failed", confidence=0.0, warnings=[str(exc)])

    total_chars = sum(len(p) for p in pages)
    avg_chars = total_chars / max(len(pages), 1)
    full_text = "\n".join(pages)

    # 인코딩 불량 감지 (CC-12 케이스)
    if _has_encoding_corruption(full_text):
        log.info("인코딩 불량 폰트 감지 (cid:X 패턴) — OCR 폴백 시도")
        from .ocr import extract_text_ocr
        ocr_result = extract_text_ocr(pdf_path)
        if ocr_result.ok:
            ocr_result.tables = all_tables  # pdfplumber 표는 유지
            return ocr_result
        # OCR도 실패 — 텍스트 레이어 반환 (불량이라도)
        return ExtractResult(
            pages=pages, method="failed", confidence=0.0,
            warnings=["인코딩 불량 폰트이며 OCR도 실패했습니다."] + ocr_result.warnings,
            tables=all_tables,
        )

    if avg_chars >= _MIN_CHARS_PER_PAGE:
        # 텍스트 layer 품질 충분
        confidence = min(1.0, avg_chars / 300)
        return ExtractResult(
            pages=pages, method="pdfplumber", confidence=confidence,
            tables=all_tables,
        )

    # 빈약 → OCR 폴백
    log.info("pdfplumber 텍스트 빈약 (평균 %.0f자) — OCR 폴백 시도", avg_chars)
    from .ocr import extract_text_ocr
    ocr_result = extract_text_ocr(pdf_path)
    if ocr_result.ok:
        ocr_result.tables = all_tables
        return ocr_result

    # OCR도 실패 → pdfplumber 결과라도 반환 (비어있어도)
    warn_msg = "텍스트 layer 빈약하고 OCR도 실패했습니다."
    return ExtractResult(
        pages=pages,
        method="failed",
        confidence=0.0,
        warnings=[warn_msg] + ocr_result.warnings,
        tables=all_tables,
    )
