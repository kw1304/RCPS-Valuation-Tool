from pathlib import Path
import io

# rapidocr 엔진은 초기화 비용이 있으므로 모듈 레벨 lazy singleton 으로 1회만 생성
_ENGINE = None


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _reconstruct_lines(items, y_tol=12):
    """
    OCR 인식 박스를 좌표 기반으로 논리적 라인으로 재구성한다.
    items: list of (x0, y0, text). y 기준으로 라인 클러스터링, 각 라인은 x 순 정렬.
    extract_rows 와 동일한 아이디어.
    """
    items = sorted(items, key=lambda t: (t[1], t[0]))
    lines, cur, cur_y = [], [], None
    for x0, y0, txt in items:
        if cur_y is None or abs(y0 - cur_y) <= y_tol:
            cur.append((x0, txt))
            cur_y = y0 if cur_y is None else cur_y
        else:
            lines.append(" ".join(t for _, t in sorted(cur)))
            cur = [(x0, txt)]
            cur_y = y0
    if cur:
        lines.append(" ".join(t for _, t in sorted(cur)))
    return "\n".join(lines)


def ocr_pdf(path: Path, lang: str = "korean") -> dict:
    """
    스캔 PDF → OCR 텍스트. 시스템 바이너리(poppler/tesseract) 불필요.
    PyMuPDF(fitz) 로 페이지 렌더링 + rapidocr-onnxruntime 로 OCR.

    Args:
        path: PDF 파일 경로
        lang: 호환성 유지용 인자 (rapidocr 은 다국어 모델이라 미사용)

    Returns:
        dict with keys:
            - text: OCR로 추출된 텍스트 (좌표 기반 라인 재구성)
            - pages: OCR 처리된 페이지 수
            - error: 오류 메시지 (있을 경우)
    """
    try:
        import fitz  # noqa: F401  (PyMuPDF)
        import numpy as np
        from PIL import Image
    except ImportError as e:
        return {"text": "", "pages": 0, "error": f"OCR deps missing: {e}"}

    try:
        engine = _get_engine()
    except Exception as e:
        return {"text": "", "pages": 0, "error": f"rapidocr init failed: {e}"}

    try:
        doc = fitz.open(str(path))
    except Exception as e:
        return {"text": "", "pages": 0, "error": f"fitz open failed: {e}"}

    parts = []
    n = 0
    for page in doc:
        n += 1
        try:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            arr = np.array(img)
            result, _ = engine(arr)
            if not result:
                continue
            items = []
            for box, txt, score in result:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                items.append((min(xs), min(ys), txt))
            parts.append(_reconstruct_lines(items))
        except Exception as e:
            parts.append(f"[OCR page {n} error: {e}]")

    return {"text": "\n".join(parts), "pages": n}
