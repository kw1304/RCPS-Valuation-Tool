import glob
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.section_splitter import split_sections

ROOT = Path(__file__).resolve().parents[2]
PDFS = sorted(glob.glob(str(ROOT / "INPUT" / "온라인" / "*.pdf")))


@pytest.mark.skipif(not PDFS, reason="INPUT PDFs 없음")
def test_every_electronic_pdf_identified_and_split():
    profile = FormProfile.load()
    for p in PDFS:
        t = extract_rows(Path(p))
        if len(t.strip()) < 80:
            t = ocr_pdf(Path(p))["text"]
        fam = identify_form(t)
        assert fam != "unknown", f"{Path(p).name} → unknown (식별 실패)"
        blocks = split_sections(t)
        assert blocks, f"{Path(p).name} → 섹션 분할 0"
        assert any(profile.route(fam, n) for n in blocks), f"{Path(p).name} 라우팅 0"
