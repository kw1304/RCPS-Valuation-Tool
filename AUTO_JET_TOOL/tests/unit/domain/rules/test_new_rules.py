"""A03·B01~B09 신규 룰 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from jet.domain.entities.journal_entry import JournalEntry
from jet.domain.rules.base import RuleContext


# ── 픽스처 헬퍼 ──────────────────────────────────────────────────────────

def _entry(
    entry_no: str,
    account_code: str,
    debit: float = 0.0,
    credit: float = 0.0,
    user_id: str = "TEST001",
    entry_type: str = "SA",
    posting_date: datetime | None = None,
    entry_date: datetime | None = None,
    account_name: str | None = None,
) -> JournalEntry:
    ed = entry_date or datetime(2025, 6, 15)
    pd_ = posting_date or datetime(2025, 6, 15)
    return JournalEntry(
        entry_no=entry_no,
        entry_date=ed,
        posting_date=pd_,
        posting_time=None,
        user_id=user_id,
        user_name=None,
        account_code=account_code,
        account_name=account_name,
        debit_amount=Decimal(str(debit)),
        credit_amount=Decimal(str(credit)),
        description=None,
        counterparty=None,
        entry_type=entry_type,
        dept_code=None,
        raw_row_index=0,
        is_system_generated=False,
    )


def _ctx(**kwargs) -> RuleContext:
    return RuleContext(
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        **kwargs,
    )


# ── Normalizer 격리 버그 수정 테스트 ─────────────────────────────────────

class TestNormalizerSystemEntry:
    """§A: user_id 결측 행을 SYSTEM-{전표유형}으로 채우는 테스트."""

    def test_missing_user_id_becomes_system(self):
        """user_id 결측 행이 격리되지 않고 SYSTEM-HR 로 처리된다."""
        import pandas as pd
        from jet.application.pipeline.normalizer import Normalizer

        n = Normalizer()
        df = pd.DataFrame([{
            "entry_no": "4900000001",
            "entry_date": "2025-01-15",
            "posting_date": "2025-01-15",
            "posting_time": None,
            "user_id": None,         # 결측
            "user_name": None,
            "account_code": "11101010",
            "account_name": "현금",
            "debit_amount": "1000000",
            "credit_amount": "0",
            "description": "HR 자동전표",
            "counterparty": None,
            "entry_type": "HR",
            "dept_code": None,
        }])

        entries, report = n.normalize(df)
        assert len(entries) == 1, "격리되지 않아야 함"
        assert report.quarantine_count == 0
        assert entries[0].user_id == "SYSTEM-HR"
        assert entries[0].is_system_generated is True

    def test_normal_user_id_not_system(self):
        """user_id가 있으면 is_system_generated=False 이다."""
        import pandas as pd
        from jet.application.pipeline.normalizer import Normalizer

        n = Normalizer()
        df = pd.DataFrame([{
            "entry_no": "1000000001",
            "entry_date": "2025-01-10",
            "posting_date": "2025-01-10",
            "posting_time": None,
            "user_id": "112230003",
            "user_name": None,
            "account_code": "11101010",
            "account_name": None,
            "debit_amount": "500000",
            "credit_amount": "0",
            "description": None,
            "counterparty": None,
            "entry_type": "SA",
            "dept_code": None,
        }])
        entries, report = n.normalize(df)
        assert entries[0].is_system_generated is False
        assert entries[0].user_id == "112230003"

    def test_other_required_field_missing_still_quarantined(self):
        """user_id 외 필수 필드(entry_no) 결측은 여전히 격리된다."""
        import pandas as pd
        from jet.application.pipeline.normalizer import Normalizer

        n = Normalizer()
        df = pd.DataFrame([{
            "entry_no": None,     # 필수 필드 결측
            "entry_date": "2025-01-10",
            "posting_date": "2025-01-10",
            "posting_time": None,
            "user_id": "112230003",
            "user_name": None,
            "account_code": "11101010",
            "account_name": None,
            "debit_amount": "500000",
            "credit_amount": "0",
            "description": None,
            "counterparty": None,
            "entry_type": "SA",
            "dept_code": None,
        }])
        entries, report = n.normalize(df)
        assert len(entries) == 0
        assert report.quarantine_count == 1


# ── A03 TB Rollforward ───────────────────────────────────────────────────

class TestA03TBRollforward:
    """A03 TB Rollforward 룰 테스트."""

    def test_matching_accounts_no_findings(self):
        """기초 + 차변 - 대변 = 기말인 경우 적출 없음."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        from jet.infrastructure.io.tb_loader import TrialBalance

        entries = [
            _entry("E001", "11101010", debit=100_000),
            _entry("E001", "11101010", credit=50_000),
        ]
        tb = {
            "11101010": TrialBalance(
                account_code="11101010", account_name="현금",
                opening_balance=500_000,
                period_debit=100_000, period_credit=50_000,
                closing_balance=550_000,
            )
        }
        rule = A03TBRollforward()
        rule.configure({})
        result = rule.apply(entries, _ctx(tb_master=tb))
        assert result.finding_count == 0

    def test_mismatch_detected(self):
        """기초 + 차변 - 대변 ≠ 기말이면 적출된다."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward
        from jet.infrastructure.io.tb_loader import TrialBalance

        entries = [_entry("E001", "11101010", debit=100_000)]
        tb = {
            "11101010": TrialBalance(
                account_code="11101010", account_name="현금",
                opening_balance=500_000,
                period_debit=0, period_credit=0,
                closing_balance=700_000,  # 기대: 600_000 but TB says 700_000
            )
        }
        rule = A03TBRollforward()
        rule.configure({})
        result = rule.apply(entries, _ctx(tb_master=tb))
        assert result.finding_count == 1

    def test_no_tb_master_skips(self):
        """tb_master 없으면 빈 결과 반환."""
        from jet.domain.rules.a03_tb_rollforward import A03TBRollforward

        rule = A03TBRollforward()
        rule.configure({})
        result = rule.apply([_entry("E001", "11101010", debit=1000)], _ctx())
        assert result.finding_count == 0
        assert result.params.get("skipped")


# ── B01 Large PL Items ────────────────────────────────────────────────────

class TestB01LargePLItem:
    """B01 Large P/L Items 룰 테스트."""

    def test_large_pl_detected(self):
        """매출의 0.5% 초과 PL 분개가 적출된다."""
        from jet.domain.rules.b01_large_pl import B01LargePLItem
        from jet.infrastructure.io.coa_loader import AccountMaster

        coa = {
            "40000000": AccountMaster("40000000", "매출", "P", None, "1000"),
            "50000000": AccountMaster("50000000", "매출원가", "P", None, "1000"),
        }
        # 매출 1억 → 임계치 50만원
        entries = [
            _entry("E001", "40000000", credit=100_000_000, account_name="매출"),
            _entry("E002", "50000000", debit=600_000, account_name="매출원가"),
        ]
        rule = B01LargePLItem()
        rule.configure({"materiality_ratio": 0.005})
        result = rule.apply(entries, _ctx(coa_master=coa))
        assert result.finding_count >= 1

    def test_small_pl_not_detected(self):
        """임계치 미만 PL 분개는 적출되지 않는다."""
        from jet.domain.rules.b01_large_pl import B01LargePLItem
        from jet.infrastructure.io.coa_loader import AccountMaster

        coa = {
            "40000000": AccountMaster("40000000", "매출", "P", None, "1000"),
            "50000000": AccountMaster("50000000", "매출원가", "P", None, "1000"),
        }
        # 매출 1억 → 임계치 50만원. E002 매출원가 10만(임계치 미달)만 검증 대상.
        # E001 매출 대변(임계치 산정 분개)는 절대값 1억 > 50만이라 적출 후 별도 검증.
        entries = [
            _entry("E001", "40000000", credit=100_000_000, account_name="매출"),
            _entry("E002", "50000000", debit=100_000, account_name="매출원가"),
        ]
        rule = B01LargePLItem()
        rule.configure({"materiality_ratio": 0.005})
        result = rule.apply(entries, _ctx(coa_master=coa))
        # E002(매출원가 10만)은 임계치 50만 미달 → 적출 X
        finding_codes = {f.entry_no for f in result.findings}
        assert "E002" not in finding_codes


# ── B04 Seldom Used ───────────────────────────────────────────────────────

class TestB04SeldomUsedAccount:
    """B04 Seldom Used Accounts 룰 테스트."""

    def test_seldom_detected(self):
        """5회 이하 계정이 적출된다."""
        from jet.domain.rules.b04_seldom_used import B04SeldomUsedAccount

        # 11901010은 3회, 11101010은 10회
        entries = (
            [_entry(f"E{i:03d}", "11901010", debit=1000) for i in range(3)] +
            [_entry(f"F{i:03d}", "11101010", debit=1000) for i in range(10)]
        )
        rule = B04SeldomUsedAccount()
        rule.configure({"max_usage_count": 5})
        result = rule.apply(entries, _ctx())
        # 11901010 사용 분개만 적출
        flagged_codes = {f.entry_no[:1] for f in result.findings}
        assert result.finding_count == 3

    def test_frequent_account_not_detected(self):
        """5회 초과 계정은 적출되지 않는다."""
        from jet.domain.rules.b04_seldom_used import B04SeldomUsedAccount

        entries = [_entry(f"E{i:03d}", "11101010", debit=1000) for i in range(10)]
        rule = B04SeldomUsedAccount()
        rule.configure({"max_usage_count": 5})
        result = rule.apply(entries, _ctx())
        assert result.finding_count == 0


# ── B05 Unusual User ─────────────────────────────────────────────────────

class TestB05UnusualUser:
    """B05 Unusual User 룰 테스트."""

    def _make_hr(self, active=None, retired=None):
        """간단한 HRMaster를 생성한다."""
        from jet.infrastructure.io.hr_loader import EmployeeRecord, HRMaster

        active_emps = {}
        for uid in (active or []):
            active_emps[uid] = EmployeeRecord(uid, "테스트", "부서", "G1", date(2020, 1, 1), None)

        retired_emps = {}
        for uid, retire_dt in (retired or []):
            retired_emps[uid] = EmployeeRecord(uid, "퇴직자", "부서", "G2", date(2018, 1, 1), retire_dt)

        return HRMaster(active_emps, retired_emps, {}, [])

    def test_unregistered_user_detected(self):
        """HR 미등록 사용자가 적출된다 (숫자 끝 사번 — 외부 패턴 미해당)."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        hr = self._make_hr(active=["U001"])
        # 사번이 숫자로 끝나야 알파벳 접미사 외부패턴 미해당 → 미등록으로 분류
        entries = [_entry("E001", "11101010", debit=1000, user_id="9900001")]
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply(entries, _ctx(hr_master=hr))
        assert result.finding_count == 1
        assert result.extra["not_registered_count"] == 1

    def test_post_retirement_detected(self):
        """퇴직 이후 전기일 분개가 적출된다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        retire_dt = date(2025, 3, 31)
        hr = self._make_hr(retired=[("U_RET", retire_dt)])
        entry = _entry("E001", "11101010", debit=1000, user_id="U_RET",
                        entry_date=datetime(2025, 5, 1))
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply([entry], _ctx(hr_master=hr))
        assert result.extra["post_retirement_count"] == 1

    def test_system_entry_classified_correctly(self):
        """SYSTEM-HR 자동전표는 시스템계정으로 분류된다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser
        from jet.domain.entities.journal_entry import JournalEntry

        hr = self._make_hr(active=["U001"])
        e = JournalEntry(
            entry_no="E_SYS", entry_date=datetime(2025, 1, 15),
            posting_date=datetime(2025, 1, 15), posting_time=None,
            user_id="SYSTEM-HR", user_name=None,
            account_code="11101010", account_name=None,
            debit_amount=Decimal("1000"), credit_amount=Decimal("0"),
            description=None, counterparty=None,
            entry_type="HR", dept_code=None, raw_row_index=0,
            is_system_generated=True,
        )
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply([e], _ctx(hr_master=hr))
        assert result.extra["system_account_count"] == 1
        assert result.extra["not_registered_count"] == 0


