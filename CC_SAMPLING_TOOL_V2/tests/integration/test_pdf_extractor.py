import pytest
from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text, PdfExtractError


def _make_test_pdf(path: Path, text: str) -> None:
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    c = canvas.Canvas(str(path))
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()


def test_extract_text_from_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    _make_test_pdf(pdf, "Hello World\nLine 2")
    text = extract_text(pdf)
    assert "Hello World" in text
    assert "Line 2" in text


def test_extract_missing_file_raises(tmp_path):
    with pytest.raises(PdfExtractError):
        extract_text(tmp_path / "nonexistent.pdf")


def test_extract_empty_pdf_returns_empty(tmp_path):
    pdf = tmp_path / "empty.pdf"
    _make_test_pdf(pdf, "")
    text = extract_text(pdf)
    assert text == "" or text.strip() == ""
