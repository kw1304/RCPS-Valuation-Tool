"""영문 컬럼명 자동 감지 테스트 — ledger_schema.detect_ledger_columns."""
import pandas as pd
import pytest
from src.infrastructure.schemas.ledger_schema import detect_ledger_columns, detect_ledger_sheets


# ── detect_ledger_sheets 영문 시트명 ─────────────────────────────────────────

class TestDetectLedgerSheetsEnglish:
    def test_ar_sheet_detected(self):
        result = detect_ledger_sheets(["AR", "AP"])
        assert result["receivable"] == "AR"
        assert result["payable"] == "AP"

    def test_receivable_sheet_detected(self):
        result = detect_ledger_sheets(["Receivable", "Payable"])
        assert result["receivable"] == "Receivable"
        assert result["payable"] == "Payable"

    def test_mixed_ko_en_sheets(self):
        result = detect_ledger_sheets(["채권", "AP"])
        assert result["receivable"] == "채권"
        assert result["payable"] == "AP"

    def test_ar_partial_match(self):
        result = detect_ledger_sheets(["AR Ledger", "AP Ledger"])
        assert result["receivable"] is not None
        assert result["payable"] is not None


# ── detect_ledger_columns 영문 헤더 ──────────────────────────────────────────

class TestDetectLedgerColumnsEnglish:
    def _make_df(self, cols):
        return pd.DataFrame(columns=cols)

    def test_customer_code_and_name(self):
        df = self._make_df(["Customer Code", "Customer Name", "Account Code",
                            "Account Name", "Currency", "Opening Balance",
                            "Movement", "Closing Balance"])
        result = detect_ledger_columns(df)
        assert result["code_col"] == 0
        assert result["name_col"] == 1
        assert result["account_code"] == 2
        assert result["account_name"] == 3
        assert result["currency"] == 4
        assert result["beginning"] == 5
        assert result["change"] == 6
        assert result["ending"] == 7

    def test_vendor_code_and_name(self):
        df = self._make_df(["Vendor Code", "Vendor Name", "Account Code",
                            "Account Name", "CCY", "Beg Balance",
                            "Net Change", "End Balance"])
        result = detect_ledger_columns(df)
        assert result["code_col"] == 0
        assert result["name_col"] == 1
        assert result["currency"] == 4
        assert result["beginning"] == 5
        assert result["change"] == 6
        assert result["ending"] == 7

    def test_opening_balance_alias(self):
        df = self._make_df(["Code", "Name", "Acct", "Acct Name",
                            "Curr", "Beginning Balance", "Change", "Ending Balance"])
        result = detect_ledger_columns(df)
        assert result["beginning"] == 5
        assert result["ending"] == 7

    def test_closing_balance_alias(self):
        df = self._make_df(["Code", "Name", "Acct", "Acct Name",
                            "Curr", "Opening Balance", "Movement", "Closing Balance"])
        result = detect_ledger_columns(df)
        assert result["beginning"] == 5
        assert result["ending"] == 7

    def test_bp_code_name_pattern(self):
        """BP Code / BP Name 패턴 (SAP 계열)."""
        df = self._make_df(["BP Code", "BP Name", "GL Account",
                            "GL Account Name", "Currency",
                            "Beg Bal", "Net Movement", "End Bal"])
        result = detect_ledger_columns(df)
        assert result["code_col"] == 0
        assert result["name_col"] == 1
        assert result["account_code"] == 2
        assert result["account_name"] == 3
        assert result["beginning"] == 5
        assert result["change"] == 6
        assert result["ending"] == 7

    def test_mixed_korean_english_header(self):
        """한국어/영문 혼합 헤더."""
        df = self._make_df(["거래처코드", "Customer Name", "계정과목",
                            "Account Name", "통화",
                            "Opening Balance", "증감", "기말잔액"])
        result = detect_ledger_columns(df)
        assert result["code_col"] == 0
        assert result["name_col"] == 1
        assert result["account_code"] == 2
        assert result["account_name"] == 3
        assert result["currency"] == 4
        assert result["beginning"] == 5
        assert result["change"] == 6
        assert result["ending"] == 7

    def test_korean_standard_header_unchanged(self):
        """기존 한국어 7620 표준 헤더가 여전히 작동."""
        df = self._make_df(["코드", "명", "계정과목", "계정과목명",
                            "통화", "기초", "증감", "기말"])
        result = detect_ledger_columns(df)
        assert result["code_col"] == 0
        assert result["name_col"] == 1
        assert result["account_code"] == 2
        assert result["account_name"] == 3
        assert result["currency"] == 4
        assert result["beginning"] == 5
        assert result["change"] == 6
        assert result["ending"] == 7

    def test_partial_detection_missing_cols(self):
        """일부 컬럼 없으면 None 반환."""
        df = self._make_df(["Customer Code", "Customer Name", "Balance"])
        result = detect_ledger_columns(df)
        assert result["code_col"] == 0
        assert result["name_col"] == 1
        # account_code, account_name, currency는 None
        assert result["account_code"] is None
        assert result["account_name"] is None
        assert result["currency"] is None

    def test_company_name_col_detected(self):
        """Company Name 컬럼 감지."""
        df = self._make_df(["Code", "Company Name", "Account", "Account Description",
                            "Currency", "Opening", "Net Change", "Closing"])
        result = detect_ledger_columns(df)
        assert result["name_col"] == 1
        assert result["account_code"] == 2
        assert result["account_name"] == 3
