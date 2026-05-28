from pathlib import Path


def ocr_pdf(path: Path, lang: str = "kor+eng") -> dict:
    """
    스캔 PDF → OCR 텍스트. pdf2image + pytesseract 필요.

    Args:
        path: PDF 파일 경로
        lang: Tesseract 언어 코드 (기본값: "kor+eng")

    Returns:
        dict with keys:
            - text: OCR로 추출된 텍스트
            - pages: OCR 처리된 페이지 수
            - error: 오류 메시지 (있을 경우)
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        return {"text": "", "pages": 0, "error": "OCR deps missing"}

    text_parts = []
    try:
        images = convert_from_path(str(path), dpi=200)
    except Exception as e:
        return {"text": "", "pages": 0, "error": f"pdf2image failed: {str(e)}"}

    for img in images:
        # 회전 보정 단순 휴리스틱: orientation detection
        try:
            osd = pytesseract.image_to_osd(img)
            rot = 0
            for line in osd.splitlines():
                if line.startswith("Rotate:"):
                    rot = int(line.split(":")[1].strip())
                    break
            if rot:
                img = img.rotate(-rot, expand=True)
        except Exception:
            pass

        try:
            text = pytesseract.image_to_string(img, lang=lang)
            text_parts.append(text)
        except Exception as e:
            text_parts.append(f"[OCR Error: {str(e)}]")

    return {"text": "\n".join(text_parts), "pages": len(images)}
