"""ExcelReporter 확장 메서드 — A03·B01~B09·마스터 첨부 시트.

ExcelReporter 클래스에 mix-in 방식으로 적용된다.
이 파일은 직접 import 하지 말고, excel_reporter.py 의
_ReporterExt 클래스를 통해 사용한다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from jet.infrastructure.reporters.design_tokens import (
    ROW_HEIGHT_BODY,
    ROW_HEIGHT_HEADER,
    ROW_HEIGHT_KPI,
    ROW_HEIGHT_META,
    ROW_HEIGHT_TITLE,
)

# §5: 한국 회계 용어 (excel_reporter.py와 동일 상수 공유)
_TERM_LINE = "분개행"
_TERM_LINE_COUNT = "분개행 수"

if TYPE_CHECKING:
    import xlsxwriter
    from jet.application.workpaper.workpaper_spec import WorkpaperSpec
    from jet.domain.entities.rule_result import RuleResult
    from jet.infrastructure.io.hr_loader import HRMaster

logger = logging.getLogger(__name__)

_MASTER_MAX_ROWS = 50_000


class _ReporterExt:
    """ExcelReporter 확장 메서드 믹스인."""

    # ── A03 ──────────────────────────────────────────────────────────────

    def _write_a03_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("A03")
        self._apply_col_widths(ws, [14, 20, 14, 14, 14, 14, 14, 14])

        mismatches = result.extra.get("tb_mismatches", [])
        accounts_checked = result.extra.get("accounts_checked", 0)
        mismatch_count = result.extra.get("mismatch_count", len(mismatches))
        scope_warn = result.extra.get("scope_mismatch_warning", "")
        gl_dr_total = result.extra.get("gl_total_debit", 0)
        tb_dr_total = result.extra.get("tb_total_debit", 0)
        skipped = result.params.get("skipped", "")

        equity_adj_count = result.extra.get("equity_adjusted_codes", [])
        equity_note = (
            f" / 자본보정 적용 {len(equity_adj_count)}계정"
            if equity_adj_count else ""
        )

        if skipped:
            test_result = "TB 마스터 미제공으로 수행 생략"
        elif scope_warn:
            test_result = (
                f"{accounts_checked:,}계정 검증 / 불일치 {mismatch_count}계정 "
                f"(TB-GL 회사 범위 불일치 의심: TB 차변 {tb_dr_total:,.0f} vs "
                f"GL 차변 {gl_dr_total:,.0f}){equity_note}"
            )
        elif mismatch_count == 0:
            test_result = f"모든 계정 TB 일치 확인 ({accounts_checked:,}계정){equity_note}"
        else:
            test_result = f"{accounts_checked:,}계정 검증 / 불일치 {mismatch_count}계정 적출{equity_note}"

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "A03. Trial Balance Rollforward",
            "합계잔액시산표와 GL 분개 합계의 일치 여부 검증",
            "계정코드별로 (기초잔액 + 당기차변 - 당기대변) = TB기말잔액인지 검증하여 1원 이상 차이 계정을 적출한다.",
            test_result,
        )

        row = 7
        kpi_data = [
            ("검증 계정수", f"{accounts_checked:,}"),
            ("일치 계정수", f"{accounts_checked - mismatch_count:,}"),
            ("불일치 계정수", f"{mismatch_count:,}"),
        ]
        row = self._write_kpi_row(ws, fmt, kpi_data, row)

        if not mismatches:
            ws.set_row(row, ROW_HEIGHT_HEADER + 4)
            ws.merge_range(row, 0, row, 7, "불일치 계정 없음 — TB Rollforward 완료", fmt["pass_badge"])
            return

        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "TB 불일치 계정 목록", fmt["section_header"])
        row += 1

        headers = ["계정코드", "계정과목명", "기초잔액", "당기차변합", "당기대변합", "계산기말잔액", "TB기말잔액", "차이금액"]
        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, hdr in enumerate(headers):
            ws.write(row, ci, hdr, fmt["table_header"])
        row += 1

        for m in mismatches:
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, m.account_code, fmt["table_cell"])
            ws.write(row, 1, m.account_name, fmt["table_cell"])
            ws.write(row, 2, m.opening_balance, fmt["table_cell_num"])
            ws.write(row, 3, m.period_debit, fmt["table_cell_num"])
            ws.write(row, 4, m.period_credit, fmt["table_cell_num"])
            ws.write(row, 5, m.calculated_closing, fmt["table_cell_num"])
            ws.write(row, 6, m.tb_closing, fmt["table_cell_num"])
            diff_fmt = fmt["fail_badge"] if abs(m.difference) > 0.5 else fmt["warn_badge"]
            ws.write(row, 7, m.difference, diff_fmt)
            row += 1

        self._write_exec_meta(ws, fmt, result, row + 1)
        # §4: A03 인쇄 설정 — 가로 A4, 데이터 헤더 행 반복
        self._apply_print_setup(
            ws, spec,
            sheet_display_name="A03. TB Rollforward",
            landscape=True,
            fit_width=1,
            fit_height=0,
            repeat_header_row=row - len(mismatches) - 1 if mismatches else None,
        )

    # ── B01 ──────────────────────────────────────────────────────────────

    def _write_b01_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B01")
        self._apply_col_widths(ws, [14, 12, 14, 20, 10, 14, 14, 14])

        findings_data = result.extra.get("large_pl_findings", [])
        threshold = result.extra.get("threshold", 0)
        total_sales = result.extra.get("total_sales", 0)
        ratio = result.params.get("materiality_ratio", 0.005)
        mode = result.params.get("sales_calc_mode", "net_credit")
        abs_thr = result.params.get("absolute_threshold")

        if abs_thr is not None:
            test_method = (
                f"COA 손익계정(계정유형 P) 분개 중 외부 산정 임계치 초과 분개를 적출한다. "
                f"임계치: {threshold:,.0f}원 (GL 매출 참고: {total_sales:,.0f}원, mode={mode})"
            )
        else:
            test_method = (
                f"COA 손익계정(계정유형 P) 분개 중 매출액 × {ratio*100:.2f}% 초과 분개를 적출한다. "
                f"매출 산정: {mode} / 매출합계 {total_sales:,.0f}원 / 임계치 {threshold:,.0f}원"
            )
        unique_entries = result.extra.get("unique_entry_count", 0)
        if result.finding_count > 0:
            test_result = f"라인 {result.finding_count:,}건 / 전표 {unique_entries:,}개"
        else:
            test_result = "임계치 초과 분개 없음"

        self._write_rule_sheet_header(ws, fmt, spec, "B01. Large P/L Items Test",
                                      "손익계정 대형 분개 적출", test_method, test_result)
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("매출합계", f"{total_sales:,.0f}원"), ("임계치", f"{threshold:,.0f}원"),
            ("적출 (전표/라인)", f"{unique_entries:,}전표 / {result.finding_count:,}라인"),
        ], row)

        if findings_data:
            headers = ["전표번호", "전기일", "계정코드", "계정과목명", "적요", "차변금액", "대변금액", "최대금액"]
            rows = [[f.entry_no, f.entry_date.strftime("%Y-%m-%d"),
                     f.account_code, f.account_name or "", f.description or "",
                     f.debit_amount, f.credit_amount, f.max_amount] for f in findings_data]
            row = self._write_generic_entry_table(ws, fmt, headers, rows, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(ws, spec, "B01. Large P/L Items", landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    # ── B02 ──────────────────────────────────────────────────────────────

    def _write_b02_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B02")
        self._apply_col_widths(ws, [14, 12, 16, 24, 14, 14, 6, 10])

        findings_data = result.extra.get("unmatched_findings", [])
        skipped = result.params.get("skipped", "")
        test_result = "수행 생략" if skipped else (
            f"적출 {result.finding_count:,}건" if result.finding_count > 0 else "미등록 계정 없음"
        )

        self._write_rule_sheet_header(ws, fmt, spec, "B02. Unmatched Accounts Test",
                                      "COA 미등록 계정코드 사용 분개 적출",
                                      "분개 계정코드와 COA 마스터를 비교하여 미등록 계정코드를 적출한다.",
                                      test_result)
        row = 7
        if findings_data:
            headers = ["전표번호", "전기일", "계정코드", "적요", "차변금액", "대변금액", "", ""]
            rows = [[f.entry_no, f.entry_date.strftime("%Y-%m-%d"),
                     f.account_code, f.description or "", f.debit_amount, f.credit_amount, "", ""]
                    for f in findings_data]
            row = self._write_generic_entry_table(ws, fmt, headers, rows, row)
        else:
            ws.merge_range(row, 0, row, 7, "미등록 계정 없음" if not skipped else "COA 마스터 미제공", fmt["pass_badge"])

        self._write_exec_meta(ws, fmt, result, row + 2)
        self._apply_print_setup(ws, spec, "B02. Unmatched Accounts", landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    # ── B03 ──────────────────────────────────────────────────────────────

    def _write_b03_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B03")
        self._apply_col_widths(ws, [14, 20, 12, 14, 14, 14, 10, 10])

        new_accounts = result.extra.get("new_accounts", [])
        new_entries = result.extra.get("new_account_entries", [])
        unique_entries = result.extra.get("unique_entry_count", 0)
        used_count = result.extra.get("new_accounts_used_count", 0)
        skipped = result.params.get("skipped", "")

        test_result = (
            f"신규 계정 {len(new_accounts)}개 (GL 기표 {used_count}개) / "
            f"라인 {result.finding_count:,}건 / 전표 {unique_entries:,}개"
            if not skipped else "COA 마스터 미제공"
        )

        self._write_rule_sheet_header(
            ws, fmt, spec, "B03. Newly Created Accounts Test",
            "회계기간 중 신규 생성 계정 및 사용 분개 검토",
            "COA 생성일자가 회계기간 시작일~종료일 사이인 계정과 그 사용 분개를 적출한다.",
            test_result,
        )
        row = 7

        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, f"신규 생성 계정 목록 ({len(new_accounts)}건)", fmt["section_header"])
        row += 1

        if new_accounts:
            ws.set_row(row, ROW_HEIGHT_HEADER)
            ws.write(row, 0, "계정코드", fmt["table_header"])
            ws.write(row, 1, "계정과목명", fmt["table_header"])
            ws.write(row, 2, "생성일자", fmt["table_header"])
            row += 1
            for acct in new_accounts:
                ws.set_row(row, ROW_HEIGHT_BODY)
                ws.write(row, 0, acct["account_code"], fmt["table_cell"])
                ws.write(row, 1, acct["account_name"], fmt["table_cell"])
                ws.write(row, 2, str(acct["created_date"]), fmt["table_cell"])
                row += 1
        else:
            ws.write(row, 0, "신규 계정 없음", fmt["pass_badge"])
            row += 1

        row += 1
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, f"신규 계정 사용 분개 ({len(new_entries)}건)", fmt["section_header"])
        row += 1

        if new_entries:
            headers = ["전표번호", "전기일", "계정코드", "계정과목명", "생성일자", "차변금액", "대변금액", "적요"]
            rows = [[e.entry_no, e.entry_date.strftime("%Y-%m-%d"),
                     e.account_code, e.account_name,
                     str(e.account_created_date), e.debit_amount, e.credit_amount,
                     e.description or ""] for e in new_entries]
            row = self._write_generic_entry_table(ws, fmt, headers, rows, row)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(ws, spec, "B03. New Accounts", landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    # ── B04 ──────────────────────────────────────────────────────────────

    def _write_b04_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B04")
        self._apply_col_widths(ws, [14, 12, 14, 20, 8, 14, 14, 14])

        findings_data = result.extra.get("seldom_findings", [])
        seldom_acct_cnt = result.extra.get("seldom_account_count", 0)
        unique_entries = result.extra.get("unique_entry_count", 0)
        max_usage = result.params.get("max_usage_count", 5)

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B04. Seldom Used Accounts",
            "빈도수 낮은 계정 사용 분개 적출",
            f"당기 GL에서 계정코드별 사용 빈도를 집계하여 {max_usage}회 이하 계정과 해당 분개를 적출한다.",
            f"희소 계정 {seldom_acct_cnt:,}개 / 라인 {result.finding_count:,}건 / 전표 {unique_entries:,}개",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("희소 계정수", f"{seldom_acct_cnt:,}개"),
            ("기준 빈도", f"{max_usage}회 이하"),
            ("적출 (전표/라인)", f"{unique_entries:,}전표 / {result.finding_count:,}라인"),
        ], row)

        if findings_data:
            headers = ["전표번호", "전기일", "계정코드", "계정과목명", "사용빈도", "차변금액", "대변금액", "적요"]
            rows = [[f.entry_no, f.entry_date.strftime("%Y-%m-%d"),
                     f.account_code, f.account_name or "", f.usage_count,
                     f.debit_amount, f.credit_amount, f.description or ""]
                    for f in findings_data]
            row = self._write_generic_entry_table(ws, fmt, headers, rows, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(ws, spec, "B04. Seldom Used", landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    # ── B05 ──────────────────────────────────────────────────────────────

    # 분류별 정렬 순서 (B05 요약 표)
    _B05_CATEGORY_ORDER = {
        "HR 미등록": 0,
        "퇴직 후 입력": 1,
        "시스템 계정": 2,
        "그룹사 사번": 3,
    }
    # 분류별 unique 사용자 표에서 분류당 최대 표시 행수
    _B05_UNIQUE_USER_LIMIT = 100

    def _write_b05_sheet(self, wb, fmt, spec, result, mdata=None) -> None:
        skipped = result.params.get("skipped", "")
        not_reg = result.extra.get("not_registered_count", 0)
        post_ret = result.extra.get("post_retirement_count", 0)
        sys_cnt = result.extra.get("system_account_count", 0)
        aff_cnt = result.extra.get("affiliate_count", 0)
        findings_data = result.extra.get("unusual_findings", [])

        ws = wb.add_worksheet("B05")
        # 10열로 확장: 분류·세부유형·작성자명 추가로 열 너비 재설정
        self._apply_col_widths(ws, [14, 12, 14, 20, 10, 14, 12, 14, 18, 18])

        test_result = (
            f"HR 미등록 {not_reg:,}건 / 퇴직후입력 {post_ret:,}건 / "
            f"시스템 {sys_cnt:,}건 / 그룹사 {aff_cnt:,}건"
            if not skipped else "HR 마스터 미제공"
        )

        self._write_rule_sheet_header(
            ws, fmt, spec, "B05. Unusual User Test",
            "HR 비등록·퇴직 후 입력 사용자 분개 적출",
            "HR 인사 마스터와 GL 작성자 ID를 비교하여 미등록 사용자 및 퇴직 이후 입력 분개를 적출한다. "
            "시스템·인터페이스 ID, 그룹사 사번은 별도 분류.",
            test_result,
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("HR 미등록", f"{not_reg:,}건"),
            ("퇴직 후 입력", f"{post_ret:,}건"),
            ("시스템 계정", f"{sys_cnt:,}건"),
        ], row)
        row = self._write_kpi_row(ws, fmt, [
            ("그룹사 사번", f"{aff_cnt:,}건"),
            ("", ""),
            ("", ""),
        ], row)

        # ── 분류별 unique 사용자 요약 표 ─────────────────────────────────
        row = self._write_b05_unique_user_table(ws, fmt, findings_data, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(
            ws, spec, "B05. Unusual User",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=7,
        )

        # ── B05-1 상세 시트 (컬럼 확장) ──────────────────────────────────
        ws2 = wb.add_worksheet("B05-1")
        # 10열: 전표번호·전기일·입력일·작성자ID·작성자명·분류·세부유형·퇴직일·경과일수·최대금액
        self._apply_col_widths(ws2, [14, 12, 12, 14, 12, 12, 18, 12, 10, 14])
        ws2.set_row(0, ROW_HEIGHT_TITLE)
        ws2.merge_range(0, 0, 0, 9, "B05-1. Unusual User 상세 적출 목록", fmt["title"])
        row2 = 1

        if findings_data:
            headers = [
                "전표번호", "전기일", "입력일", "작성자ID", "작성자명",
                "분류", "세부유형", "퇴직일", "경과일수", "최대금액",
            ]
            rows = []
            for f in findings_data:
                post_str = f.posting_date.strftime("%Y-%m-%d") if f.posting_date else ""
                rows.append([
                    f.entry_no,
                    f.entry_date.strftime("%Y-%m-%d"),
                    post_str,
                    f.user_id,
                    getattr(f, "user_name", "") or "",
                    f.reason,
                    getattr(f, "detail_type", "") or "",
                    str(f.retire_date) if f.retire_date else "",
                    f.days_after_retirement or "",
                    max(f.debit_amount, f.credit_amount),
                ])
            self._write_generic_entry_table(ws2, fmt, headers, rows, row2)
        else:
            ws2.merge_range(row2, 0, row2, 9, "비정상 사용자 없음", fmt["pass_badge"])

        self._apply_print_setup(
            ws2, spec, "B05-1. Unusual User 상세",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=1,
        )

    def _write_b05_unique_user_table(self, ws, fmt, findings_data, start_row) -> int:
        """B05_OK 시트에 분류별 unique 사용자 요약 표를 작성한다.

        각 분류(미등록→퇴직후→시스템→그룹사)별로 unique 사번을 집계하여
        적출 건수 내림차순으로 정렬 후 표시한다.
        분류당 _B05_UNIQUE_USER_LIMIT 초과 시 "기타 N명" 안내 행을 추가한다.
        """
        from collections import defaultdict

        ws.set_row(start_row, ROW_HEIGHT_HEADER)
        ws.merge_range(
            start_row, 0, start_row, 9,
            "분류별 unique 사용자 목록 (건수 내림차순, 분류당 최대 100명)",
            fmt["section_header"],
        )
        start_row += 1

        # unique 사용자별 집계: {(category, user_id) → {name, detail_type, count, max_amount}}
        user_agg: dict[tuple, dict] = defaultdict(lambda: {
            "user_name": "", "detail_type": "", "count": 0, "max_amount": 0.0,
        })
        for f in findings_data:
            key = (f.reason, f.user_id)
            agg = user_agg[key]
            agg["user_name"] = getattr(f, "user_name", "") or agg["user_name"]
            agg["detail_type"] = getattr(f, "detail_type", "") or agg["detail_type"]
            agg["count"] += 1
            agg["max_amount"] = max(agg["max_amount"], max(f.debit_amount, f.credit_amount))

        # 분류별 정렬 후 카테고리 순 → 건수 내림차순
        sorted_entries = sorted(
            user_agg.items(),
            key=lambda x: (
                self._B05_CATEGORY_ORDER.get(x[0][0], 9),
                -x[1]["count"],
            ),
        )

        # 헤더
        headers = ["분류", "사번", "작성자명", "세부유형", "적출 건수", "최대금액", "", "", "", ""]
        ws.set_row(start_row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(headers[:6]):
            ws.write(start_row, ci, h, fmt["table_header"])
        start_row += 1

        if not sorted_entries:
            ws.merge_range(start_row, 0, start_row, 9, "적출 없음", fmt["pass_badge"])
            return start_row + 1

        # 분류당 최대 100명 제한 적용
        current_category = None
        category_count = 0
        category_total: dict[str, int] = {}
        # 먼저 분류별 총 사용자 수 집계
        for (cat, _uid), _ in sorted_entries:
            category_total[cat] = category_total.get(cat, 0) + 1

        written_per_cat: dict[str, int] = {}
        skipped_rows = []  # (category, total) — 초과분

        for (cat, uid), agg in sorted_entries:
            cnt_so_far = written_per_cat.get(cat, 0)
            if cnt_so_far >= self._B05_UNIQUE_USER_LIMIT:
                continue  # 초과분은 스킵 (아래에서 안내 행으로 처리)
            written_per_cat[cat] = cnt_so_far + 1

            ws.set_row(start_row, ROW_HEIGHT_BODY)
            ws.write(start_row, 0, cat, fmt["table_cell"])
            ws.write(start_row, 1, uid, fmt["table_cell"])
            ws.write(start_row, 2, agg["user_name"], fmt["table_cell"])
            ws.write(start_row, 3, agg["detail_type"], fmt["table_cell"])
            ws.write(start_row, 4, agg["count"], fmt["table_cell_num"])
            ws.write(start_row, 5, agg["max_amount"], fmt["table_cell_num"])
            start_row += 1

        # 초과분 안내 행
        for cat, total in category_total.items():
            shown = written_per_cat.get(cat, 0)
            if total > shown:
                ws.set_row(start_row, ROW_HEIGHT_BODY)
                ws.merge_range(
                    start_row, 0, start_row, 9,
                    f"  [{cat}] 기타 {total - shown:,}명 생략 — 전체 상세는 B05-1 시트 참조",
                    fmt["warn_badge"],
                )
                start_row += 1

        return start_row

    # ── B06 (Waive 또는 활성) ─────────────────────────────────────────────

    def _write_b06_waive_sheet(self, wb, fmt, spec, result) -> None:
        """B06 시트 작성.

        approver 데이터가 있으면 적출 결과 시트를, 없으면 Waive 안내 시트를 생성한다.
        """
        has_approver = result.extra.get("has_approver_data", False) if result else False

        if has_approver and result and not result.extra.get("waived"):
            self._write_b06_active_sheet(wb, fmt, spec, result)
        else:
            self._write_b06_waive_only_sheet(wb, fmt, spec, result)

    def _write_b06_active_sheet(self, wb, fmt, spec, result) -> None:
        """B06 활성 수행 결과 시트 (입력자=승인자 적출)."""
        ws = wb.add_worksheet("B06")
        self._apply_col_widths(ws, [14, 12, 14, 20, 12, 12, 14, 14])

        findings = result.extra.get("b06_findings", [])
        fc = len(findings)

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B06. Inappropriate User Test",
            "입력자 = 승인자 직무분리 위반 분개 적출",
            (
                "전표 입력자(user_id)와 승인자(approver)가 동일한 분개를 적출한다. "
                "직무분리(Segregation of Duties) 원칙상 입력과 승인은 별개 담당자가 수행해야 한다."
            ),
            f"직무분리 위반 {fc:,}건 적출" if fc > 0 else "직무분리 위반 없음",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("총 평가 분개", f"{result.total_entries_evaluated:,}건"),
            ("직무분리 위반", f"{fc:,}건"),
            ("", ""),
        ], row)

        if findings:
            headers = ["전표번호", "전기일", "계정코드", "계정과목명", "입력자", "승인자(동일)", "차변금액", "대변금액"]
            rows_data = []
            for f in findings:
                rows_data.append([
                    f.entry_no,
                    f.entry_date.strftime("%Y-%m-%d"),
                    f.account_code,
                    f.account_name or "",
                    f.user_id,
                    f.approver,
                    float(f.debit_amount),
                    float(f.credit_amount),
                ])
            row = self._write_generic_entry_table(ws, fmt, headers, rows_data, row + 1)
        else:
            ws.set_row(row + 1, ROW_HEIGHT_HEADER + 4)
            ws.merge_range(row + 1, 0, row + 1, 7,
                           "예외사항 없음 — 모든 전표의 입력자 ≠ 승인자 확인됨",
                           fmt["pass_badge"])
            row += 2

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(ws, spec, "B06. Inappropriate User",
                                landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    def _write_b06_waive_only_sheet(self, wb, fmt, spec, result) -> None:
        """B06 Waive 안내 시트 (승인자 데이터 미입수)."""
        ws = wb.add_worksheet("B06_waive")
        self._apply_col_widths(ws, [6, 16, 20, 20, 10, 10, 10, 10])

        ws.set_row(0, ROW_HEIGHT_TITLE)
        ws.merge_range(0, 0, 0, 7, "B06. Inappropriate User Test — 데이터 미입수", fmt["title"])
        ws.set_row(1, ROW_HEIGHT_META)
        ws.merge_range(1, 0, 1, 7, "처리자/승인자 직무분리 위반 검증", fmt["subtitle"])
        ws.set_row(2, 8)

        ws.set_row(3, ROW_HEIGHT_META)
        ws.write(3, 0, "수행여부", fmt["meta_label"])
        ws.merge_range(3, 1, 3, 3, "미수행 (Waived)", fmt["warn_badge"])
        ws.write(3, 4, "결산일", fmt["meta_label"])
        ws.write(3, 5, spec.period_end, fmt["meta_value"])

        ws.set_row(4, 6)
        ws.set_row(5, ROW_HEIGHT_HEADER)
        ws.merge_range(5, 0, 5, 7, "미수행 사유", fmt["section_header"])

        waive_reason = (
            result.extra.get("waive_reason") if result else
            "GL 추출본에 승인자(Approver) 컬럼이 포함되지 않아 직무분리 검증 불가."
        )
        ws.set_row(6, ROW_HEIGHT_BODY * 4)
        ws.merge_range(6, 0, 6, 7, waive_reason, fmt["result_text"])

        ws.set_row(7, 6)
        ws.set_row(8, ROW_HEIGHT_HEADER)
        ws.merge_range(8, 0, 8, 7, "향후 조치 사항", fmt["section_header"])
        ws.set_row(9, ROW_HEIGHT_BODY * 3)
        ws.merge_range(9, 0, 9, 7,
                       "권한 로그 또는 별도 전표 승인 로그 확보 후 재수행 권고.",
                       fmt["result_text"])
        self._apply_print_setup(ws, spec, "B06. Waived", landscape=False, fit_width=1, fit_height=0)

    # ── B07 ──────────────────────────────────────────────────────────────

    def _write_b07_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B07")
        self._apply_col_widths(ws, [14, 12, 12, 8, 14, 20, 14, 14])

        findings_data = result.extra.get("backdated_findings", [])
        max_delay = result.params.get("max_delay_days", 30)
        include_back = result.params.get("include_backdated", True)
        skipped_no_date = result.extra.get("skipped_no_date", 0)
        delayed = [f for f in findings_data if f.delay_days > 0]
        reversed_ = [f for f in findings_data if f.delay_days < 0]
        unique_late = result.extra.get("unique_late_entries", 0)
        unique_back = result.extra.get("unique_back_entries", 0)

        method = (
            f"전기일 대비 입력일이 {max_delay}일 초과인 지연 분개를 적출한다. "
            + ("역행(입력일<전기일) 분개도 함께 적출한다." if include_back else "역행 분개는 제외한다.")
        )
        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B07. Back Dated Entries Test",
            "전기일 vs 입력일 간격 과대 및 역행 분개 적출",
            method,
            f"지연 라인 {len(delayed):,}건 (전표 {unique_late:,}개) / "
            f"역행 라인 {len(reversed_):,}건 (전표 {unique_back:,}개) / "
            f"입력일 없음 {skipped_no_date:,}건 제외",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            (f"지연 ({max_delay}일↑) 전표/라인", f"{unique_late:,}/{len(delayed):,}"),
            ("역행 전표/라인", f"{unique_back:,}/{len(reversed_):,}"),
            ("입력일 없어 제외", f"{skipped_no_date:,}건"),
        ], row)

        if findings_data:
            headers = ["전표번호", "전기일", "입력일", "경과일수", "계정코드", "계정과목명", "차변금액", "대변금액"]
            rows = [[f.entry_no, f.entry_date.strftime("%Y-%m-%d"),
                     f.posting_date.strftime("%Y-%m-%d"),
                     f.delay_days, f.account_code, f.account_name or "",
                     f.debit_amount, f.credit_amount] for f in findings_data]
            row = self._write_generic_entry_table(ws, fmt, headers, rows, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(ws, spec, "B07. Back Dated", landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    # ── B08 ──────────────────────────────────────────────────────────────

    def _write_b08_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B08")
        self._apply_col_widths(ws, [8, 18, 14, 20, 8, 14, 14, 6])

        # B08 v2.0: 매출 임계치 초과 라인의 전표유형 × 계정 분석표
        # 하위 호환: 구버전 'combo_findings' 키도 인식
        analysis_rows = result.extra.get("analysis_rows", [])
        legacy_combos = result.extra.get("combo_findings", [])
        threshold = result.extra.get("threshold", 0)
        total_sales = result.extra.get("total_sales", 0)

        if analysis_rows:
            mode = result.params.get("sales_calc_mode", "net_credit")
            abs_thr = result.params.get("absolute_threshold")
            ratio = result.params.get("materiality_ratio", 0.005)
            method_text = (
                f"매출 {total_sales:,.0f}원의 {ratio*100:.2f}% "
                f"= {threshold:,.0f}원 초과 라인의 전표유형 × 계정 집계 (mode={mode})"
                if abs_thr is None
                else f"외부 산정 임계치 {threshold:,.0f}원 초과 라인의 전표유형 × 계정 집계"
            )
            self._write_rule_sheet_header(
                ws, fmt, spec,
                "B08. 전표유형-계정 분석",
                "매출 임계치 초과 전표의 전표유형별 계정 집계",
                method_text,
                f"임계치 초과 라인 → 분석표 {result.finding_count:,}행 생성",
            )
            row = 7
            row = self._write_kpi_row(ws, fmt, [
                ("매출 합계", f"{total_sales:,.0f}원"),
                ("임계치", f"{threshold:,.0f}원"),
                ("분석표 행수", f"{result.finding_count:,}행"),
            ], row)

            headers = ["전표유형", "전표유형내역", "계정코드", "계정과목명", "차변/대변", "차변합계", "대변합계", "라인수"]
            rows = [[r.entry_type, r.entry_type_name, r.account_code,
                     r.account_name, r.dr_cr, r.debit_total, r.credit_total, r.line_count]
                    for r in analysis_rows]
            row = self._write_generic_entry_table(ws, fmt, headers, rows, row + 1)
        else:
            # 레거시 출력 경로 (구버전 룰 호환)
            min_freq = result.params.get("min_frequency", 2)
            total_combos = result.extra.get("total_combos", 0)
            self._write_rule_sheet_header(
                ws, fmt, spec,
                "B08. 전표유형-계정 조합 분석",
                "전표유형별 비통상 계정 조합 적출",
                f"전표유형 × 계정코드 조합을 집계하여 {min_freq}회 이하 비통상 조합을 적출한다.",
                f"전체 조합 {total_combos:,}개 / 비통상 {result.finding_count:,}개",
            )
            row = 7
            row = self._write_kpi_row(ws, fmt, [
                ("전체 조합수", f"{total_combos:,}개"),
                (f"비통상 ({min_freq}회↓)", f"{result.finding_count:,}개"),
                ("", ""),
            ], row)
            if legacy_combos:
                headers = ["전표유형", "전표유형내역", "계정코드", "계정과목명", "빈도", "차변합계", "대변합계", ""]
                rows = [[f.entry_type, f.entry_type_name, f.account_code,
                         f.account_name, f.frequency, f.debit_total, f.credit_total, ""]
                        for f in legacy_combos]
                row = self._write_generic_entry_table(ws, fmt, headers, rows, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(ws, spec, "B08. DocType Analysis", landscape=True, fit_width=1, fit_height=0, repeat_header_row=7)

    # ── B09 ──────────────────────────────────────────────────────────────

    # B09 분석표 10열 헤더 (정답조서 R9 양식과 동일)
    _B09_HEADERS = [
        "계정코드", "계정과목", "차대변",
        "B09.계정코드", "B09.계정과목", "B09.차대변",
        "합계:B09.차변", "합계:B09.대변", "계정유형",
    ]
    _B09_COL_WIDTHS = [14, 22, 8, 14, 22, 8, 16, 16, 12]

    def _write_b09_sheet(self, wb, fmt, spec, result) -> None:
        sub_results = result.extra.get("b09_sub_results", [])
        all_rows = result.extra.get("b09_all_rows", [])

        # ── B09_OK: 전체 통합 시트 ─────────────────────────────────────────
        ws = wb.add_worksheet("B09")
        self._apply_col_widths(ws, self._B09_COL_WIDTHS)

        total_rows = len(all_rows)
        counter_rows = sum(1 for r in all_rows if r.account_type == "상대계정")

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B09. 상대계정 분석 (전체 통합)",
            "본계정군별 상대계정·참고계정 분석표 — 6개 서브 시나리오 통합",
            (
                "매출·매출채권·선급금·선수금·유형자산·건설중인자산 각 본계정군에 대해 "
                "동일 전표의 상대계정을 집계하여 상대계정/참고계정/본계정으로 분류한다."
            ),
            f"전체 분석행 {total_rows:,}행 / 상대계정 {counter_rows:,}건",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("전체 분석행", f"{total_rows:,}행"),
            ("상대계정", f"{counter_rows:,}건"),
            ("서브시나리오", f"{len(sub_results)}개"),
        ], row)

        if all_rows:
            data_rows = self._b09_rows_to_table(all_rows)
            row = self._write_b09_analysis_table(ws, fmt, data_rows, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(
            ws, spec, "B09. 상대계정 분석",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=9,
        )

        # ── B09-1_OK ~ B09-6_OK: 서브 시나리오 시트 ──────────────────────
        for sr in sub_results:
            self._write_b09_sub_sheet(wb, fmt, spec, sr)

    def _write_b09_sub_sheet(self, wb, fmt, spec, sr) -> None:
        """B09 서브 시나리오 시트를 정답조서 양식으로 작성한다.

        R1  : B09-N. {서브 시나리오 이름}
        R2~R7: 테스트 내역 본문 (write_rule_sheet_header)
        R9  : 10열 헤더
        R10~: 데이터 행
        """
        sheet_name = f"{sr.code}"
        ws = wb.add_worksheet(sheet_name)
        self._apply_col_widths(ws, self._B09_COL_WIDTHS)

        sub_rows = len(sr.rows)
        counter_cnt = sum(1 for r in sr.rows if r.account_type == "상대계정")

        self._write_rule_sheet_header(
            ws, fmt, spec,
            f"{sr.code}. {sr.name}",
            f"{sr.name} — 본계정군 상대계정·참고계정 분석",
            (
                f"{sr.name}에 해당하는 분개(본계정군)와 동일 전표의 모든 계정을 집계하여 "
                "상대계정(차대 반대)/참고계정(차대 동일)/본계정으로 분류한다."
            ),
            f"분석 행수 {sub_rows:,}행 / 상대계정 {counter_cnt:,}건",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("분석 행수", f"{sub_rows:,}행"),
            ("상대계정", f"{counter_cnt:,}건"),
            ("참고계정", f"{sum(1 for r in sr.rows if r.account_type == '참고계정'):,}건"),
        ], row)

        if sr.rows:
            data_rows = self._b09_rows_to_table(sr.rows)
            row = self._write_b09_analysis_table(ws, fmt, data_rows, row + 1)
        else:
            ws.set_row(row + 1, ROW_HEIGHT_HEADER + 4)
            ws.merge_range(
                row + 1, 0, row + 1, len(self._B09_HEADERS) - 1,
                "해당 본계정군 분개 없음",
                fmt["pass_badge"],
            )
            row += 2

        self._write_b09_exec_meta(ws, fmt, row + 1)
        self._apply_print_setup(
            ws, spec, f"{sr.code}. {sr.name}",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=9,
        )

    def _b09_rows_to_table(self, rows) -> list[list]:
        """B09CounterAccountRow 목록을 테이블 행 목록(9열)으로 변환한다."""
        return [
            [
                r.main_account_code,
                r.main_account_name,
                r.main_dr_cr,
                r.counter_account_code,
                r.counter_account_name,
                r.counter_dr_cr,
                r.total_debit,
                r.total_credit,
                r.account_type,
            ]
            for r in rows
        ]

    def _write_b09_analysis_table(self, ws, fmt, data_rows, start_row) -> int:
        """B09 분석표 헤더와 데이터를 작성한다 (9열 고정 양식)."""
        ws.set_row(start_row, ROW_HEIGHT_HEADER)
        for ci, hdr in enumerate(self._B09_HEADERS):
            ws.write(start_row, ci, hdr, fmt["table_header"])
        row = start_row + 1
        max_data_row = self._EXCEL_SHEET_ROW_LIMIT - 1

        for cells in data_rows:
            if row >= max_data_row:
                ws.merge_range(
                    row, 0, row, len(self._B09_HEADERS) - 1,
                    f"Excel 행 수 한도({self._EXCEL_SHEET_ROW_LIMIT:,}행) 근접 — 이하 생략",
                    fmt.get("warn_badge", fmt["table_cell"]),
                )
                row += 1
                break
            ws.set_row(row, ROW_HEIGHT_BODY)
            for ci, val in enumerate(cells):
                if isinstance(val, float) and ci in (6, 7):
                    ws.write(row, ci, val, fmt["table_cell_num"])
                else:
                    ws.write(row, ci, str(val) if val is not None else "", fmt["table_cell"])
            row += 1
        return row

    def _write_b09_exec_meta(self, ws, fmt, row) -> None:
        """B09 시트 하단 메타 정보 (실행일시 없이 간단하게)."""
        ws.set_row(row, ROW_HEIGHT_BODY)
        ws.merge_range(
            row, 0, row, len(self._B09_HEADERS) - 1,
            "JET 자동화 툴 생성 — B09 상대계정·참고계정 분석표",
            fmt["section_body"],
        )

    # ── §3: Stats_AutoManual 시트 ─────────────────────────────────────────

    # SAP 표준 자동전표 유형 (ISA 240 §A43 "자동 처리된 분개" 기준)
    # AF=자산결산, CO=원가/관리, HR=급여인사, MD=자재관리, ML=자재원장,
    # WA/WE/WL/WI/WN=창고·출하, CH=환산차이, PR=구매발주, M9=표준원가
    _AUTO_DOC_TYPES: frozenset = frozenset({
        "AF", "CO", "HR", "MD", "ML",
        "WA", "WE", "WL", "WI", "WN",
        "CH", "PR", "M9",
    })

    def _write_stats_auto_manual_sheet(
        self,
        wb,
        fmt,
        spec,
        entries,
        doc_type_master,
    ) -> None:
        """Stats_AutoManual 시트 — ISA 240 §A43 자동/수동 분개 통계.

        전표유형별 분개 건수·차변합·대변합·차변평균과
        자동/수동 분류 비율을 제공한다.

        자동전표 판별 기준:
            1. 전표유형이 _AUTO_DOC_TYPES에 포함되면 자동전표
            2. 전표유형 마스터의 settlement_type == 'SYSTEM'이면 자동전표
            3. 그 외는 수동전표
        """
        from collections import defaultdict

        ws = wb.add_worksheet("Stats_AutoManual")
        self._apply_col_widths(ws, [10, 28, 10, 16, 16, 16, 10, 14])

        ws.set_row(0, ROW_HEIGHT_TITLE)
        ws.merge_range(0, 0, 0, 7, "Stats_AutoManual — 자동/수동 분개 통계", fmt["title"])

        ws.set_row(1, ROW_HEIGHT_META)
        ws.merge_range(
            1, 0, 1, 7,
            f"ISA 240 §A43 — 자동 처리 여부별 분개 분류  /  "
            f"회사: {spec.company}  /  결산일: {spec.period_end}",
            fmt["subtitle"],
        )
        ws.set_row(2, 6)

        # ── 집계 ─────────────────────────────────────────────────────────
        agg: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "debit": 0.0, "credit": 0.0}
        )
        user_auto_count = 0
        total_lines = 0

        for e in entries:
            dt = (getattr(e, "entry_type", None) or "").strip().upper() or "(없음)"
            agg[dt]["count"] += 1
            agg[dt]["debit"] += float(e.debit_amount)
            agg[dt]["credit"] += float(e.credit_amount)
            total_lines += 1
            uid = (getattr(e, "user_id", None) or "").upper()
            if uid.startswith("SYSTEM-") or uid.startswith("SYSTEM_"):
                user_auto_count += 1

        # ── 분류 판별 ────────────────────────────────────────────────────
        def _classify(dt: str) -> str:
            if dt in self._AUTO_DOC_TYPES:
                return "자동전표"
            if doc_type_master:
                dm = doc_type_master.get(dt)
                if dm and getattr(dm, "settlement_type", "") == "SYSTEM":
                    return "자동전표"
            return "수동전표"

        # ── KPI 행 ───────────────────────────────────────────────────────
        auto_lines = sum(v["count"] for dt, v in agg.items() if _classify(dt) == "자동전표")
        manual_lines = total_lines - auto_lines
        auto_ratio = (auto_lines / total_lines * 100) if total_lines else 0.0

        row = 3
        row = self._write_kpi_row(ws, fmt, [
            ("총 분개 라인", f"{total_lines:,}건"),
            ("자동전표", f"{auto_lines:,}건 ({auto_ratio:.1f}%)"),
            ("수동전표", f"{manual_lines:,}건 ({100 - auto_ratio:.1f}%)"),
        ], row)

        # ── 전표유형별 상세 표 ───────────────────────────────────────────
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "전표유형별 분개 통계", fmt["section_header"])
        row += 1

        headers = ["전표유형", "전표유형내역", "분류", "건수", "차변합계", "대변합계", "차변평균", "차변합(%)"]
        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(headers):
            ws.write(row, ci, h, fmt["table_header"])
        row += 1

        total_debit_all = sum(v["debit"] for v in agg.values()) or 1.0
        sorted_dt = sorted(agg.items(), key=lambda x: -x[1]["count"])

        for dt, v in sorted_dt:
            cnt = v["count"]
            dr = v["debit"]
            cr = v["credit"]
            dr_avg = dr / cnt if cnt else 0.0
            dr_pct = dr / total_debit_all * 100
            cls = _classify(dt)

            dt_name = ""
            if doc_type_master:
                dm = doc_type_master.get(dt)
                if dm:
                    dt_name = getattr(dm, "description", "") or ""

            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, dt, fmt["table_cell"])
            ws.write(row, 1, dt_name, fmt["table_cell"])
            ws.write(row, 2, cls, fmt["table_cell"])
            ws.write(row, 3, cnt, fmt["table_cell_num"])
            ws.write(row, 4, dr, fmt["table_cell_num"])
            ws.write(row, 5, cr, fmt["table_cell_num"])
            ws.write(row, 6, dr_avg, fmt["table_cell_num"])
            ws.write(row, 7, round(dr_pct, 2), fmt["table_cell_num"])
            row += 1

        row += 1

        # ── SYSTEM-* 사용자 자동전표 별도 안내 ──────────────────────────
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "SYSTEM-* 사용자 자동전표", fmt["section_header"])
        row += 1
        ws.set_row(row, ROW_HEIGHT_BODY)
        ws.merge_range(
            row, 0, row, 7,
            f"SYSTEM-* 사용자 ID로 입력된 분개: {user_auto_count:,}건 "
            "(전표유형 분류와 별도 — 사용자 ID 기준 자동전표)",
            fmt["section_body"],
        )
        row += 2

        # ── 자동/수동 요약 ───────────────────────────────────────────────
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "자동/수동 분류 요약", fmt["section_header"])
        row += 1

        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(["분류", "전표유형 수", "분개 건수", "비율(%)", "차변합계", "", "", ""]):
            if h:
                ws.write(row, ci, h, fmt["table_header"])
        row += 1

        for cls_label in ("자동전표", "수동전표"):
            cls_types = [dt for dt in agg if _classify(dt) == cls_label]
            cls_cnt = sum(agg[dt]["count"] for dt in cls_types)
            cls_dr = sum(agg[dt]["debit"] for dt in cls_types)
            cls_pct = cls_cnt / total_lines * 100 if total_lines else 0.0
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, cls_label, fmt["table_cell"])
            ws.write(row, 1, len(cls_types), fmt["table_cell_num"])
            ws.write(row, 2, cls_cnt, fmt["table_cell_num"])
            ws.write(row, 3, round(cls_pct, 1), fmt["table_cell_num"])
            ws.write(row, 4, cls_dr, fmt["table_cell_num"])
            row += 1

        self._apply_print_setup(
            ws, spec, "Stats_AutoManual",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=3,
        )

    # ── 공통 헬퍼 ────────────────────────────────────────────────────────

    def _write_kpi_row(self, ws, fmt, kpi_data, start_row) -> int:
        ws.set_row(start_row, ROW_HEIGHT_KPI)
        ws.set_row(start_row + 1, ROW_HEIGHT_META)
        for i, (label, value) in enumerate(kpi_data[:4]):
            col_start = i * 2
            ws.merge_range(start_row, col_start, start_row, col_start + 1, value, fmt["accent_kpi"])
            ws.merge_range(start_row + 1, col_start, start_row + 1, col_start + 1, label, fmt["accent_kpi_label"])
        return start_row + 3

    # Excel 시트당 최대 행 수 (헤더 포함 1,048,576행 한도에서 안전 마진 확보)
    _EXCEL_SHEET_ROW_LIMIT = 1_048_000

    def _write_generic_entry_table(self, ws, fmt, headers, rows_data, start_row) -> int:
        """적출 데이터를 테이블로 작성한다.

        시작 행 + 헤더 행 + 데이터 행 합계가 Excel 한도에 근접하면
        안내 메시지를 추가하고 쓰기를 중단한다.
        (한도 초과 분할은 gl_loader_factory의 다중 업로드로 입력 단계에서 처리)
        """
        ws.set_row(start_row, ROW_HEIGHT_HEADER)
        for ci, hdr in enumerate(headers):
            ws.write(start_row, ci, hdr, fmt["table_header"])
        row = start_row + 1
        max_data_row = self._EXCEL_SHEET_ROW_LIMIT - 1  # 0-indexed

        for cells in rows_data:
            if row >= max_data_row:
                # Excel 한도 근접 — 안내 후 중단
                ws.merge_range(
                    row, 0, row, len(headers) - 1,
                    f"Excel 행 수 한도({self._EXCEL_SHEET_ROW_LIMIT:,}행) 근접 — 이하 데이터 생략. "
                    "전체 데이터는 CSV/Parquet 형식으로 재처리하거나 분할 파일을 사용하세요.",
                    fmt.get("warn_badge", fmt["table_cell"]),
                )
                row += 1
                break
            ws.set_row(row, ROW_HEIGHT_BODY)
            for ci, val in enumerate(cells):
                if isinstance(val, float):
                    ws.write(row, ci, val, fmt["table_cell_num"])
                elif isinstance(val, int) and ci > 1:
                    ws.write(row, ci, val, fmt["table_cell_num"])
                else:
                    ws.write(row, ci, str(val) if val is not None else "", fmt["table_cell"])
            row += 1
        return row

    def _write_exec_meta(self, ws, fmt, result, row) -> None:
        ws.set_row(row, ROW_HEIGHT_BODY)
        exec_at = result.executed_at.strftime("%Y-%m-%d %H:%M:%S")
        ws.merge_range(
            row, 0, row, 7,
            (f"실행일시: {exec_at}  /  룰버전: {result.rule_version}  /  "
             f"평가 라인: {result.total_entries_evaluated:,}건  /  "
             f"적출 {result.finding_count:,}건"),
            fmt["section_body"],
        )

    # ── 마스터 첨부 시트들 ────────────────────────────────────────────────

    def _write_master_sheet_header(self, ws, fmt, sheet_title, spec) -> int:
        ws.set_row(0, ROW_HEIGHT_TITLE)
        ws.merge_range(0, 0, 0, 7, sheet_title, fmt["title"])
        ws.set_row(1, ROW_HEIGHT_META)
        ws.merge_range(1, 0, 1, 7,
                       f"회사: {spec.company}  /  결산일: {spec.period_end}  /  JET 자동화 툴 생성",
                       fmt["subtitle"])
        ws.set_row(2, 6)
        return 3

    def _write_tb2025_sheet(self, wb, fmt, spec, tb_master) -> None:
        ws = wb.add_worksheet("TB2025")
        self._apply_col_widths(ws, [14, 24, 16, 16, 16, 16, 6, 6])
        row = self._write_master_sheet_header(ws, fmt, "합계잔액시산표 2025년", spec)

        headers = ["계정코드", "계정과목명", "기초잔액", "당기차변", "당기대변", "기말잔액", "", ""]
        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(headers[:6]):
            ws.write(row, ci, h, fmt["table_header"])
        row += 1

        rows_written = 0
        for code, tb in sorted(tb_master.items()):
            if rows_written >= _MASTER_MAX_ROWS:
                ws.merge_range(row, 0, row, 7,
                               f"이하 {len(tb_master) - rows_written:,}건 생략 (50,000행 상한)",
                               fmt["warn_badge"])
                break
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, code, fmt["table_cell"])
            ws.write(row, 1, tb.account_name, fmt["table_cell"])
            ws.write(row, 2, tb.opening_balance, fmt["table_cell_num"])
            ws.write(row, 3, tb.period_debit, fmt["table_cell_num"])
            ws.write(row, 4, tb.period_credit, fmt["table_cell_num"])
            ws.write(row, 5, tb.closing_balance, fmt["table_cell_num"])
            row += 1
            rows_written += 1
        self._apply_print_setup(ws, spec, "TB2025", landscape=True, fit_width=1, fit_height=0, repeat_header_row=3)

    def _write_doctype_sheet(self, wb, fmt, spec, doc_types) -> None:
        ws = wb.add_worksheet("전표유형")
        self._apply_col_widths(ws, [8, 24, 14, 8, 8, 8, 8, 8])
        row = self._write_master_sheet_header(ws, fmt, "전표유형 마스터", spec)

        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(["전표유형코드", "내역", "분류"]):
            ws.write(row, ci, h, fmt["table_header"])
        row += 1

        type_label = {"CLOSING": "결산조정", "SYSTEM": "시스템자동", "MANUAL": "수동입력"}
        for code, dt in sorted(doc_types.items()):
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, code, fmt["table_cell"])
            ws.write(row, 1, dt.description, fmt["table_cell"])
            ws.write(row, 2, type_label.get(dt.settlement_type, dt.settlement_type), fmt["table_cell"])
            row += 1
        self._apply_print_setup(ws, spec, "전표유형", landscape=False, fit_width=1, fit_height=0, repeat_header_row=3)

    def _write_coa_sheet(self, wb, fmt, spec, coa) -> None:
        ws = wb.add_worksheet("COA")
        self._apply_col_widths(ws, [14, 24, 8, 12, 8, 8, 8, 8])
        row = self._write_master_sheet_header(ws, fmt, "계정과목표 (SKA1)", spec)

        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(["계정코드", "계정과목명", "유형", "생성일자"]):
            ws.write(row, ci, h, fmt["table_header"])
        row += 1

        type_label = {"B": "BS(재무상태표)", "P": "PL(손익)"}
        rows_written = 0
        for code, acct in sorted(coa.items()):
            if rows_written >= _MASTER_MAX_ROWS:
                ws.merge_range(row, 0, row, 7,
                               f"이하 {len(coa) - rows_written:,}건 생략", fmt["warn_badge"])
                break
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, code, fmt["table_cell"])
            ws.write(row, 1, acct.account_name, fmt["table_cell"])
            ws.write(row, 2, type_label.get(acct.account_type, acct.account_type), fmt["table_cell"])
            ws.write(row, 3, str(acct.created_date) if acct.created_date else "", fmt["table_cell"])
            row += 1
            rows_written += 1
        self._apply_print_setup(ws, spec, "COA", landscape=False, fit_width=1, fit_height=0, repeat_header_row=3)

    def _write_user_sheet(self, wb, fmt, spec, user_df) -> None:
        ws = wb.add_worksheet("USER")
        self._apply_col_widths(ws, [14, 14, 14, 14, 14, 14, 10, 10])
        row = self._write_master_sheet_header(ws, fmt, "사용자 리스트 (USR02)", spec)

        if user_df is None or (hasattr(user_df, "empty") and user_df.empty):
            ws.merge_range(row, 0, row, 7, "사용자 데이터 없음", fmt["warn_badge"])
            return

        cols = list(user_df.columns[:8])
        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(cols):
            ws.write(row, ci, str(h), fmt["table_header"])
        row += 1

        rows_written = 0
        for _, data_row in user_df.iterrows():
            if rows_written >= _MASTER_MAX_ROWS:
                ws.merge_range(row, 0, row, 7,
                               f"이하 {len(user_df) - rows_written:,}건 생략", fmt["warn_badge"])
                break
            ws.set_row(row, ROW_HEIGHT_BODY)
            for ci, col in enumerate(cols):
                val = data_row.iloc[ci] if ci < len(data_row) else ""
                ws.write(row, ci, str(val) if val is not None else "", fmt["table_cell"])
            row += 1
            rows_written += 1
        self._apply_print_setup(ws, spec, "USER", landscape=True, fit_width=1, fit_height=0, repeat_header_row=3)

    def _write_hr_sheets(self, wb, fmt, spec, hr) -> None:
        configs = [
            ("1. 25년말재직자리스트", "2025년말 재직자 리스트",
             hr.active_employees, ["사번", "성명", "소속", "직급", "입사일"]),
            ("2-1 25년 퇴직자리스트", "2025년 퇴직자 리스트",
             hr.retired_employees, ["사번", "성명", "소속", "직급", "입사일", "퇴직일"]),
            ("2-2 25년 신규입사자", "2025년 신규입사자 리스트",
             hr.new_joiners, ["사번", "성명", "소속", "직급", "입사일"]),
        ]

        for sheet_name, title, emp_dict, headers in configs:
            ws = wb.add_worksheet(sheet_name)
            self._apply_col_widths(ws, [14, 14, 20, 12, 12, 12, 8, 8])
            row = self._write_master_sheet_header(ws, fmt, title, spec)

            ws.set_row(row, ROW_HEIGHT_HEADER)
            for ci, h in enumerate(headers):
                ws.write(row, ci, h, fmt["table_header"])
            row += 1

            rows_written = 0
            for uid, emp in emp_dict.items():
                if rows_written >= _MASTER_MAX_ROWS:
                    break
                ws.set_row(row, ROW_HEIGHT_BODY)
                row_vals = [uid, emp.name, emp.dept, emp.grade,
                            str(emp.join_date) if emp.join_date else "",
                            str(emp.retire_date) if emp.retire_date else ""]
                for ci, val in enumerate(row_vals[:len(headers)]):
                    ws.write(row, ci, val, fmt["table_cell"])
                row += 1
                rows_written += 1
            self._apply_print_setup(ws, spec, sheet_name, landscape=True, fit_width=1, fit_height=0, repeat_header_row=3)

        ws_tr = wb.add_worksheet("2-3  인사발령리스트")
        self._apply_col_widths(ws_tr, [14, 14, 24, 12, 12, 12, 8, 8])
        row = self._write_master_sheet_header(ws_tr, fmt, "2025년 인사발령 리스트", spec)

        ws_tr.set_row(row, ROW_HEIGHT_HEADER)
        for ci, h in enumerate(["사번", "성명", "발령내용", "직급"]):
            ws_tr.write(row, ci, h, fmt["table_header"])
        row += 1

        for emp in hr.transfers[:_MASTER_MAX_ROWS]:
            ws_tr.set_row(row, ROW_HEIGHT_BODY)
            ws_tr.write(row, 0, emp.user_id, fmt["table_cell"])
            ws_tr.write(row, 1, emp.name, fmt["table_cell"])
            ws_tr.write(row, 2, emp.dept, fmt["table_cell"])
            ws_tr.write(row, 3, emp.grade, fmt["table_cell"])
            row += 1
        self._apply_print_setup(ws_tr, spec, "인사발령리스트", landscape=True, fit_width=1, fit_height=0, repeat_header_row=3)

    # ── Q01 이상전표 질의서 ──────────────────────────────────────────────────

    # 질의서 시트 열 수 (Q 시트는 17열)
    _Q01_TOTAL_COLS = 17
    # 룰별 최대 적출 건수 (이 초과는 샘플링)
    _Q01_MAX_PER_RULE = 100

    def _write_q01_inquiry_sheet(
        self,
        wb: "xlsxwriter.Workbook",
        fmt: dict,
        spec: "WorkpaperSpec",
        results: dict,
    ) -> int:
        """Q01 이상전표 질의서 시트를 작성한다."""
        """Q01 이상전표 질의서 시트를 작성한다.

        모든 룰의 적출 분개를 통합하여 회사 소명 양식으로 출력한다.
        회사 답변 칸은 노란색(AMBER_BG) 강조로 빈 칸을 제공한다.

        Returns:
            작성된 총 질의 건수
        """
        from jet.infrastructure.reporters.design_tokens import (
            AMBER_BG, AMBER_FG, ACCENT_BG, ACCENT, TEXT, TEXT2, TEXT3,
            BG2, BG3, BORDER, WHITE,
        )

        ws = wb.add_worksheet("Q01_이상전표_질의서")

        # Q01은 17열 구성 — 열 너비 설정
        col_widths = [7, 8, 18, 22, 14, 12, 10, 14, 14, 14, 12, 24, 22, 14, 12, 20, 22]
        for i, w in enumerate(col_widths):
            ws.set_column(i, i, w)

        # ── 회사 답변 전용 서식 ─────────────────────────────────────────────
        fmt_answer_cell = wb.add_format({
            "font_name": "Pretendard",
            "font_size": 9,
            "font_color": TEXT,
            "bg_color": AMBER_BG,
            "valign": "vcenter",
            "align": "left",
            "text_wrap": True,
            "border": 1,
            "border_color": BORDER,
        })
        fmt_answer_header = wb.add_format({
            "font_name": "Pretendard",
            "font_size": 9,
            "bold": True,
            "font_color": AMBER_FG,
            "bg_color": AMBER_BG,
            "valign": "vcenter",
            "align": "center",
            "border": 1,
            "border_color": BORDER,
        })
        fmt_auditor_cell = wb.add_format({
            "font_name": "Pretendard",
            "font_size": 9,
            "font_color": TEXT2,
            "bg_color": ACCENT_BG,
            "valign": "vcenter",
            "align": "left",
            "text_wrap": True,
            "border": 1,
            "border_color": BORDER,
        })
        fmt_q_no = wb.add_format({
            "font_name": "Pretendard",
            "font_size": 9,
            "bold": True,
            "font_color": ACCENT,
            "bg_color": BG2,
            "valign": "vcenter",
            "align": "center",
            "border": 1,
            "border_color": BORDER,
        })
        fmt_section_sep = wb.add_format({
            "font_name": "Pretendard",
            "font_size": 9,
            "bold": True,
            "font_color": TEXT2,
            "bg_color": BG3,
            "valign": "vcenter",
            "align": "left",
            "border": 1,
            "border_color": BORDER,
            "italic": True,
        })

        # ── R1~R6 헤더 ─────────────────────────────────────────────────────
        _total_cols = self._Q01_TOTAL_COLS - 1  # 0-indexed 끝 열

        ws.set_row(0, ROW_HEIGHT_TITLE)
        ws.merge_range(0, 0, 0, _total_cols,
                       "Q01. 이상전표 질의서", fmt["title"])

        ws.set_row(1, ROW_HEIGHT_META)
        ws.merge_range(1, 0, 1, _total_cols,
                       "감사인 질의 — 회사 소명 양식", fmt["subtitle"])

        ws.set_row(2, 8)

        ws.set_row(3, ROW_HEIGHT_META)
        ws.write(3, 0, "회사명", fmt["meta_label"])
        ws.merge_range(3, 1, 3, 4, spec.company, fmt["meta_value"])
        ws.write(3, 5, "결산일", fmt["meta_label"])
        ws.merge_range(3, 6, 3, 8, spec.period_end, fmt["meta_value"])
        ws.write(3, 9, "작성자", fmt["meta_label"])
        ws.merge_range(3, 10, 3, 12, spec.preparer or "", fmt["meta_value"])
        ws.write(3, 13, "작성일", fmt["meta_label"])
        ws.merge_range(3, 14, 3, _total_cols, spec.prepared_date or "", fmt["meta_value"])

        # R5: 감사인 질의 방법 — 샘플링 설정 반영
        q01_sampling_pre = getattr(spec, "q01_sampling", {}) or {}
        _sampling_enabled = q01_sampling_pre.get("enabled", False)
        _sampling_method = q01_sampling_pre.get("method", "mus").upper()
        _sampling_n = q01_sampling_pre.get("n_per_rule", 50)
        if _sampling_enabled:
            _sampling_note = (
                f" ※ 표본추출 적용: {_sampling_method} 방법, 룰당 {_sampling_n}건 "
                "(총 적출 < 표본수이면 전체 포함 — ISA 530 §A23)"
            )
        else:
            _sampling_note = ""

        ws.set_row(4, ROW_HEIGHT_BODY * 3)
        ws.merge_range(
            4, 0, 4, _total_cols,
            (
                "【감사인 질의 방법】 본 시트는 각 룰(A01~B12)에서 적출된 이상전표를 통합하여 "
                "회사로부터 소명을 받기 위한 양식입니다. 회사는 각 행의 '회사 답변' 칸에 "
                f"사유 또는 정정 사항을 기재해 주시기 바랍니다.{_sampling_note}"
            ),
            fmt["result_text"],
        )

        ws.set_row(5, ROW_HEIGHT_BODY * 2)
        ws.merge_range(
            5, 0, 5, _total_cols,
            (
                "【작성 가이드】 회사 답변 작성 후 'JET 결과' 폴더에 동일 파일명으로 반납 → "
                "감사인이 검토 후 후속 절차 결정. 답변 불필요 항목은 '해당 없음'으로 기재."
            ),
            fmt["section_body"],
        )

        # ── KPI 카드 (R8) ───────────────────────────────────────────────────
        q01_sampling = getattr(spec, "q01_sampling", {}) or {}
        q01_rows = self._collect_q01_findings(results, q01_sampling=q01_sampling)
        active_rules = len({r["rule_code"] for r in q01_rows})
        total_findings = len(q01_rows)

        ws.set_row(6, 8)  # R7 구분선

        ws.set_row(7, ROW_HEIGHT_KPI)
        ws.set_row(8, ROW_HEIGHT_META)
        ws.set_row(9, ROW_HEIGHT_META - 4)

        kpi_items = [
            (f"{active_rules}", "적출 룰 수"),
            (f"{total_findings:,}", "총 적출 분개 행"),
            (f"{total_findings:,}", "답변 필요 항목"),
        ]
        for i, (val, label) in enumerate(kpi_items):
            cs = i * 4
            ws.merge_range(7, cs, 7, cs + 3, val, fmt["accent_kpi"])
            ws.merge_range(8, cs, 8, cs + 3, label, fmt["accent_kpi_label"])

        ws.set_row(10, 8)  # 구분선

        # ── 통합 적출 표 헤더 (R11) ────────────────────────────────────────
        table_headers = [
            "질의 번호", "룰 코드", "룰명", "적출 사유",
            "전표번호", "전기일", "계정코드", "계정과목명",
            "차변금액", "대변금액", "작성자", "적요",
            "회사 답변", "답변 작성자", "답변 일자", "후속 조치", "감사인 코멘트",
        ]
        ws.set_row(11, ROW_HEIGHT_HEADER)
        for ci, hdr in enumerate(table_headers):
            if hdr in ("회사 답변", "답변 작성자", "답변 일자"):
                ws.write(11, ci, hdr, fmt_answer_header)
            elif hdr == "감사인 코멘트":
                ws.write(11, ci, hdr, fmt["table_header"])
            else:
                ws.write(11, ci, hdr, fmt["table_header"])

        # ── 데이터 행 작성 ─────────────────────────────────────────────────
        row = 12
        prev_rule = None

        for q_data in q01_rows:
            # 룰 변경 시 구분 행 삽입
            if q_data["rule_code"] != prev_rule:
                prev_rule = q_data["rule_code"]
                ws.set_row(row, ROW_HEIGHT_BODY)
                sampling_lbl = q_data.get("sampling_label", "")
                if sampling_lbl:
                    sampled_note = f" ({sampling_lbl})"
                elif q_data.get("is_sampled"):
                    sampled_note = (
                        f" (전체 {q_data['section_total']:,}건 중 상위 "
                        f"{self._Q01_MAX_PER_RULE}건 표시)"
                    )
                else:
                    sampled_note = ""
                ws.merge_range(
                    row, 0, row, _total_cols,
                    f"[{q_data['rule_code']}]  {q_data['rule_name']}  — "
                    f"적출 {q_data['section_count']:,}건{sampled_note}",
                    fmt_section_sep,
                )
                row += 1

            ws.set_row(row, ROW_HEIGHT_BODY)

            # 질의 번호
            ws.write(row, 0, q_data["q_no"], fmt_q_no)
            # 룰 코드 (하이퍼링크: 해당 룰 시트로 이동)
            sheet_ref = q_data.get("sheet_ref", "")
            if sheet_ref:
                try:
                    ws.write_url(
                        row, 1,
                        f"internal:'{sheet_ref}'!A1",
                        fmt["table_cell"],
                        q_data["rule_code"],
                    )
                except Exception:
                    ws.write(row, 1, q_data["rule_code"], fmt["table_cell"])
            else:
                ws.write(row, 1, q_data["rule_code"], fmt["table_cell"])
            ws.write(row, 2, q_data["rule_name"], fmt["table_cell"])
            ws.write(row, 3, q_data["reason"], fmt["table_cell"])
            ws.write(row, 4, q_data["entry_no"], fmt["table_cell"])
            ws.write(row, 5, q_data["entry_date"], fmt["table_cell"])
            ws.write(row, 6, q_data["account_code"], fmt["table_cell"])
            ws.write(row, 7, q_data["account_name"], fmt["table_cell"])
            ws.write(row, 8, q_data["debit_amount"], fmt["table_cell_num"])
            ws.write(row, 9, q_data["credit_amount"], fmt["table_cell_num"])
            ws.write(row, 10, q_data["user_id"], fmt["table_cell"])
            ws.write(row, 11, q_data["description"], fmt["table_cell"])
            # 회사 답변 칸 — 노란색 빈 칸
            ws.write(row, 12, "", fmt_answer_cell)
            ws.write(row, 13, "", fmt_answer_cell)
            ws.write(row, 14, "", fmt_answer_cell)
            ws.write(row, 15, "", fmt["table_cell"])
            ws.write(row, 16, "", fmt_auditor_cell)
            row += 1

        if total_findings == 0:
            ws.set_row(row, ROW_HEIGHT_HEADER + 4)
            ws.merge_range(row, 0, row, _total_cols,
                           "적출된 이상전표 없음 — 모든 룰에서 예외사항 발견되지 않음",
                           fmt["pass_badge"])
            row += 1

        # 인쇄 설정
        self._apply_print_setup(
            ws, spec,
            sheet_display_name="Q01. 이상전표 질의서",
            landscape=True,
            fit_width=1,
            fit_height=0,
            repeat_header_row=11,
        )

        return total_findings

    def _collect_q01_findings(
        self,
        results: dict,
        q01_sampling: dict | None = None,
    ) -> list[dict]:
        """모든 룰 결과에서 적출 분개를 수집하여 Q01 질의서용 행 목록을 반환한다.

        q01_sampling.enabled=True이면 ISA 530 §A23 금액비례확률추출(MUS)·
        무작위·계통 추출 중 선택한 방법으로 룰당 N건만 포함한다.
        추출 방법이 비활성이면 기존 _Q01_MAX_PER_RULE(100건) 상한을 유지한다.

        Returns:
            질의서 행 딕셔너리 목록 (순서: 룰 코드 순)
        """
        from jet.domain.services.sampling import (
            mus_sample,
            random_sample,
            systematic_sample,
        )

        sampling = q01_sampling or {}
        sampling_enabled = sampling.get("enabled", False)
        sampling_method = str(sampling.get("method", "mus")).lower()
        n_per_rule = int(sampling.get("n_per_rule", 50))
        seed = int(sampling.get("seed", 42))

        q_rows: list[dict] = []
        q_counter = 1

        # 룰별 처리 정의: (룰코드, 시트명, 룰명, 적출 추출 함수)
        rule_defs = [
            ("B01", "B01",  "Large P/L Items",         self._extract_b01_findings),
            ("B04", "B04",  "Seldom Used Accounts",     self._extract_b04_findings),
            ("B05", "B05",  "Unusual User",             self._extract_b05_findings),
            ("B06", "B06",  "Inappropriate User",       self._extract_b06_findings),
            ("B07", "B07",  "Back Dated Entries",       self._extract_b07_findings),
            ("B08", "B08",  "전표유형-계정 조합 분석",  self._extract_b08_findings),
            ("B09", "B09",  "상대계정 조합 분석",       self._extract_b09_findings),
            ("B10", "B10",  "적요 부재·짧음·모호",      self._extract_b10_findings),
            ("B11", "B11",  "결산일 인접 분개",          self._extract_b11_findings),
            ("B12", "B12",  "결산조정 분개",             self._extract_b12_findings),
            ("A03", "A03",  "TB Rollforward 불일치",     self._extract_a03_findings),
        ]

        for rule_code, sheet_ref, rule_name, extractor in rule_defs:
            result = results.get(rule_code)
            if result is None:
                continue
            if result.extra.get("waived") or result.params.get("skipped"):
                continue

            raw_findings = extractor(result)
            if not raw_findings:
                continue

            total_count = len(raw_findings)

            if sampling_enabled:
                # 표본추출 방법 분기
                if sampling_method == "random":
                    display_findings = random_sample(raw_findings, n_per_rule, seed=seed)
                elif sampling_method == "systematic":
                    display_findings = systematic_sample(raw_findings, n_per_rule)
                else:
                    # 기본: MUS (금액 가중 — debit_amount + credit_amount를 amount로 활용)
                    # _extract_*_findings가 반환하는 dict는 debit_amount/credit_amount 보유
                    # MUS용 임시 래퍼: amount 속성을 추가한 namedtuple 대신 dict 직접 처리
                    class _Wrapper:
                        __slots__ = ("_d", "amount")
                        def __init__(self, d: dict) -> None:
                            self._d = d
                            self.amount = abs(d.get("debit_amount", 0.0)) + abs(d.get("credit_amount", 0.0))

                    wrapped = [_Wrapper(f) for f in raw_findings]
                    sampled_wrappers = mus_sample(wrapped, n_per_rule)
                    display_findings = [w._d for w in sampled_wrappers]

                is_sampled = total_count > n_per_rule
                sampling_label = f"{sampling_method.upper()} 표본 {len(display_findings)}건 / 총 {total_count}건"
            else:
                is_sampled = total_count > self._Q01_MAX_PER_RULE
                display_findings = raw_findings[:self._Q01_MAX_PER_RULE]
                sampling_label = ""

            for finding in display_findings:
                finding["q_no"] = f"Q-{q_counter:03d}"
                finding["rule_code"] = rule_code
                finding["rule_name"] = rule_name
                finding["sheet_ref"] = sheet_ref
                finding["section_count"] = len(display_findings)
                finding["section_total"] = total_count
                finding["is_sampled"] = is_sampled
                finding["sampling_label"] = sampling_label
                q_rows.append(finding)
                q_counter += 1

        return q_rows

    def _extract_b01_findings(self, result) -> list[dict]:
        findings = result.extra.get("large_pl_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": getattr(f, "user_id", ""),
                "description": f.description or "",
                "reason": f"중요성 기준 초과 손익 분개 ({float(f.max_amount):,.0f}원)",
            })
        return rows

    def _extract_b04_findings(self, result) -> list[dict]:
        findings = result.extra.get("seldom_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": getattr(f, "user_id", ""),
                "description": f.description or "",
                "reason": f"희소 계정 사용 (당기 {f.usage_count}회 사용)",
            })
        return rows

    def _extract_b05_findings(self, result) -> list[dict]:
        findings = result.extra.get("unusual_findings", [])
        rows = []
        for f in findings:
            debit = float(getattr(f, "debit_amount", 0))
            credit = float(getattr(f, "credit_amount", 0))
            user_name = getattr(f, "user_name", "") or ""
            detail_type = getattr(f, "detail_type", "") or ""
            # Q01 작성자 칸에 "사번 (성명)" 형태로 표시
            user_display = f"{f.user_id} ({user_name})" if user_name else f.user_id
            # 사유 = 분류 + 세부유형
            reason_display = f"{f.reason}" + (f" — {detail_type}" if detail_type else "")
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d") if hasattr(f.entry_date, "strftime") else str(f.entry_date),
                "account_code": getattr(f, "account_code", ""),
                "account_name": getattr(f, "account_name", "") or "",
                "debit_amount": debit,
                "credit_amount": credit,
                "user_id": user_display,
                "description": getattr(f, "description", "") or "",
                "reason": reason_display,
            })
        return rows

    def _extract_b06_findings(self, result) -> list[dict]:
        findings = result.extra.get("b06_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": f.user_id,
                "description": f.description or "",
                "reason": f"입력자·승인자 동일 (사번: {f.user_id})",
            })
        return rows

    def _extract_b07_findings(self, result) -> list[dict]:
        findings = result.extra.get("backdated_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": getattr(f, "user_id", ""),
                "description": getattr(f, "description", "") or "",
                "reason": (
                    f"소급 분개 (전기일 대비 {f.delay_days}일 후 입력)"
                    if f.delay_days > 0 else f"역행 분개 (입력일이 전기일보다 {abs(f.delay_days)}일 이전)"
                ),
            })
        return rows

    def _extract_b08_findings(self, result) -> list[dict]:
        # B08 v2.0: 분석표 행 (적출 의미가 아닌 거래 유형 분류)
        # 하위 호환: 구버전 combo_findings 키도 인식
        analysis_rows = result.extra.get("analysis_rows", [])
        if analysis_rows:
            rows = []
            for r in analysis_rows:
                rows.append({
                    "entry_no": f"(전표유형: {r.entry_type})",
                    "entry_date": "",
                    "account_code": r.account_code,
                    "account_name": r.account_name or "",
                    "debit_amount": float(r.debit_total),
                    "credit_amount": float(r.credit_total),
                    "user_id": "",
                    "description": r.entry_type_name or "",
                    "reason": f"전표유형-계정 분석 [{r.dr_cr}] — 라인 {r.line_count}건",
                })
            return rows
        # 레거시 경로
        legacy = result.extra.get("combo_findings", [])
        rows = []
        for f in legacy:
            rows.append({
                "entry_no": f"(전표유형: {f.entry_type})",
                "entry_date": "",
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_total),
                "credit_amount": float(f.credit_total),
                "user_id": "",
                "description": f.entry_type_name or "",
                "reason": f"비통상 전표유형-계정 조합 (빈도: {getattr(f, 'frequency', 0)}회)",
            })
        return rows

    def _extract_b09_findings(self, result) -> list[dict]:
        # 신규 양식: b09_all_rows 에서 상대계정 행만 Q01 질의서로 추출
        all_rows = result.extra.get("b09_all_rows", [])
        rows = []
        for r in all_rows:
            if r.account_type != "상대계정":
                continue
            rows.append({
                "entry_no": f"({r.main_account_code}↔{r.counter_account_code})",
                "entry_date": "",
                "account_code": r.main_account_code,
                "account_name": r.main_account_name or "",
                "debit_amount": float(r.total_debit),
                "credit_amount": float(r.total_credit),
                "user_id": "",
                "description": (
                    f"상대: {r.counter_account_name or r.counter_account_code} "
                    f"({r.counter_dr_cr})"
                ),
                "reason": (
                    f"상대계정 분석: {r.main_account_code}({r.main_dr_cr}) "
                    f"← {r.counter_account_code}({r.counter_dr_cr})"
                ),
            })
        return rows

    def _extract_a03_findings(self, result) -> list[dict]:
        mismatches = result.extra.get("tb_mismatches", [])
        rows = []
        for m in mismatches:
            rows.append({
                "entry_no": "(계정 단위 질의)",
                "entry_date": "",
                "account_code": m.account_code,
                "account_name": m.account_name or "",
                "debit_amount": float(m.calculated_closing) if m.calculated_closing >= 0 else 0.0,
                "credit_amount": float(abs(m.calculated_closing)) if m.calculated_closing < 0 else 0.0,
                "user_id": "",
                "description": f"TB 기말잔액: {m.tb_closing:,.0f}원 / GL 계산: {m.calculated_closing:,.0f}원",
                "reason": f"TB Rollforward 불일치 (차이: {m.difference:,.0f}원)",
            })
        return rows

    # ── B10 ──────────────────────────────────────────────────────────────

    def _write_b10_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B10")
        self._apply_col_widths(ws, [14, 12, 14, 16, 10, 20, 20, 14])

        findings_data = result.extra.get("no_desc_findings", [])
        absent = result.extra.get("absent_count", 0)
        short = result.extra.get("short_count", 0)
        vague = result.extra.get("vague_count", 0)
        min_len = result.params.get("min_length", 5)
        keywords = result.params.get("vague_keywords", [])

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B10. 적요 부재·짧음·모호 분개",
            "ISA 240 §A43 — 적절한 설명 없는 분개 적출",
            (
                f"적요 없음·{min_len}자 미만·의미 없는 키워드({', '.join(keywords[:5])}{' 등' if len(keywords) > 5 else ''})만 포함된 분개를 적출한다."
            ),
            f"적요 부재 {absent:,}건 / 짧음 {short:,}건 / 모호 {vague:,}건",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("적요 부재", f"{absent:,}건"),
            ("적요 짧음", f"{short:,}건"),
            ("적요 모호", f"{vague:,}건"),
        ], row)

        if findings_data:
            headers = ["전표번호", "전기일", "작성자ID", "작성자명", "분류", "적요원본", "계정과목명", "차변/대변"]
            rows_data = [
                [
                    f.entry_no,
                    f.entry_date.strftime("%Y-%m-%d"),
                    f.user_id,
                    f.user_name or "",
                    f.category,
                    f.description_raw or "",
                    f.account_name or "",
                    f"{f.debit_amount:,.0f} / {f.credit_amount:,.0f}",
                ]
                for f in findings_data
            ]
            row = self._write_generic_entry_table(ws, fmt, headers, rows_data, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(
            ws, spec, "B10. 적요 부재·짧음·모호",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=7,
        )

    def _extract_b10_findings(self, result) -> list[dict]:
        findings = result.extra.get("no_desc_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": f.user_id,
                "description": f.description_raw or "",
                "reason": f"{f.category} — ISA 240 §A43",
            })
        return rows

    # ── B11 ──────────────────────────────────────────────────────────────

    def _write_b11_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B11")
        self._apply_col_widths(ws, [14, 12, 12, 10, 10, 14, 16, 14])

        findings_data = result.extra.get("period_end_findings", [])
        proximity = result.extra.get("proximity_count", 0)
        post_input = result.extra.get("post_input_count", 0)
        days_before = result.params.get("days_before", 10)
        days_after = result.params.get("days_after", 10)
        period_end_str = result.params.get("period_end", "")

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B11. 결산일 인접 분개",
            "ISA 240 §A43 — 회계연도 종료일 임박 분개 적출",
            (
                f"결산일({period_end_str}) ±{days_before}/{days_after}일 이내 전기일 분개 및 "
                f"결산 후 소급입력(전기일≤결산일, 입력일>결산일) 분개를 적출한다."
            ),
            f"결산일 인접 {proximity:,}건 / 결산 후 입력 {post_input:,}건",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("결산일 인접", f"{proximity:,}건"),
            ("결산 후 입력", f"{post_input:,}건"),
            ("결산일", period_end_str),
        ], row)

        if findings_data:
            headers = [
                "전표번호", "전기일", "입력일", "결산일까지일수",
                "분류", "작성자ID", "계정과목명", "차변/대변",
            ]
            rows_data = [
                [
                    f.entry_no,
                    f.entry_date.strftime("%Y-%m-%d"),
                    f.posting_date.strftime("%Y-%m-%d") if f.posting_date else "",
                    f.days_to_period_end,
                    f.category,
                    f.user_id,
                    f.account_name or "",
                    f"{f.debit_amount:,.0f} / {f.credit_amount:,.0f}",
                ]
                for f in findings_data
            ]
            row = self._write_generic_entry_table(ws, fmt, headers, rows_data, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(
            ws, spec, "B11. 결산일 인접",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=7,
        )

    def _extract_b11_findings(self, result) -> list[dict]:
        findings = result.extra.get("period_end_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": f.user_id,
                "description": f.description or "",
                "reason": (
                    f"{f.category}: 전기일 {f.entry_date.strftime('%Y-%m-%d')} "
                    f"(결산일까지 {f.days_to_period_end:+d}일) — ISA 240 §A43"
                ),
            })
        return rows

    # ── B12 ──────────────────────────────────────────────────────────────

    def _write_b12_sheet(self, wb, fmt, spec, result) -> None:
        ws = wb.add_worksheet("B12")
        self._apply_col_widths(ws, [14, 12, 10, 18, 14, 16, 20, 14])

        findings_data = result.extra.get("topside_findings", [])
        days_around = result.params.get("days_around_period_end", 10)
        period_end_str = result.params.get("period_end", "")
        doc_types_list = result.params.get("closing_doc_types", [])

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "B12. 결산조정 분개",
            "ISA 240 §A43 — 사전 분석되지 않은 조정 분개 적출",
            (
                f"결산조정 전표유형({', '.join(sorted(doc_types_list)[:6])}{' 등' if len(doc_types_list) > 6 else ''}) 중 "
                f"결산일({period_end_str}) ±{days_around}일 이내 또는 결산일 이후 분개를 적출한다."
            ),
            f"{len(findings_data):,}건 적출",
        )
        row = 7
        row = self._write_kpi_row(ws, fmt, [
            ("결산조정 분개", f"{len(findings_data):,}건"),
            ("결산일", period_end_str),
            ("대상 전표유형", f"{len(doc_types_list)}종"),
        ], row)

        if findings_data:
            headers = [
                "전표번호", "전기일", "전표유형코드", "전표유형명",
                "작성자ID", "계정과목명", "적요", "차변/대변",
            ]
            rows_data = [
                [
                    f.entry_no,
                    f.entry_date.strftime("%Y-%m-%d"),
                    f.entry_type_code,
                    f.entry_type_name,
                    f.user_id,
                    f.account_name or "",
                    f.description or "",
                    f"{f.debit_amount:,.0f} / {f.credit_amount:,.0f}",
                ]
                for f in findings_data
            ]
            row = self._write_generic_entry_table(ws, fmt, headers, rows_data, row + 1)

        self._write_exec_meta(ws, fmt, result, row + 1)
        self._apply_print_setup(
            ws, spec, "B12. 결산조정 분개",
            landscape=True, fit_width=1, fit_height=0, repeat_header_row=7,
        )

    def _extract_b12_findings(self, result) -> list[dict]:
        findings = result.extra.get("topside_findings", [])
        rows = []
        for f in findings:
            rows.append({
                "entry_no": f.entry_no,
                "entry_date": f.entry_date.strftime("%Y-%m-%d"),
                "account_code": f.account_code,
                "account_name": f.account_name or "",
                "debit_amount": float(f.debit_amount),
                "credit_amount": float(f.credit_amount),
                "user_id": f.user_id,
                "description": f.description or "",
                "reason": (
                    f"결산조정 분개: 전표유형 {f.entry_type_code}({f.entry_type_name}) "
                    f"— ISA 240 §A43"
                ),
            })
        return rows
