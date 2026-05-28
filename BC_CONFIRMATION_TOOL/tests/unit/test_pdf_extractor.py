from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text_and_tables


def test_extract_digital_pdf():
    sample = Path("C:/Claude/BC_CONFIRMATION_TOOL/INPUT/온라인")
    if not sample.exists():
        import pytest
        pytest.skip("샘플 PDF 없음")
    pdfs = list(sample.glob("*.pdf"))
    if not pdfs:
        import pytest
        pytest.skip("샘플 PDF 없음")
    r = extract_text_and_tables(pdfs[0])
    assert "text" in r
    assert isinstance(r["text"], str)
    assert len(r["text"]) > 100
    assert "tables" in r