# ── B07 Back Dated ────────────────────────────────────────────────────────

class TestB07BackDatedEntry:
    """B07 Back Dated Entries 룰 테스트."""

    def test_delayed_entry_detected(self):
        """30일 초과 지연 입력이 적출된다."""
        from jet.domain.rules.b07_backdated_entry import B07BackDatedEntry

        entry = _entry("E001", "11101010", debit=1000,
                        entry_date=datetime(2025, 1, 1),
                        posting_date=datetime(2025, 2, 15))  # 45일 지연
        rule = B07BackDatedEntry()
        rule.configure({"max_delay_days": 30})
        result = rule.apply([entry], _ctx())
        assert result.finding_count == 1

    def test_reversed_entry_detected(self):
        """입력일 < 전기일 역행 분개가 적출된다."""
        from jet.domain.rules.b07_backdated_entry import B07BackDatedEntry

        entry = _entry("E001", "11101010", debit=1000,
                        entry_date=datetime(2025, 3, 1),
                        posting_date=datetime(2025, 1, 1))  # 입력일 < 전기일
        rule = B07BackDatedEntry()
        rule.configure({"max_delay_days": 30})
        result = rule.apply([entry], _ctx())
        assert result.finding_count == 1
        assert result.extra["backdated_findings"][0].delay_days < 0

    def test_normal_entry_not_detected(self):
        """30일 이내 정상 분개는 적출되지 않는다."""
        from jet.domain.rules.b07_backdated_entry import B07BackDatedEntry

        entry = _entry("E001", "11101010", debit=1000,
                        entry_date=datetime(2025, 1, 1),
                        posting_date=datetime(2025, 1, 15))  # 14일 정상
        rule = B07BackDatedEntry()
        rule.configure({"max_delay_days": 30})
        result = rule.apply([entry], _ctx())
        assert result.finding_count == 0


