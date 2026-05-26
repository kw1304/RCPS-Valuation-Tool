"""A03 Trial Balance Rollforward 룰.

기초TB + 당기 분개 금액 = 기말TB 검증.
계정코드별로 (기초잔액 + GL차변합 - GL대변합) vs TB기말잔액을 비교하여
1원이라도 차이나는 계정을 적출한다.

전제:
    RuleContext.tb_master가 주입되어 있어야 한다.
    주입되지 않은 경우 찾지 못함 상태(empty result)로 처리한다.

내부 정합 검증 방식:
    TB 로더가 기말잔액을 자기 정합으로 계산(opening + dr - cr)하기 때문에,
    GL 분개 합계와 TB 기말잔액을 비교하면 GL ↔ TB 일치 여부를 검증할 수 있다.
    BTI 합계잔액시산표 오적출(541건) 원인: TB 로더가 차변누계(190B)를 기말잔액으로
    잘못 읽어 GL 계산 기말과 비교시 거의 모든 계정 적출.
    수정 후: 기말잔액 = opening + abs(차변누계) - abs(대변누계) 로 자기 정합 강제.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

import pandas as pd

from jet.domain.entities.journal_entry import JournalEntry
from jet.domain.entities.rule_result import Finding, RuleResult
from jet.domain.exceptions import RuleConfigurationError
from jet.domain.rules.base import Rule, RuleContext

logger = logging.getLogger(__name__)

# 수치 비교 허용 오차 (부동소수점 오차 제거용, 1원 미만)
_TOLERANCE = 0.5


@dataclass
class TbMismatch:
    """TB 불일치 단일 계정 레코드.

    Attributes:
        account_code: 계정코드
        account_name: 계정과목명
        opening_balance: TB 기초잔액
        period_debit: GL 당기차변합계
        period_credit: GL 당기대변합계
        calculated_closing: 계산된 기말잔액 (기초 + GL차변 - GL대변)
        tb_closing: TB 실제 기말잔액 (opening + TB차변누계 - TB대변누계 자기정합)
        difference: 차이금액 (계산 - TB)
        gl_debit: GL 차변합 (= period_debit, 참고용)
        gl_credit: GL 대변합 (= period_credit, 참고용)
        tb_debit: TB 차변누계 (참고용)
        tb_credit: TB 대변누계 (참고용)
        dr_diff: 차변 차이 (참고용, 외부정합 관점)
        cr_diff: 대변 차이 (참고용, 외부정합 관점)
    """

    account_code: str
    account_name: str
    opening_balance: float
    period_debit: float
    period_credit: float
    calculated_closing: float
    tb_closing: float
    difference: float
    # 참고용 외부정합 필드
    gl_debit: float = 0.0
    gl_credit: float = 0.0
    tb_debit: float = 0.0
    tb_credit: float = 0.0
    dr_diff: float = 0.0
    cr_diff: float = 0.0


class A03TBRollforward(Rule):
    """A03 Trial Balance Rollforward.

    GL 분개의 계정별 차변합·대변합을 기초TB와 합산한 결과가
    기말TB와 일치하는지 검증한다(내부 정합).

    수행 시 RuleContext.tb_master가 필요하다. 미제공 시 경고 로그만 남기고
    empty result를 반환한다.
    """

    code = "A03"
    name = "TBRollforward"
    version = "2.0.0"
    severity = 5

    def configure(self, params: dict) -> None:
        """파라미터 없음 (tolerance는 내부 고정값 사용)."""

    def apply(
        self,
        entries: Iterable[JournalEntry],
        context: RuleContext,
    ) -> RuleResult:
        """GL 분개와 TB를 비교하여 불일치 계정을 적출한다."""
        started = datetime.now()

        if context.tb_master is None:
            logger.warning("A03: tb_master 미제공 — TB 검증 생략")
            return self._make_result(started, 0, [], {"skipped": "tb_master_not_provided"})

        # GL 집계: 계정코드 → (차변합, 대변합)
        all_entries = list(entries)
        if not all_entries:
            return self._make_result(started, 0, [], {})

        gl_debit: dict[str, float] = {}
        gl_credit: dict[str, float] = {}

        for e in all_entries:
            code = e.account_code.lstrip("0") or e.account_code
            gl_debit[code] = gl_debit.get(code, 0.0) + float(e.debit_amount)
            gl_credit[code] = gl_credit.get(code, 0.0) + float(e.credit_amount)

        tb = context.tb_master
        mismatches: list[TbMismatch] = []
        all_codes = set(gl_debit.keys()) | set(gl_credit.keys()) | set(tb.keys())

        # TB에 없는 계정(GL에만 존재; 9xxxx 명세·비망계정 등)은 A03 대상 외
        tb_missing_in_gl = [c for c in all_codes if c not in tb]
        if tb_missing_in_gl:
            logger.info(
                "A03: TB에 등록되지 않은 계정 %d개에서 GL 분개 발견 — A03 검증 대상 제외 "
                "(명세·비망계정 추정)",
                len(tb_missing_in_gl),
            )

        for code in sorted(all_codes):
            tb_rec = tb.get(code)
            if tb_rec is None:
                # TB에 없는 계정은 A03 검증 대상 아님 (사용자 방식)
                continue
            else:
                opening = tb_rec.opening_balance
                tb_closing = tb_rec.closing_balance
                acct_name = tb_rec.account_name
                tb_dr = tb_rec.period_debit
                tb_cr = tb_rec.period_credit

            # 손익계정은 회계연도 시작 시 결산이체를 통해 0으로 초기화된다.
            # 따라서 A03 검증 시 기초잔액을 0으로 강제 처리한다.
            #
            # 판단 우선순위:
            #   1. COA 마스터의 account_type == 'P' (손익계정 명시)
            #   2. COA 미제공 시 계정코드 첫자리 fallback: 4·5·6·7·8
            if self._is_income_statement_account(code, context):
                opening = 0.0

            period_dr = gl_debit.get(code, 0.0)
            period_cr = gl_credit.get(code, 0.0)
            calculated = opening + period_dr - period_cr
            diff = calculated - tb_closing

            if abs(diff) > _TOLERANCE:
                mismatches.append(TbMismatch(
                    account_code=code,
                    account_name=acct_name,
                    opening_balance=opening,
                    period_debit=period_dr,
                    period_credit=period_cr,
                    calculated_closing=calculated,
                    tb_closing=tb_closing,
                    difference=diff,
                    gl_debit=period_dr,
                    gl_credit=period_cr,
                    tb_debit=tb_dr,
                    tb_credit=tb_cr,
                    dr_diff=period_dr - tb_dr,
                    cr_diff=period_cr - tb_cr,
                ))

        findings = [
            Finding(
                entry_no=m.account_code,
                raw_row_index=-1,
                rule_code=self.code,
                rule_name=self.name,
                severity=self.severity,
                reason=(
                    f"계정 {m.account_code} TB 불일치: "
                    f"기초{m.opening_balance:,.0f} + 차변{m.period_debit:,.0f}"
                    f" - 대변{m.period_credit:,.0f} = {m.calculated_closing:,.0f}"
                    f" ≠ TB기말{m.tb_closing:,.0f} (차이: {m.difference:,.0f}원)"
                ),
                amount=Decimal(str(abs(m.difference))),
                entry_date=datetime(context.period_end.year, context.period_end.month, context.period_end.day),
            )
            for m in mismatches
        ]

        # 회사 범위 불일치 진단:
        # TB와 GL의 차변·대변 총합 비율이 1.5배 이상 차이가 나면
        # TB가 GL과 다른 회사 범위(예: 그룹 합산 vs 단일 회사)일 가능성을 의심
        gl_dr_total = sum(gl_debit.values())
        gl_cr_total = sum(gl_credit.values())
        tb_dr_total = sum(getattr(rec, "period_debit", 0.0) for rec in tb.values())
        tb_cr_total = sum(getattr(rec, "period_credit", 0.0) for rec in tb.values())
        scope_mismatch_warning = ""
        if gl_dr_total > 0 and tb_dr_total > 0:
            ratio = tb_dr_total / gl_dr_total
            if ratio > 1.5 or ratio < 0.67:
                scope_mismatch_warning = (
                    f"TB 차변합 {tb_dr_total:,.0f} vs GL 차변합 {gl_dr_total:,.0f} "
                    f"(비율 {ratio:.2f}). TB와 GL의 회사 범위가 다를 가능성 — "
                    f"적출 결과 해석 시 주의."
                )
                logger.warning("A03 회사 범위 불일치 의심: %s", scope_mismatch_warning)

        result = self._make_result(
            started,
            len(all_entries),
            findings,
            {"tolerance": _TOLERANCE, "accounts_checked": len(all_codes)},
        )
        result.extra["tb_mismatches"] = mismatches
        result.extra["accounts_checked"] = len(all_codes)
        result.extra["mismatch_count"] = len(mismatches)
        result.extra["scope_mismatch_warning"] = scope_mismatch_warning
        result.extra["gl_total_debit"] = gl_dr_total
        result.extra["gl_total_credit"] = gl_cr_total
        result.extra["tb_total_debit"] = tb_dr_total
        result.extra["tb_total_credit"] = tb_cr_total

        logger.info("A03 완료: %d계정 검증 / 불일치 %d건", len(all_codes), len(mismatches))
        return result

    @staticmethod
    def _is_income_statement_account(code: str, context: RuleContext) -> bool:
        """손익계정 여부를 판별한다.

        판단 우선순위:
            1. COA 마스터의 account_type == 'P' — 명시적 손익계정
            2. COA 미제공 또는 해당 코드 없음 → 계정코드 첫자리 fallback:
               '4'·'5'·'6'·'7'·'8' → 손익 (K-IFRS 표준 계정 체계)

        '7'·'8'을 포함하는 이유:
            한국 SAP 표준에서 기타손익(7)·금융손익(8)도 연초 결산이체 대상.
            COA 미제공 시 보수적으로 포함하여 오적출 방지.

        Args:
            code: 정규화된 계정코드
            context: 룰 실행 컨텍스트 (coa_master 참조)

        Returns:
            손익계정이면 True
        """
        if not code:
            return False

        # COA 마스터에 명시된 계정유형 우선
        if context.coa_master is not None:
            master = context.coa_master.get(code)
            if master is not None:
                return master.account_type == "P"

        # COA 미제공: 계정코드 첫자리 fallback
        stripped = code.lstrip("0")
        if stripped:
            return stripped[0] in ("4", "5", "6", "7", "8")
        return False
