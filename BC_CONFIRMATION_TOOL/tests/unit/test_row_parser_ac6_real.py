"""AC6 value-level golden test: 실제 bank.txt fixture 기반.
phantom sentinel 행(99991231 000000000 00000000)이 record로 새어나오지 않음을 고정."""
from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.row_parsers.ac6_bills import parse_ac6

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections" / "bank.txt"


def _ac6_sections():
    prof = FormProfile.load()
    return [n for n in range(1, 11) if (r := prof.route("bank", n)) and r.get("ac") == "AC6"]


def test_ac6_no_phantom_sentinel_rows():
    text = FIX.read_text(encoding="utf-8")
    blocks = split_sections(text)
    secs = _ac6_sections()
    assert secs, "bank 가 AC6 로 라우팅되는 섹션이 있어야 함 (7,8,10)"

    all_recs = []
    for n in secs:
        if n not in blocks:
            continue
        all_recs += parse_ac6(blocks[n], bc_no="BC-1", bank="국민은행", direction="received")

    # 핵심 1: count==0 AND balance==0 인 phantom record 없음
    for r in all_recs:
        assert not (r.count == 0 and r.balance == 0), (
            f"phantom sentinel record 새어나옴: kind={r.kind} count={r.count} balance={r.balance}"
        )

    # 핵심 2: sentinel 99991231 placeholder 행이 record kind 로 잡히지 않음
    for r in all_recs:
        assert "99991231" not in r.kind

    # 핵심 3: sec7(어음·수표 본 섹션, sentinel 99991231 행 보유)은 실제 거래 0건 → phantom 제거 확인
    if 7 in blocks:
        sec7 = parse_ac6(blocks[7], bc_no="BC-1", bank="국민은행", direction="received")
        assert sec7 == [], f"sec7 sentinel-only 섹션은 0건이어야 함, got {[r.kind for r in sec7]}"