# ── B08 DocType Account Combo ─────────────────────────────────────────────

class TestB08DocTypeAccountCombo:
    """B08 Document Type × Account Combo 룰 테스트."""

    def test_rare_combo_detected(self):
        """매출 임계치 초과 분개의 (전표유형, 계정, 차/대변) 집계 행이 생성된다."""
        from jet.domain.rules.b08_doc_type_account import B08DocTypeAccountCombo

        # 매출 1억 → 임계치 50만원. 600,000 차변 분개가 임계치 초과
        entries = [
            _entry("E000", "40000000", credit=100_000_000, entry_type="SA", account_name="매출"),
            _entry("E001", "11101010", debit=600_000, entry_type="HR", account_name="현금"),
        ]
        rule = B08DocTypeAccountCombo()
        rule.configure({"materiality_ratio": 0.005})
        result = rule.apply(entries, _ctx())
        assert result.finding_count >= 1

    def test_below_threshold_not_detected(self):
        """매출 임계치 미달 분개는 집계 행에 포함되지 않는다."""
        from jet.domain.rules.b08_doc_type_account import B08DocTypeAccountCombo

        # 매출 1억 → 임계치 50만원. 1000원 라인은 모두 미달
        entries = (
            [_entry("E000", "40000000", credit=100_000_000, entry_type="SA", account_name="매출")] +
            [_entry(f"E{i:03d}", "11101010", debit=1000, entry_type="SA", account_name="현금") for i in range(1, 11)]
        )
        rule = B08DocTypeAccountCombo()
        rule.configure({"materiality_ratio": 0.005})
        result = rule.apply(entries, _ctx())
        # 11101010 라인(1000원)은 모두 미달 → 집계 행 0
        analysis_rows = result.extra.get("analysis_rows", [])
        assert not any(r.account_code == "11101010" for r in analysis_rows)


