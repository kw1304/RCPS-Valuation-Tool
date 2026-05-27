"""영문 계정과목명 인식 테스트 — AR/AP/Notes Receivable 등 영문 약어·풀네임 → 한국어 그룹."""
import pytest
from src.domain.population import _load_account_group_map, _normalize_account_name, aggregate_by_party, LedgerRow


# ── _load_account_group_map 직접 검증 ─────────────────────────────────────────

class TestAccountGroupMap:
    def setup_method(self):
        self.recv_map = _load_account_group_map("receivable")
        self.pay_map  = _load_account_group_map("payable")

    # ── 채권 영문 약어 ────────────────────────────────────────────────────────
    def test_ar_maps_to_외상매출금(self):
        assert self.recv_map.get("ar") == "외상매출금"

    def test_a_slash_r_maps_to_외상매출금(self):
        assert self.recv_map.get("a/r") == "외상매출금"

    def test_accounts_receivable_fullname(self):
        assert self.recv_map.get("accounts receivable") == "외상매출금"

    def test_trade_receivables_plural(self):
        assert self.recv_map.get("trade receivables") == "외상매출금"

    def test_notes_receivable(self):
        assert self.recv_map.get("notes receivable") == "받을어음"

    def test_bills_receivable(self):
        assert self.recv_map.get("bills receivable") == "받을어음"

    def test_nr_maps_to_받을어음(self):
        assert self.recv_map.get("nr") == "받을어음"

    def test_other_receivables(self):
        assert self.recv_map.get("other receivables") == "미수금"

    def test_advances_maps_to_선급금(self):
        assert self.recv_map.get("advances") == "선급금"

    def test_prepaid_expenses(self):
        assert self.recv_map.get("prepaid expenses") == "선급금"

    def test_long_term_loans(self):
        assert self.recv_map.get("long-term loans") == "장기대여금"

    def test_lt_loans_abbr(self):
        assert self.recv_map.get("lt loans") == "장기대여금"

    def test_lease_deposit(self):
        assert self.recv_map.get("lease deposit") == "임차보증금"

    def test_security_deposit(self):
        assert self.recv_map.get("security deposit") == "임차보증금"

    # ── 채무 영문 약어 ────────────────────────────────────────────────────────
    def test_ap_maps_to_외상매입금(self):
        assert self.pay_map.get("ap") == "외상매입금"

    def test_a_slash_p_maps_to_외상매입금(self):
        assert self.pay_map.get("a/p") == "외상매입금"

    def test_accounts_payable_fullname(self):
        assert self.pay_map.get("accounts payable") == "외상매입금"

    def test_trade_payables_plural(self):
        assert self.pay_map.get("trade payables") == "외상매입금"

    def test_notes_payable(self):
        result = self.pay_map.get("notes payable")
        assert result == "지급어음(외담대외상매입금)"

    def test_bills_payable(self):
        assert self.pay_map.get("bills payable") == "지급어음(외담대외상매입금)"

    def test_np_abbr(self):
        assert self.pay_map.get("np") == "지급어음(외담대외상매입금)"

    def test_other_payables(self):
        assert self.pay_map.get("other payables") == "미지급금"

    def test_accrued_expenses(self):
        assert self.pay_map.get("accrued expenses") == "미지급금"

    def test_customer_advances_maps_to_선수금(self):
        assert self.pay_map.get("customer advances") == "선수금"

    def test_deferred_income(self):
        assert self.pay_map.get("deferred income") == "선수금"

    def test_lease_deposit_received(self):
        assert self.pay_map.get("lease deposit received") == "임대보증금"

    # ── 한국어 기존 매핑 유지 ─────────────────────────────────────────────────
    def test_korean_외상매출금_still_works(self):
        assert self.recv_map.get("외상매출금") == "외상매출금"

    def test_korean_외상매입금_still_works(self):
        assert self.pay_map.get("외상매입금") == "외상매입금"

    def test_korean_미수금_still_works(self):
        assert self.recv_map.get("미수금") == "미수금"

    def test_korean_미지급금_still_works(self):
        assert self.pay_map.get("미지급금") == "미지급금"


# ── aggregate_by_party 영문 계정과목 처리 ─────────────────────────────────────

class TestAggregateEnglishAccountNames:
    def test_ar_ledger_row_aggregates_to_외상매출금(self):
        rows = [
            LedgerRow("C001", "거래처A", "1100", "Accounts Receivable", "KRW", 0, 0, 1_000_000),
        ]
        result = aggregate_by_party(rows, kind="receivable")
        assert "거래처A" in result
        bal = result["거래처A"]
        assert "외상매출금" in bal.by_account
        assert bal.by_account["외상매출금"] == 1_000_000

    def test_ar_abbr_aggregates_to_외상매출금(self):
        rows = [
            LedgerRow("C002", "거래처B", "1100", "AR", "KRW", 0, 0, 500_000),
        ]
        result = aggregate_by_party(rows, kind="receivable")
        assert "외상매출금" in result["거래처B"].by_account

    def test_ap_abbr_aggregates_to_외상매입금(self):
        rows = [
            LedgerRow("V001", "공급업체A", "2100", "AP", "KRW", 0, 0, 2_000_000),
        ]
        result = aggregate_by_party(rows, kind="payable")
        assert "외상매입금" in result["공급업체A"].by_account

    def test_notes_receivable_aggregates_to_받을어음(self):
        rows = [
            LedgerRow("C003", "거래처C", "1110", "Notes Receivable", "KRW", 0, 0, 300_000),
        ]
        result = aggregate_by_party(rows, kind="receivable")
        assert "받을어음" in result["거래처C"].by_account

    def test_mixed_english_korean_accounts_same_party(self):
        rows = [
            LedgerRow("C004", "혼합거래처", "1100", "AR", "KRW", 0, 0, 1_000_000),
            LedgerRow("C004", "혼합거래처", "1110", "받을어음", "KRW", 0, 0, 200_000),
        ]
        result = aggregate_by_party(rows, kind="receivable")
        bal = result["혼합거래처"]
        assert bal.by_account.get("외상매출금", 0) == 1_000_000
        assert bal.by_account.get("받을어음", 0) == 200_000
        assert bal.total == 1_200_000

    def test_unknown_english_account_kept_as_is(self):
        """매핑 없는 영문 계정과목은 원래 이름 유지."""
        rows = [
            LedgerRow("C005", "거래처E", "9999", "Custom Receivable Account", "KRW", 0, 0, 100),
        ]
        result = aggregate_by_party(rows, kind="receivable")
        bal = result["거래처E"]
        assert "Custom Receivable Account" in bal.by_account


# ── _normalize_account_name 함수 ──────────────────────────────────────────────

class TestNormalizeAccountName:
    def test_uppercase_lowercased(self):
        assert _normalize_account_name("ACCOUNTS RECEIVABLE") == "accounts receivable"

    def test_strip_whitespace(self):
        assert _normalize_account_name("  AR  ") == "ar"

    def test_korean_unchanged(self):
        assert _normalize_account_name("외상매출금") == "외상매출금"
