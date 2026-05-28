import pytest
from src.infrastructure.pdf.amount_extractor import (
    extract_party_amount, ExtractionResult,
)


def test_extract_simple_korean_format():
    text = """
    조회처: 고객사001
    잔액: 1,500,000원
    """
    r = extract_party_amount(text, candidate_parties=["고객사001", "고객사002"])
    assert r.matched_party == "고객사001"
    assert r.amount == 1_500_000


def test_extract_with_currency_suffix():
    text = "갑상사 잔액 ₩2,500,000"
    r = extract_party_amount(text, candidate_parties=["갑상사"])
    assert r.amount == 2_500_000


def test_extract_no_match_returns_none():
    text = "전혀 관련 없는 텍스트"
    r = extract_party_amount(text, candidate_parties=["갑상사"])
    assert r.matched_party is None
    assert r.amount is None


def test_extract_negative_balance():
    text = "공급사001 잔액 -500,000원"
    r = extract_party_amount(text, candidate_parties=["공급사001"])
    assert r.amount == -500_000


def test_extract_amount_without_comma():
    text = "고객사002 잔액 5000000"
    r = extract_party_amount(text, candidate_parties=["고객사002"])
    assert r.amount == 5_000_000


def test_extract_picks_largest_when_multiple():
    text = "고객사001 거래일 2025-12-31 잔액 3,500,000원 (참고 1,000)"
    r = extract_party_amount(text, candidate_parties=["고객사001"])
    assert r.amount == 3_500_000


def test_extract_with_corp_prefix_in_pdf():
    """회신서에 '(주)고객사001'로 적혀도 원장 '고객사001'과 매칭."""
    text = "조회처: (주)고객사001\n잔액: 1,200,000원"
    r = extract_party_amount(text, candidate_parties=["고객사001"])
    assert r.matched_party == "고객사001"
    assert r.amount == 1_200_000
