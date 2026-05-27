"""PDF 파서 단위 테스트 — 합성 텍스트로 추출 정확도 검증."""
import pytest

from src.infrastructure.pdf.parser import ParsedReply, parse_confirmation


# ── 기본 채권 양식 ─────────────────────────────────────────────
SAMPLE_RECEIVABLE = """
주식회사 삼성전자 귀중

2025년 12월 31일 현재 당사 장부상 귀사에 대한 외상매출금 잔액은 아래와 같사오니
확인하여 주시기 바랍니다.

잔액: 1,234,567,890원

확인 내용:
당사 장부상 잔액과 일치함을 확인합니다.

2026년 01월 15일

(인)
"""

SAMPLE_PAYABLE = """
(주)LG화학 귀하

2025.12.31 기준 외상매입금 잔액 확인금액: 987,654,321원

미지급금 합계: 500,000,000원

회신일자: 2026.01.20

서명:
"""

SAMPLE_USD = """
ABC Corporation

Balance as of December 31, 2025

Receivable Balance: $1,234.56

Reply Date: 2026-01-10

Signature: ___________
"""

SAMPLE_JPY = """
株式会社トヨタ 貴中

2025年12月31日現在

外売掛金残高: ￥100,000,000

確認日: 2026年1月15日
(確認)
"""

SAMPLE_NEGATIVE = """
웅계무역(주) 귀중

잔액: (2,500,000)원

2026년 2월 1일

(인)
"""

SAMPLE_DATE_ONLY_MD = """
ABC(주)

잔액: 5,000,000원

1월 31일 서명
"""

SAMPLE_NO_SIGN = """
주식회사 테스트 귀중

잔액: 100,000원

2026-01-01
"""


class TestParseConfirmationBasic:
    def test_company_name_guijung(self):
        result = parse_confirmation(SAMPLE_RECEIVABLE)
        assert result.extracted_name is not None
        assert "삼성전자" in result.extracted_name

    def test_balance_extraction(self):
        result = parse_confirmation(SAMPLE_RECEIVABLE)
        assert result.extracted_balance == pytest.approx(1_234_567_890, rel=1e-3)

    def test_balance_currency_krw(self):
        result = parse_confirmation(SAMPLE_RECEIVABLE)
        assert result.balance_currency == "KRW"

    def test_date_extraction_ymd_korean(self):
        result = parse_confirmation(SAMPLE_RECEIVABLE)
        assert result.reply_date == "2026-01-15"

    def test_has_signature(self):
        result = parse_confirmation(SAMPLE_RECEIVABLE)
        assert result.has_signature is True

    def test_no_signature(self):
        result = parse_confirmation(SAMPLE_NO_SIGN)
        assert result.has_signature is False


class TestPayable:
    def test_payable_name(self):
        result = parse_confirmation(SAMPLE_PAYABLE, kind="payable")
        assert result.extracted_name is not None

    def test_payable_balance(self):
        result = parse_confirmation(SAMPLE_PAYABLE, kind="payable")
        assert result.extracted_balance is not None
        assert result.extracted_balance > 0

    def test_payable_date_dot_format(self):
        result = parse_confirmation(SAMPLE_PAYABLE, kind="payable")
        assert result.reply_date == "2026-01-20"


class TestCurrency:
    def test_usd_detection(self):
        result = parse_confirmation(SAMPLE_USD)
        assert result.balance_currency == "USD"
        assert result.extracted_balance == pytest.approx(1234.56, rel=1e-3)

    def test_jpy_detection(self):
        result = parse_confirmation(SAMPLE_JPY)
        assert result.balance_currency == "JPY"
        assert result.extracted_balance == pytest.approx(100_000_000, rel=1e-3)

    def test_krw_comma_format(self):
        text = "잔액: 123,456,789원\n(인)"
        result = parse_confirmation(text)
        assert result.extracted_balance == pytest.approx(123_456_789, rel=1e-3)
        assert result.balance_currency == "KRW"


class TestNegativeBalance:
    def test_bracket_negative(self):
        result = parse_confirmation(SAMPLE_NEGATIVE)
        assert result.extracted_balance is not None
        assert result.extracted_balance < 0
        assert result.extracted_balance == pytest.approx(-2_500_000, rel=1e-3)


class TestDateFormats:
    def test_date_dash_format(self):
        text = "잔액: 100,000원\n2026-03-15\n확인"
        result = parse_confirmation(text)
        assert result.reply_date == "2026-03-15"

    def test_date_dot_format(self):
        text = "잔액: 100,000원\n2026.03.15\n(인)"
        result = parse_confirmation(text)
        assert result.reply_date == "2026-03-15"

    def test_date_korean_full(self):
        text = "잔액: 100,000원\n2026년 3월 15일\n(인)"
        result = parse_confirmation(text)
        assert result.reply_date == "2026-03-15"

    def test_date_md_only_returns_none(self):
        # 연도 없는 날짜는 None 반환
        result = parse_confirmation(SAMPLE_DATE_ONLY_MD)
        assert result.reply_date is None


class TestConfidence:
    def test_full_extraction_confidence(self):
        result = parse_confirmation(SAMPLE_RECEIVABLE)
        assert result.confidence >= 0.5  # 이름+잔액+날짜+서명 중 3개 이상

    def test_empty_text_confidence(self):
        result = parse_confirmation("")
        assert result.confidence == 0.0
