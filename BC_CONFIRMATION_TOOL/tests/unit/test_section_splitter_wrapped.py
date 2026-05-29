import glob
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections

ROOT = Path(__file__).resolve().parents[2]

def _txt(substr):
    p=[x for x in glob.glob(str(ROOT/'INPUT'/'온라인'/'*.pdf')) if substr in x]
    if not p: pytest.skip(f'{substr} 없음')
    return extract_rows(Path(p[0]))

def test_section9_detected_kookmin():
    blocks = split_sections(_txt('국민은행'))
    assert 9 in blocks, f'§9 누락, got {sorted(blocks)}'
    # §8(어음) 은 '해당 거래 없음' → 담보 데이터(상장주식/보증)가 §8에 있으면 안 됨
    assert "상장주식" not in blocks.get(8, "")
    # §10(당좌) 여전히 잡혀야 (회귀)
    assert 10 in blocks

def test_section10_still_detected():
    blocks = split_sections(_txt('KEB하나'))
    assert 10 in blocks
    assert 9 in blocks
