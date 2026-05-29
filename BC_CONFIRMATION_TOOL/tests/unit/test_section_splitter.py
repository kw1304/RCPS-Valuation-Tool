from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"

def test_bank_splits_into_numbered_blocks():
    text = (FIX / "bank.txt").read_text(encoding="utf-8")
    blocks = split_sections(text)
    assert 1 in blocks and 2 in blocks and 10 in blocks
    assert "예금" in blocks[1] or "통장" in blocks[1]

def test_block_boundary_no_leak():
    text = (FIX / "bank.txt").read_text(encoding="utf-8")
    blocks = split_sections(text)
    assert "대출" in blocks[2] or "한도" in blocks[2]

def test_empty_text_returns_empty():
    assert split_sections("") == {}
