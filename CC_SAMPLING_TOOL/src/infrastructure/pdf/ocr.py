"""OCR 폴백 — pdfplumber 이미지 + pytesseract (Week 4: 전처리 강화).

전처리 파이프라인:
  1. pdfplumber → PIL Image (300 dpi)
  2. Grayscale 변환
  3. Otsu binarization (PIL.ImageOps.autocontrast + 임계값 이진화)
  4. Deskew (pytesseract OSD 활용 — 5° 이상 기울기 보정)
  5. pytesseract OCR (kor+eng)

Tesseract binary 미설치 시 graceful fail:
  method="failed_ocr_not_installed", confidence=0, 경고 메시지 포함.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from .extractor import ExtractResult

log = logging.getLogger("cc_sampling.pdf.ocr")

_OCR_LANG = "kor+eng"
_OCR_DPI = 300


def _preprocess_image(img):
    """OCR 전처리: Grayscale → Otsu binarization → Deskew (선택적).

    Args:
        img: PIL.Image.Image 원본

    Returns:
        전처리된 PIL.Image.Image
    """
    from PIL import Image, ImageOps, ImageFilter  # type: ignore

    # 1. Grayscale
    if img.mode != "L":
        img = img.convert("L")

    # 2. 이미지 선명화 (스캔 품질 향상)
    img = img.filter(ImageFilter.SHARPEN)

    # 3. Otsu-style binarization: autocontrast → threshold
    img = ImageOps.autocontrast(img, cutoff=2)

    # PIL에서 Otsu 직접 지원 안 하므로 히스토그램 기반 임계값 계산
    hist = img.histogram()
    total_pixels = sum(hist)
    if total_pixels > 0:
        # Otsu's method
        sum_total = sum(i * hist[i] for i in range(256))
        sum_bg, weight_bg, max_var, threshold = 0.0, 0, 0.0, 128
        for t in range(256):
            weight_bg += hist[t]
            if weight_bg == 0:
                continue
            weight_fg = total_pixels - weight_bg
            if weight_fg == 0:
                break
            sum_bg += t * hist[t]
            mean_bg = sum_bg / weight_bg
            mean_fg = (sum_total - sum_bg) / weight_fg
            var = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
            if var > max_var:
                max_var = var
                threshold = t
    else:
        threshold = 128

    img = img.point(lambda x: 255 if x > threshold else 0, "L")

    return img


def _deskew_image(img, pytesseract):
    """OSD 기반 기울기 보정 (5° 이상일 때만 적용)."""
    try:
        from PIL import Image  # type: ignore
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        angle = osd.get("rotate", 0)
        if abs(angle) >= 5:
            log.debug("이미지 기울기 보정: %d°", angle)
            img = img.rotate(-angle, expand=True, fillcolor=255)
    except Exception:
        pass  # OSD 실패 시 원본 유지
    return img


def extract_text_ocr(pdf_path: Path) -> ExtractResult:
    """PDF 페이지를 이미지로 변환 후 전처리 + pytesseract OCR 적용."""
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

    # Tesseract binary 가용 여부 확인
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
                    # 300 dpi로 이미지 변환
                    pil_img = page.to_image(resolution=_OCR_DPI).original

                    # 전처리
                    pil_img = _preprocess_image(pil_img)

                    # Deskew (OSD)
                    pil_img = _deskew_image(pil_img, pytesseract)

                    # OCR 실행
                    text = pytesseract.image_to_string(
                        pil_img,
                        lang=_OCR_LANG,
                        config="--oem 3 --psm 6",  # LSTM + 균일 블록 레이아웃
                    )
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

    # 신뢰도: 페이지당 평균 글자 수 기반 (300자면 충분)
    confidence = min(0.85, total_chars / (len(pages) * 300))
    return ExtractResult(pages=pages, method="ocr", confidence=confidence, warnings=warnings)
