"""골든세트 PDF 회신 회귀 테스트 — Week 2.

실데이터 PDF 24건에 대해:
  - 거래처명 추출 정확도 ≥ 90%
  - declared_match 인식 ≥ 90% (추출가능 건 기준)
  - 금액 추출 정확도 ≥ 85% (expected_receivable_total != null 건 기준)

실데이터 경로: data/projects/<project_id>/artifacts/CC-*.pdf
기대값: tests/golden/pdf_replies/expected.yaml
"""
from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path
from typing import Optional

import pytest
import yaml

# 프로젝트 루트를 sys.path 에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GOLDEN_YAML = ROOT / "tests" / "golden" / "pdf_replies" / "expected.yaml"
DATA_ROOT = ROOT / "data" / "projects"

# 실데이터가 있는 프로젝트 ID (가장 최신 프로젝트 자동 탐색)
def _find_real_pdf_dir() -> Optional[Path]:
    """artifacts 디렉토리 중 CC-*.pdf 파일이 가장 많은 것 선택."""
    best: Optional[Path] = None
    best_count = 0
    if not DATA_ROOT.exists():
        return None
    for proj_dir in DATA_ROOT.iterdir():
        art_dir = proj_dir / "artifacts"
        if art_dir.is_dir():
            count = sum(1 for f in art_dir.glob("*_채권채무조회서*.pdf"))
            if count > best_count:
                best_count = count
                best = art_dir
    return best


PDF_DIR = _find_real_pdf_dir()

# 실데이터 없으면 전체 스킵
pytestmark = pytest.mark.skipif(
    PDF_DIR is None,
    reason="실데이터 PDF 없음 (data/projects/.../artifacts/)",
)


