"""AC5 하나 §9 다순위(설정순위)·선순위설정금액 행 완전 포착 회귀 테스트.

참고조서(정답) AC5 시트는 부동산 담보를 **설정순위(rank)별로 별도 행**으로 적는다:
  - 순위3: 감정 2,634,000,000 / 설정 12,000,000,000
  - 순위6: 감정 2,634,000,000 / 설정 53,340,000,000 / 선순위설정금액 51,000,000,000
즉 한 물건이 2개 행. 참고조서 AC5 금액합은 감정+설정+**선순위설정금액**을
모든 순위 행에 걸쳐 합산한다(선순위설정금액 컬럼이 51bn×10 = 510B 를 운반).

따라서 비교 하니스(tools/compare_to_reference)는 AC5 금액 필드로
book_amount + appraised_amount 뿐 아니라 **senior_lien** 도 합산해야
정답 컬럼과 정합한다. 이 테스트가 RED 이면 senior_lien 누락(510B 갭)이다.
"""
import glob
from pathlib import Path

import pytest

from src.infrastructure.pdf.extractor import extract_rows
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5

ROOT = Path(__file__).resolve().parents[2]
HANA = glob.glob(str(ROOT / "INPUT" / "온라인" / "*KEB하나*.pdf"))


@pytest.mark.skipif(not HANA, reason="하나 회신본 PDF 없음")
def test_hana_section9_captures_both_rank_rows_and_senior_lien():
    """하나 §9 부동산 담보 — 순위3(설정 12bn)·순위6(설정 53.34bn, 선순위 51bn) 둘 다."""
    blocks = split_sections(extract_rows(Path(HANA[0])))
    recs = parse_ac5(blocks.get(9, ""), "BC", "하나", "provided")

    appraised = [int(r.appraised_amount) for r in recs if r.appraised_amount is not None]
    seniors = [int(r.senior_lien) for r in recs if r.senior_lien is not None]

    # 순위6 행: 설정금액 53,340,000,000 이 살아 있어야 한다(병합/누락 금지).
    assert 53_340_000_000 in appraised, "53.34bn 설정금액(순위6) 행이 누락/병합됨"
    # 순위3 행: 설정금액 12,000,000,000 도 별개로 존재.
    assert 12_000_000_000 in appraised, "12bn 설정금액(순위3) 행이 누락됨"
    # 선순위설정금액 51,000,000,000 이 물건마다 채워져야 한다.
    assert 51_000_000_000 in seniors, "선순위설정금액 51bn 미포착"
    # 물건 10개 × 순위6 행 → 선순위 51bn 가 10건.
    assert seniors.count(51_000_000_000) == 10, (
        f"선순위 51bn 행 수 {seniors.count(51_000_000_000)} != 10")


@pytest.mark.skipif(not HANA, reason="하나 회신본 PDF 없음")
def test_hana_stock_collateral_has_no_senior_lien():
    """상장주식/주식 담보는 선순위설정금액을 잡지 않는다.

    참고조서 선순위 설정금액 컬럼은 **부동산(집합건물상가 등) 담보에만** 51bn 을
    적는다. 주식 담보의 후순위(순위2) 행 뒤 (KRW)59,400,000,000 은 동일 발행주식의
    선순위(순위1) 설정금액으로 이미 설정금액 컬럼에 공시된 값이라, 선순위 컬럼에는
    중복 기재하지 않는다. 따라서 주식 담보 record 의 senior_lien 은 None 이어야
    한다(아니면 59.4bn·143.99bn 이중계상 → AC5 과대 오차)."""
    blocks = split_sections(extract_rows(Path(HANA[0])))
    recs = parse_ac5(blocks.get(9, ""), "BC", "하나", "provided")
    stock = [r for r in recs if "주식" in (r.collateral_type or "")]
    assert stock, "상장주식 담보 record 가 없음 — 픽스처/파싱 회귀"
    for r in stock:
        assert r.senior_lien is None, (
            f"주식 담보 {r.collateral_type} 에 선순위 {r.senior_lien} 가 잘못 설정됨")
    # 부동산(집합건물상가) 담보는 여전히 선순위 51bn 을 보유.
    realty = [r for r in recs if r.senior_lien is not None]
    assert all("주식" not in (r.collateral_type or "") for r in realty)
    assert any(int(r.senior_lien) == 51_000_000_000 for r in realty)


def test_harness_ac5_total_counts_senior_lien():
    """비교 하니스 AC5 금액 필드에 senior_lien 이 포함되어야 한다(510B 갭의 근원)."""
    import tools.compare_to_reference as h
    assert "senior_lien" in h._TOOL_FIELDS["AC5"], (
        "하니스 AC5 가 senior_lien 을 합산하지 않아 참고조서 선순위설정금액과 불일치")
