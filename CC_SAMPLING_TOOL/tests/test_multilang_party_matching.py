"""다국어 거래처 매칭 테스트 — 한국어/영문/중국어 표기 정합성 검증."""
import pytest
from src.domain.matching import match_party, reload_aliases


@pytest.fixture(autouse=True)
def fresh_alias():
    """각 테스트 전 alias 캐시 초기화."""
    reload_aliases()
    yield
    reload_aliases()


# ── 한국어 ↔ 영문 매칭 ───────────────────────────────────────────────────────

class TestKoreanToEnglish:
    def test_cosmax_inc_matches_canonical_english(self):
        candidates = ["COSMAX INC", "기타거래처", "코스맥스USA"]
        result = match_party("코스맥스INC", candidates)
        assert result.matched_name == "COSMAX INC"
        assert result.confidence >= 0.9

    def test_cosmax_china_english_from_korean_hint(self):
        candidates = ["科丝美诗（中国）化妆品有限公司", "코스맥스비티아이", "코스맥스USA"]
        result = match_party("COSMAX CHINA", candidates)
        assert result.matched_name == "科丝美诗（中国）化妆品有限公司"
        assert result.confidence >= 0.9

    def test_cosmax_guangzhou_english(self):
        candidates = ["科丝美诗(广州)化妆品有限公司", "코스맥스USA", "코스맥스인도네시아"]
        result = match_party("COSMAX GUANGZHOU", candidates)
        assert result.matched_name == "科丝美诗(广州)化妆品有限公司"
        assert result.confidence >= 0.9

    def test_pt_cosmax_indonesia(self):
        candidates = ["코스맥스인도네시아", "코스맥스말레이시아", "COSMAX USA"]
        result = match_party("PT COSMAX INDONESIA", candidates)
        assert result.matched_name == "코스맥스인도네시아"
        assert result.confidence >= 0.9

    def test_cosmax_usa_corp(self):
        candidates = ["COSMAX USA CORP", "코스맥스USA", "COSMAX INC"]
        result = match_party("COSMAX USA Corp.", candidates)
        assert result.matched_name == "COSMAX USA CORP"
        assert result.confidence >= 0.9

    def test_cosmax_bti_variations(self):
        """BTI 다양한 영문 표기."""
        candidates = ["코스맥스비티아이", "코스맥스바이오 주식회사", "기타"]
        result = match_party("COSMAX BTI, INC.", candidates)
        assert result.matched_name == "코스맥스비티아이"
        assert result.confidence >= 0.9

    def test_cosmax_neo_english(self):
        candidates = ["Cosmax NEO", "코스맥스네오㈜", "COSMAX INC"]
        result = match_party("코스맥스네오(쓰리애플즈코스메틱스)", candidates)
        assert result.matched_name == "코스맥스네오㈜"
        assert result.confidence >= 0.9

    def test_east_korean_to_english(self):
        candidates = ["코스맥스이스트㈜", "코스맥스이스트 주식회사", "기타"]
        result = match_party("COSMAX EAST", candidates)
        assert result.matched_name in ("코스맥스이스트㈜", "코스맥스이스트 주식회사")
        assert result.confidence >= 0.9


# ── 중국어(한자) ↔ 영문/한국어 매칭 ─────────────────────────────────────────

class TestChineseMatching:
    def test_chinese_china_entity_normalized(self):
        """한자 OCR 오류(# 대체) 처리 — alias에 등록된 패턴 그대로."""
        candidates = ["科丝美诗（中国）化妆品有限公司"]
        # alias에 등록된 OCR 패턴: 科#美#（#国）化#品有限公司
        result = match_party("科#美#（#国）化#品有限公司", candidates)
        assert result.matched_name == "科丝美诗（中国）化妆品有限公司"

    def test_chinese_guangzhou_normalized(self):
        candidates = ["科丝美诗(广州)化妆品有限公司"]
        result = match_party("科#美#(#州)化#品有限公司", candidates)
        assert result.matched_name == "科丝美诗(广州)化妆品有限公司"

    def test_shandong_kunda(self):
        candidates = ["山东昆达生物科技有限公司", "코스맥스인도네시아"]
        result = match_party("산둥쿤다", candidates)
        assert result.matched_name == "山东昆达生物科技有限公司"
        assert result.confidence >= 0.9

    def test_shandong_ruinuo(self):
        candidates = ["山东瑞诺生物科技有限公司", "기타"]
        result = match_party("瑞诺", candidates)
        assert result.matched_name == "山东瑞诺生物科技有限公司"
        assert result.confidence >= 0.9

    def test_new_future_xiyun_shanghai(self):
        candidates = ["뉴퓨처인터내셔널", "코스맥스인도네시아"]
        result = match_party("Xiyun (Shanghai) Trading Co., Ltd.", candidates)
        assert result.matched_name == "뉴퓨처인터내셔널"
        assert result.confidence >= 0.9


# ── 법인 접미사 정규화 ────────────────────────────────────────────────────────

class TestSuffixNormalization:
    def test_co_ltd_variations(self):
        """Co., Ltd / Co.,Ltd / CO., LTD 통일."""
        candidates = ["코스맥스㈜"]
        result = match_party("COSMAX CO., LTD.", candidates)
        assert result.matched_name == "코스맥스㈜"

    def test_inc_dot_no_dot(self):
        candidates = ["COSMAX INC"]
        result = match_party("Cosmax Inc.", candidates)
        assert result.matched_name == "COSMAX INC"

    def test_corporation_suffix(self):
        candidates = ["COSMAX USA CORP"]
        result = match_party("COSMAX USA CORPORATION", candidates)
        assert result.matched_name == "COSMAX USA CORP"

    def test_parens_ju_vs_jushik(self):
        """(주) vs 주식회사 정규화."""
        candidates = ["(주)우원"]
        result = match_party("주식회사 우원", candidates)
        assert result.matched_name == "(주)우원"

    def test_circle_ju(self):
        candidates = ["코스맥스네오㈜"]
        result = match_party("코스맥스네오(주)", candidates)
        assert result.matched_name == "코스맥스네오㈜"


# ── 기타 국가 법인 ────────────────────────────────────────────────────────────

class TestOtherCountryEntities:
    def test_cosmax_australia(self):
        candidates = ["코스맥스오스트레일리아", "COSMAX USA"]
        result = match_party("COSMAX AUSTRALIA", candidates)
        assert result.matched_name == "코스맥스오스트레일리아"

    def test_cosmax_malaysia(self):
        candidates = ["코스맥스말레이시아", "COSMAX USA"]
        result = match_party("COSMAX MALAYSIA", candidates)
        assert result.matched_name == "코스맥스말레이시아"

    def test_cosmax_tnc_thailand(self):
        candidates = ["코스맥스티앤씨", "기타"]
        result = match_party("COSMAX T&C", candidates)
        assert result.matched_name == "코스맥스티앤씨"

    def test_cosmax_california(self):
        candidates = ["COSMAX California Corp.", "COSMAX USA CORP"]
        result = match_party("COSMAX California Corporation", candidates)
        assert result.matched_name == "COSMAX California Corp."


# ── 실패 케이스 — 관련 없는 이름은 매칭 불가 ─────────────────────────────────

class TestNonMatchCases:
    def test_unrelated_party_no_match(self):
        candidates = ["코스맥스㈜", "코스맥스인도네시아", "COSMAX USA"]
        result = match_party("삼성전자 주식회사", candidates)
        # confidence 낮거나 None
        assert result.confidence < 0.85 or result.matched_name is None