# ── B09 Counter Account ────────────────────────────────────────────────────

class TestB09CounterAccountAnalysis:
    """B09 Counter Account Analysis — 상대계정·참고계정 분석표 테스트."""

    def test_sub_scenarios_returned(self):
        """서브 시나리오 6개가 항상 반환된다."""
        from jet.domain.rules.b09_counter_account import B09CounterAccountAnalysis

        entries = [_entry("E001", "11101010", debit=1000), _entry("E001", "40000000", credit=1000)]
        rule = B09CounterAccountAnalysis()
        rule.configure({})
        result = rule.apply(entries, _ctx())
        sub_results = result.extra.get("b09_sub_results", [])
        assert len(sub_results) == 6
        codes = {sr.code for sr in sub_results}
        assert codes == {"B09-1", "B09-2", "B09-3", "B09-4", "B09-5", "B09-6"}

    def test_sales_counter_account_classified(self):
        """매출(4로 시작) 대변 분개의 상대계정이 분류된다.

        전표 E001:
            41101010 (매출)  대변 100만  → B09-1 본계정군
            11201010 (외상매출금) 차변 100만 → 상대계정 (차대 반대)
        """
        from jet.domain.rules.b09_counter_account import B09CounterAccountAnalysis

        entries = [
            _entry("E001", "41101010", credit=1_000_000, account_name="제품매출"),
            _entry("E001", "11201010", debit=1_000_000, account_name="외상매출금"),
        ]
        rule = B09CounterAccountAnalysis()
        rule.configure({})
        result = rule.apply(entries, _ctx())

        b09_1 = next(sr for sr in result.extra["b09_sub_results"] if sr.code == "B09-1")
        assert len(b09_1.rows) > 0

        # 상대계정(외상매출금)과 본계정(매출) 행이 존재해야 함
        types = {r.account_type for r in b09_1.rows}
        assert "상대계정" in types
        assert "본계정" in types
        # 명시 검증: 41101010 본계정 ← 11201010 상대계정 tuple 존재
        row_map = {
            (r.main_account_code, r.counter_account_code): r.account_type
            for r in b09_1.rows
        }
        assert row_map.get(("41101010", "11201010")) == "상대계정"

    def test_counter_account_direction(self):
        """상대계정(차대 반대) vs 참고계정(차대 동일) 분류가 정확하다.

        전표 E001:
            41101010 (매출)     대변 → 본계정 (대변)
            11201010 (외상매출금) 차변 → 상대계정 (대변의 반대 = 차변)
            25401010 (부가세예수금) 대변 → 참고계정 (대변과 동일)
        """
        from jet.domain.rules.b09_counter_account import B09CounterAccountAnalysis

        entries = [
            _entry("E001", "41101010", credit=1_000_000, account_name="제품매출"),
            _entry("E001", "11201010", debit=1_100_000, account_name="외상매출금"),
            _entry("E001", "25401010", credit=100_000, account_name="부가세예수금"),
        ]
        rule = B09CounterAccountAnalysis()
        rule.configure({})
        result = rule.apply(entries, _ctx())

        b09_1 = next(sr for sr in result.extra["b09_sub_results"] if sr.code == "B09-1")
        row_map = {
            (r.main_account_code, r.counter_account_code): r.account_type
            for r in b09_1.rows
        }
        # 41101010 기준 상대계정 = 11201010(차변)
        assert row_map.get(("41101010", "11201010")) == "상대계정"
        # 41101010 기준 참고계정 = 25401010(대변)
        assert row_map.get(("41101010", "25401010")) == "참고계정"
        # 자기 자신 = 본계정
        assert row_map.get(("41101010", "41101010")) == "본계정"

    def test_yaml_override_sub_scenarios(self):
        """YAML params.sub_scenarios 로 기본값을 교체할 수 있다."""
        from jet.domain.rules.b09_counter_account import B09CounterAccountAnalysis

        entries = [
            _entry("E001", "99001", credit=500_000),
            _entry("E001", "11101010", debit=500_000),
        ]
        rule = B09CounterAccountAnalysis()
        rule.configure({
            "sub_scenarios": [
                {
                    "code": "B09-X",
                    "name": "커스텀 계정군",
                    "main_account_patterns": ["^990"],
                }
            ]
        })
        result = rule.apply(entries, _ctx())
        sub_results = result.extra.get("b09_sub_results", [])
        assert len(sub_results) == 1
        assert sub_results[0].code == "B09-X"
        # 99001이 본계정군 → 분석 행 존재
        assert len(sub_results[0].rows) > 0

    def test_all_rows_aggregated(self):
        """b09_all_rows 에 전체 서브 시나리오 행이 통합된다."""
        from jet.domain.rules.b09_counter_account import B09CounterAccountAnalysis

        entries = [
            _entry("E001", "41101010", credit=1_000_000, account_name="제품매출"),
            _entry("E001", "11201010", debit=1_000_000, account_name="외상매출금"),
        ]
        rule = B09CounterAccountAnalysis()
        rule.configure({})
        result = rule.apply(entries, _ctx())

        all_rows = result.extra.get("b09_all_rows", [])
        assert isinstance(all_rows, list)
        # B09-1과 B09-2 각각 행이 있으므로 0보다 커야 함
        assert len(all_rows) > 0


