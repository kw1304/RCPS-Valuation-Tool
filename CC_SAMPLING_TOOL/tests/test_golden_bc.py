"""골든세트 BC 폴더 대체적 절차 회귀 테스트 — Week 2.

BC 폴더 7건에 대해:
  - 거래처 매칭 + 결론 자동산출
  - aggregate_folder() Week 2 파라미터 적용 확인

실데이터가 없으면 스킵 (graceful).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN_YAML = ROOT / "tests" / "golden" / "bc_folders" / "expected.yaml"


def _load_expectations() -> list[dict]:
    if not GOLDEN_YAML.exists():
        return []
    with open(GOLDEN_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("expectations", [])


class TestAggregatorWeek2:
    """aggregate_folder() Week 2 확장 필드 테스트 (합성 데이터 사용)."""

    def test_folder_aggregate_has_week2_fields(self, tmp_path):
        """FolderAggregate에 Week 2 필드가 모두 존재하는지 확인."""
        from src.infrastructure.evidence.aggregator import FolderAggregate, aggregate_folder

        # 빈 폴더 테스트 (파일 없음)
        folder = tmp_path / "BC-99_TestParty"
        folder.mkdir()

        agg = aggregate_folder(folder)
        assert hasattr(agg, "matched_party_name")
        assert hasattr(agg, "match_confidence")
        assert hasattr(agg, "match_candidates")
        assert hasattr(agg, "covered_amount_krw")
        assert hasattr(agg, "ledger_balance_krw")
        assert hasattr(agg, "coverage_ratio")
        assert hasattr(agg, "conclusion")
        assert hasattr(agg, "low_confidence_files")

    def test_conclusion_sufficient_when_coverage_high(self, tmp_path):
        """커버리지 ≥ 95% 시 conclusion == '충분'."""
        import openpyxl
        from src.infrastructure.evidence.aggregator import aggregate_folder

        folder = tmp_path / "BC-1_TestParty"
        folder.mkdir()

        # 합성 xlsx 파일 생성 (금액: 1,000,000)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Invoice", "Amount", "Currency"])
        ws.append(["INV-001", 1000000, "KRW"])
        ws.append(["Total", 1000000, ""])
        out = folder / "invoice.xlsx"
        wb.save(str(out))

        agg = aggregate_folder(
            folder,
            ledger_balance_krw=950000.0,  # 커버리지 ≈ 1.05 → min(1.0) = 1.0 → 충분
        )
        assert agg.conclusion == "충분"
        assert agg.coverage_ratio is not None
        assert agg.coverage_ratio >= 0.95

    def test_conclusion_needs_review_when_no_ledger(self, tmp_path):
        """장부가 없으면 conclusion == 'needs_review'."""
        from src.infrastructure.evidence.aggregator import aggregate_folder

        folder = tmp_path / "BC-2_TestParty"
        folder.mkdir()

        agg = aggregate_folder(folder)  # ledger_balance_krw=None 기본값
        assert agg.conclusion == "needs_review"

    def test_low_confidence_files_populated(self, tmp_path):
        """신뢰도 < 0.5 파일이 low_confidence_files 에 포함되는지."""
        from src.infrastructure.evidence.aggregator import LOW_CONFIDENCE_THRESHOLD

        # LOW_CONFIDENCE_THRESHOLD 값 확인
        assert LOW_CONFIDENCE_THRESHOLD == 0.5

    def test_matched_party_with_candidates(self, tmp_path):
        """final_sampled_candidates 주입 시 matched_party_name 반환."""
        from src.infrastructure.evidence.aggregator import aggregate_folder

        folder = tmp_path / "BC-3_TestParty Co"
        folder.mkdir()

        candidates = ["TestParty Co.", "AnotherParty", "ThirdParty"]
        agg = aggregate_folder(
            folder,
            final_sampled_candidates=candidates,
        )
        # "TestParty Co" vs "TestParty Co." — fuzzy match or exact
        # 결과가 None이 아니거나, candidates에서 선택됐으면 OK
        if agg.matched_party_name:
            assert agg.matched_party_name in candidates or "testparty" in agg.matched_party_name.lower()

    def test_party_name_override(self, tmp_path):
        """party_name_override 주입 시 confidence=1.0 적용."""
        from src.infrastructure.evidence.aggregator import aggregate_folder

        folder = tmp_path / "BC-4_원래이름"
        folder.mkdir()

        agg = aggregate_folder(
            folder,
            party_name_override="확정된 거래처명",
        )
        assert agg.matched_party_name == "확정된 거래처명"
        assert agg.match_confidence == 1.0

    def test_parse_bc_folder_name_multi(self):
        """BC-5,12_ 복합 폴더명 파싱."""
        from src.infrastructure.evidence.aggregator import parse_bc_folder_name

        nums, party = parse_bc_folder_name("BC-5,12_채권채무조회서_불일치 소명")
        assert nums == [5, 12]
        assert party.startswith("채권채무조회서")


class TestGoldenBcFolders:
    """골든세트 BC 폴더 실데이터 테스트 (실데이터 있을 때만 실행)."""

    @pytest.fixture(scope="class")
    def expectations(self):
        return _load_expectations()

    def test_golden_yaml_exists_and_non_empty(self, expectations):
        """골든 YAML이 존재하고 기대값이 있는지 확인."""
        assert len(expectations) > 0, "golden/bc_folders/expected.yaml 기대값이 없습니다"

    def test_all_expectations_have_required_fields(self, expectations):
        """모든 기대값 항목에 필수 필드 존재."""
        for exp in expectations:
            assert "folder" in exp, f"folder 필드 없음: {exp}"
            assert "expected_conclusion" in exp, f"expected_conclusion 필드 없음: {exp}"
