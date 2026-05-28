"""대손충당금 로더 단위 테스트.

AllowanceData 파싱 로직을 검증한다:
  - 부실채권 시트에서 코드 제거 후 거래처명 추출
  - 월별 시트에서 잔액 합산 (allowance_by_party)
  - 실제 파일 없는 환경에서도 mock 데이터로 단위 검증
"""
from __future__ import annotations

import re
import sys
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.infrastructure.loaders import (
    AllowanceData,
    _strip_party_code,
    load_allowance_data,
)

# ─────────────────────────────────────────────────────────────
# _strip_party_code 단위 테스트
# ─────────────────────────────────────────────────────────────

class TestStripPartyCode:
    def test_removes_numeric_code_suffix(self):
        assert _strip_party_code("(주)미가람화장품[110]") == "(주)미가람화장품"

    def test_removes_large_code(self):
        assert _strip_party_code("(주)에이치에스글로벌[71842]") == "(주)에이치에스글로벌"

    def test_no_code_passes_through(self):
        assert _strip_party_code("코스모코스") == "코스모코스"

    def test_strips_trailing_whitespace(self):
        assert _strip_party_code("세리화장품[122]  ") == "세리화장품"

    def test_text_after_bracket_not_removed(self):
        # "[숫자]" 가 아닌 패턴은 제거하지 않음
        assert _strip_party_code("(주)테스트[ABC]") == "(주)테스트[ABC]"


# ─────────────────────────────────────────────────────────────
# AllowanceData 모델 테스트
# ─────────────────────────────────────────────────────────────

class TestAllowanceData:
    def test_bad_debt_count(self):
        data = AllowanceData(bad_debt_parties={"A", "B", "C"})
        assert data.bad_debt_count == 3

    def test_total_allowance(self):
        data = AllowanceData(allowance_by_party={"A": 1_000_000, "B": 500_000})
        assert data.total_allowance == 1_500_000

    def test_empty_defaults(self):
        data = AllowanceData()
        assert data.bad_debt_count == 0
        assert data.total_allowance == 0.0


# ─────────────────────────────────────────────────────────────
# 실제 파일 통합 테스트 (파일 있을 때만 실행)
# ─────────────────────────────────────────────────────────────

ALLOWANCE_PATH = (
    ROOT
    / "input"
    / "코스맥스네오"
    / "채권채무조회서 (3)"
    / "코스맥스네오_대손충당금_기대손실모형_(관계사포함)_25.12.xlsx"
)

_SKIP_IF_NO_FILE = pytest.mark.skipif(
    not ALLOWANCE_PATH.exists(),
    reason="대손충당금 실제 파일 없음 — CI 환경에서는 skip",
)


@_SKIP_IF_NO_FILE
class TestLoadAllowanceDataReal:
    """실제 파일 통합 테스트 — 부실채권 시트만 파싱 (include_monthly=False 기본값)."""

    @pytest.fixture(scope="class")
    def data(self):
        # include_monthly=False (기본): 부실채권 시트만 파싱 — 빠름
        return load_allowance_data(ALLOWANCE_PATH)

    def test_bad_debt_parties_not_empty(self, data: AllowanceData):
        assert data.bad_debt_count > 0, "부실채권 거래처가 1건 이상이어야 함"

    def test_known_bad_debt_party_present(self, data: AllowanceData):
        # 실데이터에서 확인된 부실채권 거래처
        assert "(주)미가람화장품" in data.bad_debt_parties

    def test_code_stripped_from_all_names(self, data: AllowanceData):
        """추출된 거래처명에 "[숫자]" 코드가 남아있으면 안 됨."""
        code_re = re.compile(r"\[\d+\]")
        for name in data.bad_debt_parties:
            assert not code_re.search(name), f"코드가 제거되지 않음: {name!r}"

    def test_bad_debt_count_matches_expected(self, data: AllowanceData):
        # 실데이터 기준 34개 거래처
        assert data.bad_debt_count == 34

    def test_allowance_by_party_empty_when_monthly_excluded(self, data: AllowanceData):
        # include_monthly=False(기본)이면 월별 합산 없음
        assert len(data.allowance_by_party) == 0
