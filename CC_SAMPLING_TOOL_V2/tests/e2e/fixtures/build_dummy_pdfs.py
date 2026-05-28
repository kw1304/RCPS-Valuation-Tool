"""더미 PDF 회신 생성. Task 12의 dummy_ledger 표본과 매칭.

실행: python tests/e2e/fixtures/build_dummy_pdfs.py
"""
from __future__ import annotations
from pathlib import Path

try:
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase import pdfmetrics
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    _HAS_RL = True
except ImportError:
    _HAS_RL = False


OUT = Path(__file__).parent


def make_pdf(filename: str, text: str) -> None:
    if not _HAS_RL:
        print(f"skip {filename} (reportlab missing)")
        return
    c = canvas.Canvas(str(OUT / filename))
    c.setFont("HYSMyeongJo-Medium", 11)
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()


if __name__ == "__main__":
    # AR000~004 = RP forced. match scenarios.
    make_pdf("conf_AR000_match.pdf",
             "회신서\n조회처: 고객사000\n잔액: 1,000,000원")
    make_pdf("conf_AR001_match.pdf",
             "조회처: 고객사001\n2025-12-31 기준 잔액 500,000원")
    make_pdf("conf_AR002_disc.pdf",
             "조회처: 고객사002\n잔액 800,000원")
    print("dummy PDFs built at:", OUT)
