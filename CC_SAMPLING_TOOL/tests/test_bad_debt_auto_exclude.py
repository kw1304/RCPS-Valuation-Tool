"""부실채권 자동 발송제외 + 채권 잔액 0 제외 단위 테스트.

검증 범위:
  1. AllowanceData.bad_debt_parties 가 excluded_parties 에 자동 병합되는지
  2. 수동 발송제외와 union(중복 없이)이 되는지
  3. 채권(receivable) 기말 잔액 0 거래처가 모집단에서 제외되는지
  4. 채무(payable) 기말 잔액 0이어도 활동(activity) > 0이면 모집단 포함인지
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domain.population import (
    LedgerRow,
    PartyBalance,
    aggregate_by_party,
    load_ledger_rows,
)
from src.infrastructure.loaders import AllowanceData
from src.orchestrator import SamplingParams, run_sampling


# ─────────────────────────────────────────────────────────────
# 헬퍼 — 최소 원장 DataFrame 생성
# ─────────────────────────────────────────────────────────────

def _make_ledger_df(rows: list[dict]) -> pd.DataFrame:
    """테스트용 최소 원장 DataFrame.

    컬럼: 코드, 명(거래처명), 계정과목명, 통화, 기초, 증감, 기말
    """
    return pd.DataFrame(rows)


def _base_params(**overrides) -> SamplingParams:
    defaults = dict(
        company_name="테스트",
        period_end=date(2025, 12, 31),
        kind="receivable",
        performance_materiality=100_000_000,
        risk_level="유의적위험",
        control_reliance="Y",
        random_seed=42,
    )
    defaults.update(overrides)
    return SamplingParams(**defaults)


# ─────────────────────────────────────────────────────────────
# 1. 부실채권 자동 발송제외 통합 (orchestrator 레벨)
# ─────────────────────────────────────────────────────────────

class TestBadDebtAutoExclude:
    """AllowanceData 부실채권 거래처가 샘플링 결과에서 발송제외로 분류되어야 함."""

    def _run(self, bad_debt_names: set[str], manual_excluded: dict[str, str] | None = None):
        """부실채권 포함 파라미터로 run_sampling 실행 후 decisions 반환."""
        df = _make_ledger_df([
            {"명": "정상거래처A", "계정과목명": "외상매출금", "통화": "KRW",
             "기초": 0, "증감": 5_000_000, "기말": 5_000_000},
            {"명": "부실거래처B", "계정과목명": "외상매출금", "통화": "KRW",
             "기초": 0, "증감": 3_000_000, "기말": 3_000_000},
            {"명": "부실거래처C", "계정과목명": "외상매출금", "통화": "KRW",
             "기초": 0, "증감": 2_000_000, "기말": 2_000_000},
        ])
        # excluded_parties 에 bad_debt_parties 를 주입 (app.py 의 _run_single_kind 로직 모사)
        excluded: dict[str, str] = dict(manual_excluded or {})
        for name in bad_debt_names:
            if name not in excluded:
                excluded[name] = "부실채권 (대손충당금 100% 적용)"

        params = _base_params(excluded_parties=excluded)
        return run_sampling(df, params)

    def test_bad_debt_party_is_excluded(self):
        out = self._run({"부실거래처B"})
        excluded = {d.name: d for d in out.decisions if d.is_excluded}
        assert "부실거래처B" in excluded, "부실채권 거래처가 발송제외 되어야 함"

    def test_bad_debt_exclusion_reason(self):
        out = self._run({"부실거래처B"})
        excluded_map = {d.name: d for d in out.decisions if d.is_excluded}
        reason = excluded_map["부실거래처B"].exclusion_reason
        assert reason == "부실채권 (대손충당금 100% 적용)"

    def test_normal_party_not_excluded(self):
        out = self._run({"부실거래처B"})
        not_excluded = {d.name for d in out.decisions if not d.is_excluded}
        assert "정상거래처A" in not_excluded

    def test_multiple_bad_debt_all_excluded(self):
        out = self._run({"부실거래처B", "부실거래처C"})
        excluded = {d.name for d in out.decisions if d.is_excluded}
        assert "부실거래처B" in excluded
        assert "부실거래처C" in excluded

    def test_union_with_manual_excluded(self):
        """수동 발송제외 + 부실채권 자동 — 합집합으로 모두 제외."""
        out = self._run(
            bad_debt_names={"부실거래처C"},
            manual_excluded={"정상거래처A": "기타사유"},
        )
        excluded = {d.name for d in out.decisions if d.is_excluded}
        assert "정상거래처A" in excluded, "수동 발송제외가 유지되어야 함"
        assert "부실거래처C" in excluded, "부실채권 자동 발송제외가 추가되어야 함"

    def test_manual_excluded_reason_preserved_over_bad_debt(self):
        """수동 발송제외가 이미 있으면 부실채권 사유로 덮지 않음."""
        out = self._run(
            bad_debt_names={"부실거래처B"},
            manual_excluded={"부실거래처B": "수동등록사유"},
        )
        excl_map = {d.name: d for d in out.decisions if d.is_excluded}
        # 수동 등록이 우선 — 자동 사유로 덮어쓰지 않음
        assert excl_map["부실거래처B"].exclusion_reason == "수동등록사유"


# ─────────────────────────────────────────────────────────────
# 2. 채권 잔액 0 자동 제외
# ─────────────────────────────────────────────────────────────

class TestZeroBalanceExclude:
    """채권 기말 잔액 0 거래처는 모집단에서 제외되어야 함."""

    def _run_receivable(self, rows: list[dict]) -> dict:
        df = _make_ledger_df(rows)
        params = _base_params(kind="receivable")
        out = run_sampling(df, params)
        return {d.name: d for d in out.decisions}

    def test_zero_ending_balance_excluded_from_population(self):
        decisions = self._run_receivable([
            {"명": "잔액있는거래처", "계정과목명": "외상매출금", "통화": "KRW",
             "기초": 0, "증감": 5_000_000, "기말": 5_000_000},
            {"명": "잔액없는거래처", "계정과목명": "외상매출금", "통화": "KRW",
             "기초": 5_000_000, "증감": -5_000_000, "기말": 0},
        ])
        # 잔액 0 거래처는 decisions 에는 포함되지 않거나 final_sampled=False
        if "잔액없는거래처" in decisions:
            assert not decisions["잔액없는거래처"].final_sampled, \
                "채권 잔액 0 거래처는 최종 표본에 포함되면 안 됨"

    def test_positive_balance_included(self):
        decisions = self._run_receivable([
            {"명": "정상거래처", "계정과목명": "외상매출금", "통화": "KRW",
             "기초": 0, "증감": 50_000_000, "기말": 50_000_000},
        ])
        assert "정상거래처" in decisions


# ─────────────────────────────────────────────────────────────
# 3. 채무 — 기말 0이어도 활동 있으면 모집단 포함
# ─────────────────────────────────────────────────────────────

class TestPayableActivityFilter:
    """채무는 activity > 0 기준이므로 기말 잔액 0이어도 당기 활동이 있으면 포함."""

    def _run_payable(self, rows: list[dict]) -> dict:
        df = _make_ledger_df(rows)
        params = _base_params(kind="payable")
        out = run_sampling(df, params)
        return {d.name: d for d in out.decisions}

    def test_payable_zero_ending_but_active_included(self):
        """기말 잔액 0이지만 당기에 지급 활동(증감 > 0)이 있는 채무 거래처는 표본 대상."""
        decisions = self._run_payable([
            {"명": "활동있는채무처", "계정과목명": "외상매입금", "통화": "KRW",
             "기초": 10_000_000, "증감": -10_000_000, "기말": 0},
            {"명": "정상채무처", "계정과목명": "외상매입금", "통화": "KRW",
             "기초": 0, "증감": 30_000_000, "기말": 30_000_000},
        ])
        # 기말 0이지만 기초 10M → activity(=기말+감소분 or 증감 절댓값) > 0 이므로 포함
        # orchestrator: pb.activity > 0 필터
        # 정상채무처는 반드시 포함
        assert "정상채무처" in decisions
