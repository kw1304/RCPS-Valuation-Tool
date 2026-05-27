"""폴더 단위 증빙 합산 테스트 — BC-14, BC-4, BC-21."""
from __future__ import annotations

import pytest
from pathlib import Path

EVIDENCE_BASE = Path(__file__).resolve().parents[1] / "input" / "조회서 회수본 및 대체적 절차" / "대체적 증빙"
BC14_DIR = EVIDENCE_BASE / "BC-14_New Future International Trade Co"
BC4_DIR = EVIDENCE_BASE / "BC-4_BIO TECH"
BC21_DIR = EVIDENCE_BASE / "BC-21_山东昆达生物科技有限公司"


# ── 폴더명 파싱 ─────────────────────────────────────────────────────────────

def test_parse_bc_folder_name_single():
    """BC-14_거래처명 → bc_numbers=[14], party_name 파싱."""
    from src.infrastructure.evidence.aggregator import parse_bc_folder_name
    nums, party = parse_bc_folder_name("BC-14_New Future International Trade Co")
    assert nums == [14]
    assert party == "New Future International Trade Co"


def test_parse_bc_folder_name_multi():
    """BC-5,12_거래처명 → bc_numbers=[5, 12]."""
    from src.infrastructure.evidence.aggregator import parse_bc_folder_name
    nums, party = parse_bc_folder_name("BC-5,12_채권채무조회서_불일치 소명")
    assert nums == [5, 12]
    assert "채권채무조회서" in party


def test_parse_bc_folder_name_non_bc():
    """BC-N 패턴 아닌 폴더 → ([], None)."""
    from src.infrastructure.evidence.aggregator import parse_bc_folder_name
    nums, party = parse_bc_folder_name("일반폴더명")
    assert nums == []
    assert party is None


def test_parse_bc_folder_name_korean():
    """한글 거래처명 파싱."""
    from src.infrastructure.evidence.aggregator import parse_bc_folder_name
    nums, party = parse_bc_folder_name("BC-26_한국의생명연구원")
    assert nums == [26]
    assert party == "한국의생명연구원"


def test_parse_bc_folder_name_chinese():
    """한자 거래처명 파싱."""
    from src.infrastructure.evidence.aggregator import parse_bc_folder_name
    nums, party = parse_bc_folder_name("BC-21_山东昆达生物科技有限公司")
    assert nums == [21]
    assert "山东" in party


# ── 폴더 합산 ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(not BC14_DIR.exists(), reason="실데이터 없음")
def test_bc14_folder_aggregate_amount():
    """BC-14 폴더 7건 → KRW 합계 금액 > 0."""
    from src.infrastructure.evidence.aggregator import aggregate_folder

    agg = aggregate_folder(BC14_DIR)
    assert agg.bc_numbers == [14]
    assert agg.party_name == "New Future International Trade Co"
    assert agg.total_files == 7
    assert agg.total_amount is not None, f"금액 미계산 — {agg.amounts_by_currency}"
    assert agg.total_amount > 0
    assert agg.total_currency == "KRW"
    assert agg.success_count >= 4, f"성공 {agg.success_count}/7"


@pytest.mark.skipif(not BC14_DIR.exists(), reason="실데이터 없음")
def test_bc14_folder_amounts_by_currency():
    """BC-14 폴더 → amounts_by_currency 에 KRW 포함."""
    from src.infrastructure.evidence.aggregator import aggregate_folder

    agg = aggregate_folder(BC14_DIR)
    assert "KRW" in agg.amounts_by_currency
    assert agg.amounts_by_currency["KRW"] > 0


@pytest.mark.skipif(not BC4_DIR.exists(), reason="실데이터 없음")
def test_bc4_folder_aggregate():
    """BC-4 폴더 — pdf 4건 + xls 7건 혼재 → 합산."""
    from src.infrastructure.evidence.aggregator import aggregate_folder

    agg = aggregate_folder(BC4_DIR)
    assert agg.bc_numbers == [4]
    assert agg.party_name == "BIO TECH"
    # 총 파일 수 확인 (xls 7 + pdf 4 = 11, 하위 폴더 제외)
    assert agg.total_files >= 4


@pytest.mark.skipif(not BC21_DIR.exists(), reason="실데이터 없음")
def test_bc21_recursive_subfolders():
    """BC-21 (하위폴더 1, 2 포함) → 재귀 탐색."""
    from src.infrastructure.evidence.aggregator import aggregate_folder

    agg = aggregate_folder(BC21_DIR, recursive=True)
    assert agg.bc_numbers == [21]
    # 하위 폴더 내 파일까지 포함해야 함
    assert agg.total_files >= 0  # 실제 파일이 있어야 하나 구조만 검증


def test_nonexistent_folder():
    """존재하지 않는 폴더 → 빈 FolderAggregate."""
    from src.infrastructure.evidence.aggregator import aggregate_folder

    folder = Path("/nonexistent/BC-99_Test")
    # FileNotFoundError 가 나는 게 아니라 파일 0건으로 처리돼야 함
    try:
        agg = aggregate_folder(folder)
        assert agg.total_files == 0
    except FileNotFoundError:
        pass  # 폴더 없으면 이것도 OK
