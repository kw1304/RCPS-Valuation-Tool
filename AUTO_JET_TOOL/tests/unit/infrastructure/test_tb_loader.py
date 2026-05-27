"""TbLoader 일반화 단위 테스트.

COA 계정유형 기반 부호 결정, 헤더 키워드 동적 매핑,
손익계정 판별(A03 연계)을 검증한다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from jet.infrastructure.io.coa_loader import AccountMaster
from jet.infrastructure.io.tb_loader import TbLoader, TrialBalance


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _coa(code: str, acct_type: str) -> AccountMaster:
    return AccountMaster(
        account_code=code,
        account_name="테스트계정",
        account_type=acct_type,
        created_date=None,
        company_code="1000",
    )


# ── 부호 결정 테스트 ─────────────────────────────────────────────────────────

class TestResolveSign:
    """_resolve_sign: 계정코드 첫자리 테이블 기반 부호 결정.

    재무상태표(B) 계정에는 자산(차변)과 부채·자본(대변)이 혼재하므로
    COA account_type='B'만으로 부호를 결정할 수 없다.
    따라서 TB 부호 결정은 항상 코드 첫자리 테이블을 사용한다.
    COA account_type은 A03의 손익계정 판별에만 활용된다.
    """

    def test_asset_prefix_positive(self):
        """첫자리 1(자산) → +1."""
        loader = TbLoader()
        assert loader._resolve_sign("11101010") == +1

    def test_memo_prefix_positive(self):
        """첫자리 9(명세) → +1."""
        loader = TbLoader()
        assert loader._resolve_sign("90000000") == +1

    def test_liability_prefix_negative(self):
        """첫자리 2(부채) → -1."""
        loader = TbLoader()
        assert loader._resolve_sign("21010000") == -1

    def test_equity_prefix_negative(self):
        """첫자리 3(자본) → -1."""
        loader = TbLoader()
        assert loader._resolve_sign("30000000") == -1

    def test_revenue_prefix_negative(self):
        """첫자리 4(매출) → -1."""
        loader = TbLoader()
        assert loader._resolve_sign("40000000") == -1

    def test_coa_provided_does_not_change_sign(self):
        """COA가 제공되어도 부호 결정에 영향 없음 (코드 첫자리 사용)."""
        # 4xxx는 COA에 'B'로 잘못 분류되어도 첫자리 기준으로 -1
        loader = TbLoader(coa_master={"40000000": _coa("40000000", "B")})
        assert loader._resolve_sign("40000000") == -1

    def test_code_with_coa_still_uses_prefix(self):
        """COA에 코드가 있어도 첫자리 fallback을 사용한다."""
        loader = TbLoader(coa_master={"11101010": _coa("11101010", "B")})
        assert loader._resolve_sign("11101010") == +1


# ── 헤더 컬럼 매핑 테스트 ───────────────────────────────────────────────────

class TestMapSplitHeaderColumns:
    """_map_split_header_columns: 다양한 컬럼명 변형 감지."""

    def _map(self, headers: list[str]):
        return TbLoader()._map_split_header_columns(headers)

    def test_bti_style_headers(self):
        """BTI 양식: 기조찬액·차변누계·대변누계 감지, 분할 잔액 closing_split."""
        headers = ["과목", "기조찬액", "잔액", "차변누계", "차변당월", "대변당월", "대변누계", "잔액"]
        col_map = self._map(headers)
        assert col_map["opening"] == 1     # 기조찬액
        assert col_map["period_debit"] == 3   # 차변누계
        assert col_map["period_credit"] == 6  # 대변누계
        # closing_split: opening(1) 이후 "잔액" 컬럼 = [2, 7]
        assert "closing_split" in col_map
        assert sorted(col_map["closing_split"]) == [2, 7]
        # closing_single은 없음 (BTI는 "기말잔액" 컬럼이 없음)
        assert "closing_single" not in col_map

    def test_explicit_closing_single(self):
        """명시적 기말잔액 컬럼이 있으면 closing_single로 감지된다."""
        headers = ["계정", "기초잔액", "차변계", "대변계", "기말잔액"]
        col_map = self._map(headers)
        assert col_map["opening"] == 1
        assert col_map["period_debit"] == 2
        assert col_map["period_credit"] == 3
        assert col_map["closing_single"] == 4
        # closing_split은 없음 (closing_single 우선)
        assert "closing_split" not in col_map

    def test_missing_keywords_not_mapped(self):
        """키워드 없는 컬럼은 매핑되지 않는다."""
        headers = ["과목", "A", "B", "C"]
        col_map = self._map(headers)
        assert "opening" not in col_map
        assert "period_debit" not in col_map


# ── split header 양식 감지 테스트 ────────────────────────────────────────────

class TestDetectSplitHeaderFormat:
    """_detect_split_header_format: 기초잔액+차변누계+대변누계 동시 존재 감지."""

    def test_bti_headers_detected(self):
        """BTI 헤더가 분할헤더 양식으로 감지된다."""
        headers = ["과목", "기조찬액", "잔액", "차변누계", "차변당월", "대변당월", "대변누계"]
        assert TbLoader._detect_split_header_format(headers) is True

    def test_generic_headers_detected(self):
        """기초잔액·차변계·대변계 등 일반 키워드도 감지된다."""
        headers = ["계정코드", "기초잔액", "차변합계", "대변합계", "기말잔액"]
        assert TbLoader._detect_split_header_format(headers) is True

    def test_multiheader_row1_not_detected(self):
        """멀티헤더 R1(차변/대변 반복)은 분할헤더 양식으로 감지되지 않는다."""
        # 멀티헤더 R1은 "기초잔액" 같은 기초 키워드가 없음
        headers = ["", "차변", "차변", "차변", "대변", "대변", "대변"]
        assert TbLoader._detect_split_header_format(headers) is False

    def test_empty_headers_not_detected(self):
        """빈 헤더는 False를 반환한다."""
        assert TbLoader._detect_split_header_format([]) is False


# ── A03 손익계정 판별 테스트 ─────────────────────────────────────────────────

class TestIsIncomeStatementAccount:
    """A03._is_income_statement_account: COA 우선, 첫자리 fallback."""

    def _ctx(self, coa=None):
        from jet.domain.rules.base import RuleContext
        return RuleContext(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            coa_master=coa,
        )

    def test_coa_type_P_is_income(self):
        """COA account_type='P' → 손익계정."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        coa = {"40000000": _coa("40000000", "P")}
        assert A03TBRollforward._is_income_statement_account("40000000", self._ctx(coa)) is True

    def test_coa_type_B_is_not_income(self):
        """COA account_type='B' → 재무상태표 계정 (손익 아님)."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        coa = {"11101010": _coa("11101010", "B")}
        assert A03TBRollforward._is_income_statement_account("11101010", self._ctx(coa)) is False

    def test_no_coa_prefix4_is_income(self):
        """COA 없고 첫자리 4 → 손익계정 fallback."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        assert A03TBRollforward._is_income_statement_account("40000000", self._ctx()) is True

    def test_no_coa_prefix1_is_not_income(self):
        """COA 없고 첫자리 1 → 자산계정 (손익 아님)."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        assert A03TBRollforward._is_income_statement_account("11101010", self._ctx()) is False

    def test_no_coa_prefix7_is_income(self):
        """COA 없고 첫자리 7(기타손익) → 손익 fallback 포함."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        assert A03TBRollforward._is_income_statement_account("70000000", self._ctx()) is True

    def test_coa_provided_but_code_missing_uses_fallback(self):
        """COA가 제공되어 있지만 해당 코드가 없으면 첫자리 fallback 사용."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        coa = {"99999999": _coa("99999999", "B")}  # 다른 코드만 있음
        # 50000000은 COA에 없음 → 첫자리 '5' → 손익
        assert A03TBRollforward._is_income_statement_account("50000000", self._ctx(coa)) is True


# ── A03 COA 연계 통합 테스트 ─────────────────────────────────────────────────

class TestA03WithCoa:
    """A03 룰이 COA 계정유형을 반영해 손익계정 기초를 0으로 처리하는지 검증."""

    def _entry(self, code: str, debit: float = 0.0, credit: float = 0.0):
        from datetime import datetime
        from jet.domain.entities.journal_entry import JournalEntry
        return JournalEntry(
            entry_no="E001",
            entry_date=datetime(2025, 6, 15),
            posting_date=datetime(2025, 6, 15),
            posting_time=None,
            user_id="TEST",
            user_name=None,
            account_code=code,
            account_name=None,
            debit_amount=Decimal(str(debit)),
            credit_amount=Decimal(str(credit)),
            description=None,
            counterparty=None,
            entry_type="SA",
            dept_code=None,
            raw_row_index=0,
            is_system_generated=False,
        )

    def test_coa_P_account_opening_forced_to_zero(self):
        """COA에서 P로 명시된 3xxx 계정도 기초=0으로 강제된다."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        from jet.domain.rules.base import RuleContext

        # 30000000은 자본계정이지만 COA에서 P로 명시 (이론적 케이스)
        coa = {"30000000": _coa("30000000", "P")}
        # TB에 기초잔액 100만원 세팅
        tb = {
            "30000000": TrialBalance(
                account_code="30000000", account_name="테스트",
                opening_balance=1_000_000,
                period_debit=500_000, period_credit=500_000,
                closing_balance=1_000_000,  # 기초 유지 → 차이=0 기대
            )
        }
        entries = [
            self._entry("30000000", debit=500_000),
            self._entry("30000000", credit=500_000),
        ]
        rule = A03TBRollforward()
        rule.configure({})
        ctx = RuleContext(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            coa_master=coa,
            tb_master=tb,
        )
        result = rule.apply(entries, ctx)
        # COA P → 기초=0 강제 → 계산기말=0+500k-500k=0 ≠ TB기말 100만 → 1건 적출
        assert result.finding_count == 1

    def test_coa_B_account_opening_preserved(self):
        """COA에서 B로 명시된 자산계정은 기초잔액이 그대로 반영된다."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        from jet.domain.rules.base import RuleContext

        coa = {"11101010": _coa("11101010", "B")}
        tb = {
            "11101010": TrialBalance(
                account_code="11101010", account_name="현금",
                opening_balance=1_000_000,
                period_debit=300_000, period_credit=200_000,
                closing_balance=1_100_000,  # 100만 + 30만 - 20만 = 110만
            )
        }
        entries = [
            self._entry("11101010", debit=300_000),
            self._entry("11101010", credit=200_000),
        ]
        rule = A03TBRollforward()
        rule.configure({})
        ctx = RuleContext(
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            coa_master=coa,
            tb_master=tb,
        )
        result = rule.apply(entries, ctx)
        assert result.finding_count == 0


# ── TbLoader.load_with_prior 단위 테스트 ─────────────────────────────────

class TestLoadWithPrior:
    """load_with_prior: (당기 TB, 전기 TB) 쌍 반환 검증."""

    def _make_multiheader_xl(self, sheets: dict[str, pd.DataFrame]):
        """멀티헤더 양식 ExcelFile 모킹용 임시 파일을 생성한다."""
        import tempfile
        import os

        # 임시 엑셀 파일 생성
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp_path = Path(f.name)

        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)

        return tmp_path

    def _multiheader_df(self, rows: list[dict]) -> pd.DataFrame:
        """멀티헤더 양식 DataFrame을 생성한다.

        R0: 계정코드 / 계정명 / 차변 / 차변 / 차변 / 대변 / 대변 / 대변
        R1: ''       / ''     / 이월 / 당기 / 잔액 / 이월 / 당기 / 잔액
        R2~: 데이터
        """
        header0 = ["계정코드", "계정명", "차변", "차변", "차변", "대변", "대변", "대변"]
        header1 = ["", "", "이월", "당기", "잔액", "이월", "당기", "잔액"]
        data_rows = [
            [r["code"], r["name"], r["odrs"], r["pdr"], r["cdr"],
             r["ocr"], r["pcr"], r["ccr"]]
            for r in rows
        ]
        return pd.DataFrame([header0, header1] + data_rows)

    def test_multiheader_two_sheets_returns_current_and_prior(self):
        """멀티헤더 2시트(2025년·2024년)에서 (당기, 전기) 쌍이 반환된다."""
        rows_2025 = [{"code": "11101010", "name": "현금",
                      "odrs": 80_000, "pdr": 100_000, "cdr": 150_000,
                      "ocr": 0, "pcr": 50_000, "ccr": 0}]
        rows_2024 = [{"code": "11101010", "name": "현금",
                      "odrs": 60_000, "pdr": 80_000, "cdr": 80_000,
                      "ocr": 0, "pcr": 40_000, "ccr": 0},
                     {"code": "11901010", "name": "구계정",
                      "odrs": 5_000, "pdr": 0, "cdr": 5_000,
                      "ocr": 0, "pcr": 0, "ccr": 0}]

        tmp_path = self._make_multiheader_xl({
            "2025년": self._multiheader_df(rows_2025),
            "2024년": self._multiheader_df(rows_2024),
        })
        try:
            loader = TbLoader()
            current, prior = loader.load_with_prior(tmp_path)
            assert "11101010" in current
            assert prior is not None
            assert "11101010" in prior
            assert "11901010" in prior   # 전기에만 있는 계정
            assert "11901010" not in current  # 당기에는 없음
        finally:
            import gc; gc.collect()  # Windows: 파일 핸들 해제 후 삭제
            try:
                tmp_path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_multiheader_single_sheet_returns_none_prior(self):
        """멀티헤더 시트가 1개뿐이면 prior=None이 반환된다."""
        rows = [{"code": "11101010", "name": "현금",
                 "odrs": 80_000, "pdr": 100_000, "cdr": 150_000,
                 "ocr": 0, "pcr": 50_000, "ccr": 0}]
        tmp_path = self._make_multiheader_xl({
            "2025년": self._multiheader_df(rows),
        })
        try:
            loader = TbLoader()
            current, prior = loader.load_with_prior(tmp_path)
            assert "11101010" in current
            assert prior is None
        finally:
            import gc; gc.collect()
            try:
                tmp_path.unlink(missing_ok=True)
            except PermissionError:
                pass
