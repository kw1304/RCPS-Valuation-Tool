"""거래처 매칭 단위 테스트."""
import pytest

from src.domain.matching import MatchResult, match_party, _normalize


class TestNormalize:
    def test_strips_juju(self):
        assert _normalize("㈜삼성전자") == _normalize("삼성전자")

    def test_strips_justock(self):
        assert _normalize("(주)LG화학") == _normalize("LG화학")

    def test_strips_jusikhoisaa(self):
        assert _normalize("주식회사 현대자동차") == _normalize("현대자동차")

    def test_strips_english_suffix(self):
        assert _normalize("Samsung Co.") == _normalize("Samsung")
        assert _normalize("LG Ltd.") == _normalize("LG")

    def test_lowercase(self):
        assert _normalize("ABC Corp") == _normalize("abc corp")

    def test_strips_spaces(self):
        assert _normalize("  삼성  전자  ") == _normalize("삼성전자")


class TestExactMatch:
    def test_exact_same(self):
        result = match_party("삼성전자", ["삼성전자", "LG전자"])
        assert result.matched_name == "삼성전자"
        assert result.confidence == 1.0
        assert result.method == "exact"

    def test_exact_after_normalize_juju(self):
        """㈜ 제거 후 동치."""
        result = match_party("㈜삼성전자", ["삼성전자", "LG전자"])
        assert result.matched_name == "삼성전자"
        assert result.method == "exact"

    def test_exact_after_normalize_jusikhoisaa(self):
        result = match_party("주식회사현대자동차", ["현대자동차"])
        assert result.matched_name == "현대자동차"
        assert result.method == "exact"

    def test_exact_english_case_insensitive(self):
        result = match_party("ABC CORP", ["abc corp", "DEF Inc"])
        assert result.matched_name == "abc corp"
        assert result.method == "exact"


class TestFuzzyMatch:
    def test_fuzzy_partial_similar(self):
        """부분 유사도 90+ 케이스."""
        result = match_party("삼성전자주식회사 반도체사업부", ["삼성전자"])
        # partial_ratio 높을 것
        assert result.matched_name == "삼성전자"
        assert result.confidence >= 0.85

    def test_fuzzy_partial_longer_name(self):
        """긴 이름의 짧은 후보 partial 매칭 — '삼성전자 반도체' → '삼성전자'."""
        result = match_party("Hyundai Motor Company Korea", ["Hyundai Motor", "Samsung"])
        # Hyundai Motor가 partial_ratio로 잡혀야 함
        assert result.matched_name is not None
        assert "Hyundai" in result.matched_name

    def test_low_confidence_returns_failed(self):
        """전혀 다른 이름은 failed."""
        result = match_party("전혀다른회사", ["삼성전자", "LG전자", "현대자동차"])
        assert result.method == "failed"
        assert len(result.candidates) <= 3

    def test_empty_candidates(self):
        result = match_party("삼성전자", [])
        assert result.method == "failed"
        assert result.matched_name is None


class TestTop3Candidates:
    def test_failed_returns_top3(self):
        candidates = ["가나다", "라마바", "사아자", "차카타", "파하ABC"]
        result = match_party("완전_다른_이름_XYZ", candidates)
        assert result.method == "failed"
        assert len(result.candidates) <= 3


class TestChineseMatch:
    def test_chinese_korean_same_company(self):
        """한자·중국어 표기 — rapidfuzz token_set이 잡을 경우."""
        # 코스맥스는 중국어로도 많이 쓰임 — 직접 매핑 불가, failed OK
        result = match_party("科丝美诗", ["코스맥스비티아이", "LG화학"])
        # 실패해도 크래시 없어야 함
        assert isinstance(result, MatchResult)
