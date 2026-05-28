from pathlib import Path
import pdfplumber


def extract_text_and_tables(path: Path) -> dict:
    """
    Digital PDF 우선 시도. 실패 시 OCR fallback (별도 호출자가 처리).

    Args:
        path: PDF 파일 경로

    Returns:
        dict with keys:
            - text: 추출된 텍스트 (페이지별로 개행으로 구분)
            - tables: 추출된 테이블 목록 (각 테이블은 list[list[str]])
            - pages: 텍스트가 추출된 페이지 수
    """
    text_parts: list[str] = []
    tables: list[list[list]] = []

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                text_parts.append(t)
            for tab in (page.extract_tables() or []):
                tables.append(tab)

    return {
        "text": "\n".join(text_parts),
        "tables": tables,
        "pages": len(text_parts),
    }