# ── B03 TB 비교 fallback ──────────────────────────────────────────────────

class TestB03TBComparisonFallback:
    """B03 TB 비교 방식 (COA created_date 없을 때 전기 TB → 당기 TB diff)."""

    def test_tb_comparison_detects_new_account(self):
        """전기 TB에 없고 당기 TB에 있는 계정 분개가 적출된다."""
        from jet.domain.rules.b03_new_account import B03NewlyCreatedAccount
        from jet.infrastructure.io.tb_loader import TrialBalance

        # 당기 TB: 11101010(기존) + 11901010(신규)
        tb_current = {
            "11101010": TrialBalance("11101010", "현금", 0, 100_000, 50_000, 50_000),
            "11901010": TrialBalance("11901010", "신규계정", 0, 30_000, 0, 30_000),
        }
        # 전기 TB: 11101010만 있음
        tb_prior = {
            "11101010": TrialBalance("11101010", "현금", 0, 80_000, 40_000, 40_000),
        }
        entries = [
            _entry("E001", "11101010", debit=100_000),
            _entry("E002", "11901010", debit=30_000),   # 신규 계정 사용
        ]
        rule = B03NewlyCreatedAccount()
        rule.configure({})
        result = rule.apply(
            entries,
            _ctx(tb_master=tb_current, tb_master_prior=tb_prior),
        )
        assert result.finding_count == 1
        assert result.extra["detection_method"] == "tb_comparison"
        assert result.findings[0].entry_no == "E002"

    def test_coa_created_date_takes_priority_over_tb(self):
        """COA created_date가 있으면 TB 비교가 아니라 COA 방식을 사용한다."""
        from jet.domain.rules.b03_new_account import B03NewlyCreatedAccount
        from jet.infrastructure.io.coa_loader import AccountMaster
        from jet.infrastructure.io.tb_loader import TrialBalance

        coa = {
            "11901010": AccountMaster(
                "11901010", "신규계정(COA)", "B",
                date(2025, 3, 1), "1000"
            ),
        }
        tb_current = {
            "11101010": TrialBalance("11101010", "현금", 0, 100_000, 0, 100_000),
            "11901010": TrialBalance("11901010", "신규계정(COA)", 0, 30_000, 0, 30_000),
        }
        tb_prior = {
            "11101010": TrialBalance("11101010", "현금", 0, 80_000, 0, 80_000),
        }
        entries = [_entry("E001", "11901010", debit=30_000)]
        rule = B03NewlyCreatedAccount()
        rule.configure({})
        result = rule.apply(
            entries,
            _ctx(coa_master=coa, tb_master=tb_current, tb_master_prior=tb_prior),
        )
        assert result.extra["detection_method"] == "coa_created_date"
        assert result.finding_count == 1

    def test_no_coa_no_prior_tb_skips(self):
        """COA도 없고 전기 TB도 없으면 면제된다."""
        from jet.domain.rules.b03_new_account import B03NewlyCreatedAccount

        entries = [_entry("E001", "11901010", debit=30_000)]
        rule = B03NewlyCreatedAccount()
        rule.configure({})
        result = rule.apply(entries, _ctx())
        assert result.finding_count == 0
        assert result.params.get("skipped")

    def test_coa_without_created_date_falls_back_to_tb(self):
        """COA는 있지만 created_date가 없으면 TB 비교 fallback으로 동작한다."""
        from jet.domain.rules.b03_new_account import B03NewlyCreatedAccount
        from jet.infrastructure.io.coa_loader import AccountMaster
        from jet.infrastructure.io.tb_loader import TrialBalance

        # created_date=None인 COA
        coa = {
            "11101010": AccountMaster("11101010", "현금", "B", None, "1000"),
            "11901010": AccountMaster("11901010", "신규계정", "B", None, "1000"),
        }
        tb_current = {
            "11101010": TrialBalance("11101010", "현금", 0, 0, 0, 0),
            "11901010": TrialBalance("11901010", "신규계정", 0, 5_000, 0, 5_000),
        }
        tb_prior = {
            "11101010": TrialBalance("11101010", "현금", 0, 0, 0, 0),
        }
        entries = [_entry("E001", "11901010", debit=5_000)]
        rule = B03NewlyCreatedAccount()
        rule.configure({})
        result = rule.apply(
            entries,
            _ctx(coa_master=coa, tb_master=tb_current, tb_master_prior=tb_prior),
        )
        assert result.extra["detection_method"] == "tb_comparison"
        assert result.finding_count == 1


