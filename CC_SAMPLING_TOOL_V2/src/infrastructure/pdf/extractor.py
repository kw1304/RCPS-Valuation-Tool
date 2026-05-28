"""PDF 텍스트층 추출 (pdfplumber).

설계서 §6.1 [5]. OCR은 별도 모듈 (Phase 3 범위 밖).
"""
from __future__ import annotations
from pathlib import Path
import pdfplumber


class PdfExtractError(Exception):
    pass


def extract_text(path: Path) -> str:
    """텍스트층 합치기 (페이지 구분 \\n으로)."""
    p = Path(path)
    if not p.exists():
        raise PdfExtractError(f"file not found: {p}")
    try:
        with pdfplumber.open(p) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
            return "\n".join(pages)
    except Exception as e:
        raise PdfExtractError(f"pdfplumber failed on {p}: {e}") from e