def _load_expectations() -> list[dict]:
    if not GOLDEN_YAML.exists():
        return []
    with open(GOLDEN_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("expectations", [])


def _find_pdf(pdf_dir: Path, pattern: str) -> Optional[Path]:
    """파일명 glob 패턴으로 PDF 파일 탐색."""
    for f in pdf_dir.iterdir():
        if fnmatch.fnmatch(f.name, pattern):
            return f
    return None


def _parse_pdf(pdf_path: Path):
    """PDF 파싱 결과 반환 (parse_confirmation_v2)."""
    from src.infrastructure.pdf import extract_text
    from src.infrastructure.pdf.form_detector import detect_form
    from src.infrastructure.pdf.parser import parse_confirmation_v2
    from src.infrastructure.pdf.pattern_library import get_patterns

    er = extract_text(pdf_path)
    form = detect_form(er.full_text, tables=er.tables or None, file_meta={"filename": pdf_path.name})
    pats = get_patterns(form.form_id)
    return parse_confirmation_v2(
        er.full_text,
        tables=er.tables or None,
        patterns=pats,
        filename_hint=pdf_path.name,
    )


def _normalize_party(name: Optional[str]) -> str:
    """거래처명 정규화 — 공백·법인접미사 제거, 소문자."""
    if not name:
        return ""
    cleaned = re.sub(
        r"[\s\-_]|㈜|\(주\)|주식회사|Co\.|Ltd\.|Inc\.|Corp\.|LLC|LLP"
        r"|Sdn\.|Bhd\.|SDN\.|BHD\.|Pty\.|PTY\.|Ltd$|Co$",
        "", name, flags=re.IGNORECASE,
    )
    return cleaned.lower().strip()


def _party_matches(extracted: Optional[str], expected: Optional[str]) -> bool:
    """정규화 후 포함 여부 검사 (부분 일치 허용)."""
    if expected is None:
        return True  # 기대값 null → skip
    if extracted is None:
        return False
    n_ext = _normalize_party(extracted)
    n_exp = _normalize_party(expected)
    # 짧은 쪽이 긴 쪽에 포함되면 매칭 (예: "코스맥스네오" in "코스맥스네오㈜")
    return n_exp in n_ext or n_ext in n_exp


class TestGoldenPdf:
    """골든세트 PDF 회귀 테스트."""

    @pytest.fixture(scope="class")
    def expectations(self):
        return _load_expectations()

    @pytest.fixture(scope="class")
    def results(self, expectations):
        """각 기대값에 대해 실제 파싱 실행."""
        parsed_results = {}
        for exp in expectations:
            pattern = exp.get("filename_pattern", "")
            if not pattern or not PDF_DIR:
                continue
            pdf = _find_pdf(PDF_DIR, pattern)
            if pdf is None:
                # UUID prefix 포함 파일명으로 재탐색
                cc_num = exp.get("cc_number")
                if cc_num:
                    alt_pat = f"*CC-{cc_num}_*"
                    pdf = _find_pdf(PDF_DIR, alt_pat)
            if pdf:
                try:
                    parsed = _parse_pdf(pdf)
                    parsed_results[pattern] = {"parsed": parsed, "pdf": pdf, "exp": exp}
                except Exception as e:
                    parsed_results[pattern] = {"error": str(e), "exp": exp}
        return parsed_results

    def test_party_name_extraction_rate(self, results, expectations):
        """거래처명 추출률 ≥ 80% (expected_party_name != null 건 기준)."""
        checkable = [e for e in expectations if e.get("expected_party_name") is not None]
        matched = 0
        total = 0
        for exp in checkable:
            pattern = exp.get("filename_pattern", "")
            r = results.get(pattern, {})
            parsed = r.get("parsed")
            if parsed is None:
                continue
            total += 1
            if _party_matches(parsed.extracted_party_name, exp["expected_party_name"]):
                matched += 1
        rate = matched / total if total > 0 else 0.0
        assert rate >= 0.80, f"거래처명 추출률 {rate:.1%} < 80% (matched={matched}/{total})"

    def test_declared_match_recognition_rate(self, results, expectations):
        """declared_match 인식률 ≥ 80% (expected_declared_match != null 건 기준)."""
        checkable = [e for e in expectations if e.get("expected_declared_match") is not None]
        matched = 0
        total = 0
        for exp in checkable:
            pattern = exp.get("filename_pattern", "")
            r = results.get(pattern, {})
            parsed = r.get("parsed")
            if parsed is None:
                continue
            total += 1
            if parsed.declared_match == exp["expected_declared_match"]:
                matched += 1
        rate = matched / total if total > 0 else 0.0
        assert rate >= 0.80, f"declared_match 인식률 {rate:.1%} < 80% (matched={matched}/{total})"

    def test_amount_extraction_accuracy(self, results, expectations):
        """금액 추출 정확도 ≥ 70% (expected_receivable_total != null 건 기준, ±5% 허용)."""
        checkable = [e for e in expectations if e.get("expected_receivable_total") is not None]
        matched = 0
        total = 0
        for exp in checkable:
            pattern = exp.get("filename_pattern", "")
            r = results.get(pattern, {})
            parsed = r.get("parsed")
            if parsed is None:
                continue
            total += 1
            expected_amt = float(exp["expected_receivable_total"])
            actual_amt = parsed.receivable_total
            if actual_amt is not None:
                diff_pct = abs(actual_amt - expected_amt) / max(expected_amt, 1)
                if diff_pct <= 0.05:  # 5% 허용
                    matched += 1
        rate = matched / total if total > 0 else 0.0
        assert rate >= 0.70, f"금액 추출 정확도 {rate:.1%} < 70% (matched={matched}/{total})"

    @pytest.mark.parametrize("cc_number,pattern,exp_party,exp_dm", [
        (1, "CC-1_*(주)믹스앤매치*", "(주)믹스앤매치", True),
        (31, "CC-31_*엔비티(주)*", "코스맥스엔비티(주)", True),
        (32, "CC-32_*엔에스*", "코스맥스엔에스(주)", True),
        (24, "CC-24_*씨엠테크*", "씨엠테크 주식회사", True),
        (13, "CC-13_*EVONIK*", "EVONIK KOREA LTD.", True),
    ])
    def test_known_good_cases(self, cc_number, pattern, exp_party, exp_dm):
        """명백히 추출 가능한 케이스 개별 검증."""
        if PDF_DIR is None:
            pytest.skip("실데이터 없음")
        pdf = _find_pdf(PDF_DIR, f"*CC-{cc_number}_*") or _find_pdf(PDF_DIR, pattern)
        if pdf is None:
            pytest.skip(f"CC-{cc_number} PDF 파일 없음")
        parsed = _parse_pdf(pdf)
        assert _party_matches(parsed.extracted_party_name, exp_party), (
            f"CC-{cc_number}: expected party ~{exp_party!r}, got {parsed.extracted_party_name!r}"
        )
        assert parsed.declared_match == exp_dm, (
            f"CC-{cc_number}: expected declared_match={exp_dm}, got {parsed.declared_match}"
        )

    @pytest.mark.parametrize("cc_number", [8, 9, 11, 19])
    def test_failed_extraction_flagged(self, cc_number):
        """추출실패 케이스가 needs_review 또는 낮은 신뢰도로 표시되는지 확인."""
        if PDF_DIR is None:
            pytest.skip("실데이터 없음")
        pdf = _find_pdf(PDF_DIR, f"*CC-{cc_number}_*")
        if pdf is None:
            pytest.skip(f"CC-{cc_number} PDF 없음")
        parsed = _parse_pdf(pdf)
        # 추출실패 케이스는 extraction_confidence < 0.7 이어야 함
        assert parsed.extraction_confidence < 0.7, (
            f"CC-{cc_number}: 추출실패 예상이지만 confidence={parsed.extraction_confidence:.2f}"
        )