# ── B05 외부/계약직 패턴 확장 ─────────────────────────────────────────────

class TestB05ExternalAndSystemPatterns:
    """B05 외부/계약직(알파벳 접미사) 및 Z접두사 시스템 계정 분류 테스트."""

    def _make_hr(self, active=None, retired=None):
        from jet.infrastructure.io.hr_loader import EmployeeRecord, HRMaster
        active_emps = {}
        for uid in (active or []):
            active_emps[uid] = EmployeeRecord(uid, "직원", "부서", "G1", date(2020, 1, 1), None)
        retired_emps = {}
        for uid, retire_dt in (retired or []):
            retired_emps[uid] = EmployeeRecord(uid, "퇴직자", "부서", "G2", date(2018, 1, 1), retire_dt)
        return HRMaster(active_emps, retired_emps, {}, [])

    def test_z_prefix_classified_as_system(self):
        """Z접두사 사번(Z001, ZBATCH)은 시스템 계정으로 분류된다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        hr = self._make_hr()
        entries = [
            _entry("E001", "11101010", debit=1000, user_id="Z001"),
            _entry("E002", "11101010", debit=1000, user_id="ZBATCH"),
        ]
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply(entries, _ctx(hr_master=hr))
        assert result.extra["system_account_count"] == 2
        assert result.extra["not_registered_count"] == 0

    def test_alpha_suffix_classified_as_external(self):
        """알파벳 접미사 사번(1234567C, 9876543X)은 외부/계약직으로 분류된다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        hr = self._make_hr()
        entries = [
            _entry("E001", "11101010", debit=1000, user_id="1234567C"),
            _entry("E002", "11101010", debit=1000, user_id="9876543X"),
        ]
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply(entries, _ctx(hr_master=hr))
        assert result.extra["external_count"] == 2
        assert result.extra["not_registered_count"] == 0

    def test_z_prefix_beats_alpha_suffix(self):
        """Z접두사가 알파벳 접미사보다 우선 → 시스템으로 분류된다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        hr = self._make_hr()
        # ZBATCHC: Z접두사(시스템) AND C접미사(외부) — 시스템이 우선
        entries = [_entry("E001", "11101010", debit=1000, user_id="ZBATCHC")]
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply(entries, _ctx(hr_master=hr))
        assert result.extra["system_account_count"] == 1
        assert result.extra["external_count"] == 0

    def test_hr_registered_with_alpha_suffix_not_external(self):
        """HR에 등록된 사용자는 접미사 패턴과 무관하게 HR 경로로 처리된다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        # 1234567C가 HR에 등록되어 있으면 외부 분류 아님 (재직자로 정상 처리)
        hr = self._make_hr(active=["1234567C"])
        entries = [_entry("E001", "11101010", debit=1000, user_id="1234567C")]
        rule = B05UnusualUser()
        rule.configure({})
        result = rule.apply(entries, _ctx(hr_master=hr))
        assert result.extra["external_count"] == 0
        assert result.extra["not_registered_count"] == 0

    def test_external_patterns_yaml_override(self):
        """YAML external_user_patterns로 기본값을 교체할 수 있다."""
        from jet.domain.rules.b05_unusual_user import B05UnusualUser

        hr = self._make_hr()
        # 기본 패턴 끄고 ^VENDOR_ 만 외부로 지정
        entries = [
            _entry("E001", "11101010", debit=1000, user_id="VENDOR_123"),
            _entry("E002", "11101010", debit=1000, user_id="1234567C"),  # 기본패턴 꺼짐
        ]
        rule = B05UnusualUser()
        rule.configure({"external_user_patterns": [r"^VENDOR_"]})
        result = rule.apply(entries, _ctx(hr_master=hr))
        assert result.extra["external_count"] == 1       # VENDOR_123만
        assert result.extra["not_registered_count"] == 1  # 1234567C는 미등록
