"""test_alias_extended_coverage — 채무 거래처 alias 대량 확장 커버리지 검증."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from src.domain.matching import match_party, reload_aliases


@pytest.fixture(autouse=True)
def reload():
    reload_aliases()


# 채무 final_sampled 거래처명과 예상 PDF 표기 변형 쌍
ALIAS_TEST_CASES = [
    # (PDF에서 추출된 raw_name, 예상 match 대상, candidates)
    ("(주)다원티에스", "(주)다원티에스 Dawon TS", ["(주)다원티에스 Dawon TS", "(주)삼광켐"]),
    ("다원티에스", "(주)다원티에스 Dawon TS", ["(주)다원티에스 Dawon TS", "(주)코스만"]),
    ("Dawon TS", "(주)다원티에스 Dawon TS", ["(주)다원티에스 Dawon TS", "(주)우진트레이딩"]),
    ("삼광켐", "(주)삼광켐", ["(주)삼광켐", "미성코스메틱(주)"]),
    ("씨엠테크", "씨엠테크 주식회사", ["씨엠테크 주식회사", "(주)인투바이오"]),
    ("케이에스팩", "케이에스팩㈜", ["케이에스팩㈜", "(주)코스만"]),
    ("코매치", "코매치 주식회사", ["코매치 주식회사", "이놀렉스코리아"]),
    ("COSMAX NEO", "Cosmax NEO", ["Cosmax NEO", "COSMAX. INC"]),
    ("Cosmax NEO", "Cosmax NEO", ["Cosmax NEO", "SK(주)"]),
    ("SK주식회사", "SK(주)", ["SK(주)", "주식회사 메카솔루션"]),
    ("이놀렉스 코리아", "이놀렉스코리아", ["이놀렉스코리아", "화코스텍인터내셔널 주식회사"]),
    ("화코스텍인터내셔널", "화코스텍인터내셔널 주식회사", ["화코스텍인터내셔널 주식회사", "(주)삼광켐"]),
    ("미성코스메틱", "미성코스메틱(주)", ["미성코스메틱(주)", "코매치 주식회사"]),
    ("메카솔루션", "주식회사 메카솔루션", ["주식회사 메카솔루션", "이놀렉스코리아"]),
    ("인투바이오", "(주)인투바이오", ["(주)인투바이오", "씨엠테크 주식회사"]),
    ("우진트레이딩", "(주)우진트레이딩", ["(주)우진트레이딩", "(주)코스만"]),
    ("코스만", "(주)코스만", ["(주)코스만", "(주)삼광켐"]),
    # COSMAX California alias
    ("COSMAX California Corp", "COSMAX California Corp.", ["COSMAX California Corp.", "COSMAX. INC"]),
    ("COSMAX CALIFORNIA", "COSMAX California Corp.", ["COSMAX California Corp.", "COSMAX USA CORP"]),
    # 코스맥스이스트 주식회사
    ("코스맥스이스트㈜", "코스맥스이스트 주식회사", ["코스맥스이스트 주식회사", "코스맥스에이비(주)"]),
]


@pytest.mark.parametrize("raw_name,expected_match,candidates", ALIAS_TEST_CASES)
def test_alias_matches(raw_name, expected_match, candidates):
    """alias 매핑 — 각 PDF 표기 변형이 올바른 final_sampled명으로 매칭됨."""
    result = match_party(raw_name, candidates)
    assert result.matched_name == expected_match, (
        f"'{raw_name}' → 기대: '{expected_match}', 실제: '{result.matched_name}' "
        f"(confidence={result.confidence:.2f}, method={result.method})"
    )
    assert result.confidence >= 0.8, (
        f"낮은 신뢰도: {result.confidence:.2f} for '{raw_name}'"
    )
