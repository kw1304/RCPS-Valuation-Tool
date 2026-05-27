"""B03 Newly Created Accounts — 회계기간 중 신규 생성 계정 및 사용 분개 적출 룰.

회계기간 시작일(period_start) 이후에 생성된 계정과목을 식별하고,
해당 계정을 사용한 분개를 적출한다.

출력:
    (1) 신규 계정 목록
    (2) 신규 계정 사용 분개

식별 방법 (우선순위):
    1순위 — COA created_date 방식:
        RuleContext.coa_master가 있고 AccountMaster.created_date가 채워진
        레코드가 1건이라도 있을 때 사용한다.
        period_start <= created_date <= period_end 조건을 만족하는 계정을 신규로 본다.

    2순위 — TB 비교 방식 (fallback):
        COA created_date를 활용할 수 없을 때
        RuleContext.tb_master_prior(전기 TB)가 있으면 적용한다.
        set(당기 TB 계정코드) - set(전기 TB 계정코드) = 신규 계정.
        정답조서 기준: 전기 TB에 없고 당기 TB에 나타난 계정 = 당기 신규 개설 계정.

    3순위 — 면제:
        두 방법 모두 불가능하면 룰을 면제(skip)한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from jet.domain.entities.journal_entry import JournalEntry
from jet.domain.entities.rule_result import Finding, RuleResult
from jet.domain.rules.base import Rule, RuleContext

logger = logging.getLogger(__name__)


@dataclass
class NewAccountEntry:
    """신규 계정 사용 분개 상세."""

    entry_no: str
    entry_date: datetime
    account_code: str
    account_name: str
    account_created_date: date
    debit_amount: float
    credit_amount: float
    description: str | None


class B03NewlyCreatedAccount(Rule):
    """B03 Newly Created Accounts.

    회계기간 시작일 이후 생성된 계정과목 및 그 사용 분개를 적출한다.
    """

    code = "B03"
    name = "NewlyCreatedAccount"
    version = "1.0.0"
    severity = 3

    def configure(self, params: dict) -> None:
        """파라미터 없음 (period_start는 RuleContext에서 읽음)."""

    def apply(
        self,
        entries: Iterable[JournalEntry],
        context: RuleContext,
    ) -> RuleResult:
        """신규 생성 계정 사용 분개를 적출한다.

        식별 방법 결정:
            1순위: COA created_date — coa_master에 created_date가 채워진 계정이 있는 경우
            2순위: TB 비교 (fallback) — tb_master_prior가 있는 경우
            3순위: 면제
        """
        started = datetime.now()
        all_entries = list(entries)
        period_start = context.period_start
        period_end = context.period_end

        # 식별 방법 결정
        new_account_codes, new_accounts_info, detection_method = self._identify_new_accounts(
            context, period_start, period_end
        )

        if detection_method == "skipped":
            logger.warning("B03: COA created_date 없고 TB prior 없음 — 룰 스킵")
            return self._make_result(started, 0, [], {"skipped": "no_coa_created_date_and_no_prior_tb"})

        logger.info(
            "B03: 신규 계정 %d개 식별 (방법: %s, 회계기간: %s ~ %s)",
            len(new_accounts_info), detection_method, period_start, period_end,
        )

        # 신규 계정 사용 분개 적출
        coa = context.coa_master or {}
        matching_entries: list[NewAccountEntry] = []
        for e in all_entries:
            code = e.account_code
            code_stripped = code.lstrip("0") or code
            if code in new_account_codes or code_stripped in new_account_codes:
                coa_rec = coa.get(code) or coa.get(code_stripped)
                # 생성일: COA 방식은 실제 날짜, TB 비교 방식은 period_start 사용
                create_dt: date = period_start
                if coa_rec and coa_rec.created_date:
                    create_dt = coa_rec.created_date
                matching_entries.append(NewAccountEntry(
                    entry_no=e.entry_no,
                    entry_date=e.entry_date,
                    account_code=code,
                    account_name=e.account_name or (coa_rec.account_name if coa_rec else ""),
                    account_created_date=create_dt,
                    debit_amount=float(e.debit_amount),
                    credit_amount=float(e.credit_amount),
                    description=e.description,
                ))

        findings = [
            Finding(
                entry_no=f.entry_no,
                raw_row_index=-1,
                rule_code=self.code,
                rule_name=self.name,
                severity=self.severity,
                reason=self._build_reason(f, detection_method, period_start),
                amount=Decimal(str(max(f.debit_amount, f.credit_amount))),
                entry_date=f.entry_date,
            )
            for f in matching_entries
        ]

        unique_entries = {e.entry_no for e in matching_entries}
        used_new_account_codes = {e.account_code for e in matching_entries} | {
            e.account_code.lstrip("0") for e in matching_entries
        }
        new_accounts_used_count = sum(
            1 for info in new_accounts_info
            if info["account_code"] in used_new_account_codes
            or info["account_code"].lstrip("0") in used_new_account_codes
        )

        result = self._make_result(
            started,
            len(all_entries),
            findings,
            {
                "period_start": str(period_start),
                "period_end": str(period_end),
                "detection_method": detection_method,
            },
        )
        result.extra["new_accounts"] = new_accounts_info
        result.extra["new_account_entries"] = matching_entries
        result.extra["unique_entry_count"] = len(unique_entries)
        result.extra["new_accounts_used_count"] = new_accounts_used_count
        result.extra["detection_method"] = detection_method

        logger.info(
            "B03 완료: 신규계정 %d개(GL 기표 %d개) / 라인 %d건 / 전표 %d개 [%s]",
            len(new_accounts_info), new_accounts_used_count,
            len(matching_entries), len(unique_entries), detection_method,
        )
        return result

    def _identify_new_accounts(
        self,
        context: RuleContext,
        period_start: date,
        period_end: date,
    ) -> tuple[set[str], list[dict], str]:
        """신규 계정코드 집합·상세정보·감지방법 문자열을 반환한다.

        Returns:
            (new_account_codes, new_accounts_info, detection_method)
            detection_method: "coa_created_date" | "tb_comparison" | "skipped"
        """
        # 1순위: COA created_date
        if context.coa_master:
            coa_info = self._identify_by_coa(context.coa_master, period_start, period_end)
            if coa_info is not None:
                codes, info = coa_info
                return codes, info, "coa_created_date"

        # 2순위: TB 비교 (전기 TB → 당기 TB)
        if context.tb_master is not None and context.tb_master_prior is not None:
            codes, info = self._identify_by_tb_comparison(
                context.tb_master, context.tb_master_prior
            )
            return codes, info, "tb_comparison"

        return set(), [], "skipped"

    @staticmethod
    def _identify_by_coa(
        coa: dict,
        period_start: date,
        period_end: date,
    ) -> tuple[set[str], list[dict]] | None:
        """COA created_date로 신규계정을 식별한다.

        Returns:
            (codes, info) — created_date가 채워진 계정이 1건도 없으면 None 반환
            (None을 반환해야 2순위 TB 비교로 fallback 가능)
        """
        codes: set[str] = set()
        info: list[dict] = []
        has_created_date = False

        for code, master in coa.items():
            if master.created_date:
                has_created_date = True
                if period_start <= master.created_date <= period_end:
                    codes.add(code)
                    codes.add(code.lstrip("0") or code)
                    info.append({
                        "account_code": code,
                        "account_name": master.account_name,
                        "created_date": master.created_date,
                    })

        # COA에 created_date가 하나도 없으면 None → fallback 허용
        if not has_created_date:
            return None

        return codes, info

    @staticmethod
    def _identify_by_tb_comparison(
        tb_current: dict,
        tb_prior: dict,
    ) -> tuple[set[str], list[dict]]:
        """당기 TB와 전기 TB를 비교하여 신규계정을 식별한다.

        신규계정 = set(당기 TB 계정코드) - set(전기 TB 계정코드)

        전기 TB에 없고 당기에 처음 나타난 계정을 당기 신규 개설 계정으로 본다.
        이는 COA created_date 미제공 환경(더존·한컴 ERP 등)에서
        정답조서와 동일한 방법론이다.
        """
        prior_codes = set(tb_prior.keys()) | {c.lstrip("0") for c in tb_prior}
        codes: set[str] = set()
        info: list[dict] = []

        for code, tb_rec in tb_current.items():
            code_stripped = code.lstrip("0") or code
            if code not in prior_codes and code_stripped not in prior_codes:
                codes.add(code)
                codes.add(code_stripped)
                info.append({
                    "account_code": code,
                    "account_name": tb_rec.account_name,
                    "created_date": None,  # TB 비교 방식은 생성일 미상
                })

        logger.info(
            "B03 TB비교: 당기 %d계정 / 전기 %d계정 → 신규 %d계정",
            len(tb_current), len(tb_prior), len(info),
        )
        return codes, info

    @staticmethod
    def _build_reason(
        f: "NewAccountEntry",
        detection_method: str,
        period_start: date,
    ) -> str:
        """Finding reason 문자열을 생성한다."""
        if detection_method == "coa_created_date":
            return (
                f"신규 생성 계정 {f.account_code} 사용: "
                f"계정 생성일 {f.account_created_date} "
                f"(회계기간 시작: {period_start})"
            )
        # tb_comparison
        return (
            f"신규 계정(전기 TB 미존재) {f.account_code} 사용: "
            f"전기 TB에 없는 계정 (회계기간: {period_start}~)"
        )
