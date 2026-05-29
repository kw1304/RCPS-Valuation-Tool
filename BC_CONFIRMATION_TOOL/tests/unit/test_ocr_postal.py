"""우편(스캔) PDF OCR 파이프라인 검증.

fitz 렌더 + rapidocr-onnxruntime (poppler/tesseract 불필요).

실측 관찰 (FY2025 에스트래픽/코스맥스 우편 36건):
- 스캔된 한국 표준 양식은 '번호 셀 빈 양식'에 데이터가 도장·수기로 채워진 형태로,
  rapidocr 기본 한글 모델은 작은 인쇄 한글 라벨을 거의 복원하지 못한다(hangul ~0).
- 신뢰성 있게 복원되는 것: 금액·숫자, 영문 양식 텍스트, 사업자번호, 날짜.
- 따라서 기관명 매칭은 OCR 텍스트가 아니라 파일명(parse_filename)에서 나온다.
- 이 테스트는 현실적으로 달성 가능한 것만 단언한다: 비어있지 않은 텍스트 +
  금액/숫자(감사인 manual-review 후보)가 표면화되는지.
OCR 은 느리므로 slow 마크. 라이브러리/샘플 없으면 skip.
"""
import glob
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_ocr_extracts_text_and_amounts():
    pytest.importorskip("fitz")
    pytest.importorskip("rapidocr_onnxruntime")
    from src.infrastructure.pdf.ocr import ocr_pdf

    g = glob.glob(str(ROOT / "INPUT" / "**" / "*엔지니어링공제조합*.pdf"), recursive=True)
    if not g:
        pytest.skip("샘플 없음")

    r = ocr_pdf(Path(g[0]))
    assert r["pages"] >= 1, r.get("error")
    # 스캔 PDF 에서 실제 텍스트가 나와야 한다 (이전: poppler/tesseract 부재로 0자)
    assert len(r["text"]) > 30, r.get("error")
    # 한국 표준 양식 스캔은 금액/숫자가 표면화된다 — manual-review 후보의 핵심
    assert re.search(r"\d[\d,.]{3,}", r["text"]), "금액/숫자 미검출"
