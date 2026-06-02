"""ExcelReporter — xlsxwriter 기반 JET 감사조서 Excel 생성기.

생성 시트:
    7400        표지 조서 (회사정보·경영진 주장·절차 개요)
    7401        시나리오 목록 및 검토결과
    A01         DataIntegrity 상세 결과
    A02         DR/CR Balance 상세 결과
    A03         TB Rollforward 불일치 계정
    B01_OK      Large P/L Items 적출 결과
    B02_OK      Unmatched Accounts 적출 결과
    B03_OK      Newly Created Accounts (신규계정목록 + 사용분개)
    B04_OK      Seldom Used Accounts 적출 결과
    B05_OK      Unusual User 요약 결과
    B05-1       Unusual User 상세 적출 목록
    B06_waive   Inappropriate User — 데이터 미입수 안내
    B07_OK      Back Dated Entries 적출 결과
    B08_OK      DocType × Account Combo 적출 결과
    B09_OK      Counter Account Analysis 요약
    B09-1_OK ~ B09-6_OK  서브 시나리오별 시트
    TB2025      합계잔액시산표 원본 첨부
    전표유형      전표유형 마스터 첨부
    COA         계정과목표 첨부
    USER        사용자 리스트 첨부
    1. 25년말재직자리스트 / 2-1 25년 퇴직자리스트 / 2-2 25년 신규입사자 / 2-3  인사발령리스트

디자인은 design_tokens.py 의 서식 카탈로그를 사용하며
RCPS 툴과 동일한 Toss/Pretendard 팔레트를 공유한다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import xlsxwriter

from jet.application.workpaper.workpaper_spec import WorkpaperSpec
from jet.domain.entities.rule_result import RuleResult
from jet.domain.rules.a01_integrity import IntegrityStats
from jet.domain.rules.a02_dr_cr_balance import DrCrStats, ImbalancedEntry
from jet.infrastructure.reporters.design_tokens import (
    ACCENT,
    BORDER,
    ROW_HEIGHT_BODY,
    ROW_HEIGHT_HEADER,
    ROW_HEIGHT_KPI,
    ROW_HEIGHT_META,
    ROW_HEIGHT_TITLE,
    TEXT3,
    get_formats,
)

# ── 한국 회계 용어 사전 ───────────────────────────────────────────────────────
# 조서 전반에서 일관된 표현을 사용하기 위해 상수로 정의한다.
_TERM_LINE = "분개행"            # 전표라인 → 분개행
_TERM_LINE_COUNT = "분개행 수"   # 전표라인 수 → 분개행 수
_TERM_GL_LINE = "GL 분개행"      # GL 라인 → GL 분개행
_TERM_MISSING = "누락"           # 결측 → 누락
_TERM_TOLERANCE = "±0.01원"      # 0.01원 → ±0.01원

if TYPE_CHECKING:
    from jet.infrastructure.io.coa_loader import AccountMaster
    from jet.infrastructure.io.doc_type_loader import DocTypeMaster
    from jet.infrastructure.io.hr_loader import HRMaster
    from jet.infrastructure.io.tb_loader import TrialBalance

from jet.infrastructure.reporters._reporter_ext import _ReporterExt

# 마스터 첨부 시트 행 수 상한 (Excel 100만 행 제한 고려)
_MASTER_MAX_ROWS = 50_000

logger = logging.getLogger(__name__)

# 전체 조서 열 수 (A~H = 8열)
_TOTAL_COLS = 8
# 열 너비 설정 (단위: 문자 너비)
_COL_WIDTHS = [4, 14, 22, 22, 22, 10, 12, 12]


class ExcelReporter(_ReporterExt):
    """JET 감사조서 Excel 생성기.

    사용 방법:
        reporter = ExcelReporter()
        output_path = reporter.write(
            spec=spec,
            results={'A01': a01_result, 'A02': a02_result},
            output_path=Path('OUTPUT/7400_FY2025.xlsx'),
        )
    """

    def write(
        self,
        spec: WorkpaperSpec,
        results: dict[str, RuleResult],
        output_path: Path,
        master_data: dict | None = None,
    ) -> Path:
        """감사조서 Excel을 생성하고 파일 경로를 반환한다.

        Args:
            spec: 조서 스펙 (회사정보·시나리오 목록)
            results: 룰 코드 → RuleResult 딕셔너리
            output_path: 출력 파일 경로
            master_data: 마스터 첨부용 딕셔너리
                {
                  'coa': dict[str, AccountMaster],
                  'hr': HRMaster,
                  'doc_types': dict[str, DocTypeMaster],
                  'tb': dict[str, TrialBalance],
                  'user_df': pd.DataFrame,
                }

        Returns:
            생성된 파일의 절대 경로
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Excel 조서 생성 시작: %s", output_path)
        mdata = master_data or {}

        with xlsxwriter.Workbook(str(output_path)) as wb:
            fmt = get_formats(wb)

            self._write_7400_sheet(wb, fmt, spec)
            self._write_7401_sheet(wb, fmt, spec, results)

            # A 시리즈
            for scenario in spec.enabled_scenarios:
                code = scenario.code
                rule_result = results.get(code)
                if code == "A01" and rule_result:
                    self._write_a01_sheet(wb, fmt, spec, rule_result)
                elif code == "A02" and rule_result:
                    self._write_a02_sheet(wb, fmt, spec, rule_result)
                elif code == "A03" and rule_result:
                    self._write_a03_sheet(wb, fmt, spec, rule_result)

            # B 시리즈
            b_handlers = {
                "B01": self._write_b01_sheet,
                "B02": self._write_b02_sheet,
                "B03": self._write_b03_sheet,
                "B04": self._write_b04_sheet,
                "B07": self._write_b07_sheet,
                "B08": self._write_b08_sheet,
                "B09": self._write_b09_sheet,
                "B10": self._write_b10_sheet,
                "B11": self._write_b11_sheet,
                "B12": self._write_b12_sheet,
            }
            for scenario in spec.enabled_scenarios:
                code = scenario.code
                rule_result = results.get(code)
                if code == "B05" and rule_result:
                    # master_data를 전달하여 unique 사용자 표 렌더링에 활용
                    self._write_b05_sheet(wb, fmt, spec, rule_result, mdata=mdata)
                elif code in b_handlers and rule_result:
                    b_handlers[code](wb, fmt, spec, rule_result)

            # B06: 승인자 데이터 유무에 따라 활성/Waive 시트 자동 분기
            self._write_b06_waive_sheet(wb, fmt, spec, results.get("B06"))

            # Stats_AutoManual: 자동/수동 분개 통계 시트 (Q01 직전)
            entries_for_stats = mdata.get("entries")
            if entries_for_stats is not None:
                self._write_stats_auto_manual_sheet(
                    wb, fmt, spec,
                    entries_for_stats,
                    mdata.get("doc_types"),
                )

            # Q01 이상전표 질의서 (마스터 첨부 직전에 생성)
            self._write_q01_inquiry_sheet(wb, fmt, spec, results)

            # 마스터 첨부 시트
            if mdata.get("tb"):
                self._write_tb2025_sheet(wb, fmt, spec, mdata["tb"])
            if mdata.get("doc_types"):
                self._write_doctype_sheet(wb, fmt, spec, mdata["doc_types"])
            if mdata.get("coa"):
                self._write_coa_sheet(wb, fmt, spec, mdata["coa"])
            if mdata.get("user_df") is not None:
                self._write_user_sheet(wb, fmt, spec, mdata["user_df"])
            if mdata.get("hr"):
                self._write_hr_sheets(wb, fmt, spec, mdata["hr"])

        abs_path = output_path.resolve()
        logger.info("Excel 조서 생성 완료: %s", abs_path)
        return abs_path

    # ── 내부 헬퍼: 열 너비 ────────────────────────────────────────────────

    def _set_col_widths_helper(self, wb: xlsxwriter.Workbook) -> None:
        """열 너비 설정은 시트별로 적용하므로 여기서는 pass."""
        pass

    def _apply_col_widths(
        self,
        ws: Any,
        widths: list[float] | None = None,
    ) -> None:
        """시트에 열 너비를 적용한다."""
        target = widths or _COL_WIDTHS
        for i, w in enumerate(target):
            ws.set_column(i, i, w)

    # ── §10: 행 높이 동적 계산 ────────────────────────────────────────────

    @staticmethod
    def _calc_row_height(text: str, col_width_chars: int = 80, base_height: float = 18.0) -> float:
        """한국어 wrap 기준 행 높이를 추정한다 (1줄당 15.5pt 가정).

        Args:
            text: 셀에 입력할 텍스트
            col_width_chars: 열 너비(문자 단위)
            base_height: 최소 행 높이

        Returns:
            계산된 행 높이 (pt)
        """
        if not text:
            return base_height
        lines = max(1, (len(text) + col_width_chars - 1) // col_width_chars)
        return max(base_height, lines * 15.5)

    # ── §4: 인쇄 설정 헬퍼 ───────────────────────────────────────────────

    def _apply_print_setup(
        self,
        ws: Any,
        spec: Any,
        sheet_display_name: str,
        landscape: bool = True,
        fit_width: int = 1,
        fit_height: int = 0,
        repeat_header_row: int | None = None,
    ) -> None:
        """모든 시트 공통 인쇄 설정을 적용한다.

        Args:
            ws: xlsxwriter worksheet
            spec: WorkpaperSpec (회사명·조서코드 참조)
            sheet_display_name: 머리글 우측에 표시할 시트명
            landscape: True=가로 A4, False=세로 A4
            fit_width: fit_to_pages 너비 (1 = 1페이지 너비)
            fit_height: fit_to_pages 높이 (0 = 제한 없음)
            repeat_header_row: 반복 인쇄 행 인덱스 (0-based; None=사용 안 함)
        """
        ws.set_paper(9)  # A4
        if landscape:
            ws.set_landscape()
        else:
            ws.set_portrait()
        ws.fit_to_pages(fit_width, fit_height)
        ws.set_margins(left=0.5, right=0.5, top=0.75, bottom=0.75)
        ws.set_header(
            f"&L{spec.company}"
            f"&C{getattr(spec, 'workpaper_code', '7400')}"
            f"&R{sheet_display_name}"
        )
        if repeat_header_row is not None:
            ws.repeat_rows(repeat_header_row)

    # ── 공통 룰 시트 헤더 작성 (R1~R6) ───────────────────────────────────

    def _write_rule_sheet_header(
        self,
        ws: Any,
        fmt: dict,
        spec: WorkpaperSpec,
        sheet_title: str,
        sheet_subtitle: str,
        test_method: str,
        test_result: str,
    ) -> None:
        """모든 룰 시트 공통 헤더 6행을 작성한다.

        레이아웃:
            R1: 시트제목 (A1:H1 병합)
            R2: 부제 (A2:H2 병합)
            R3: 빈 행
            R4: 회사명 | {값} | 결산일 | {값} | 작성자 | {값} | 작성일 | {값}
            R5: [테스트 방법: 라벨] + [본문 B5:H5 병합]
            R6: [테스트 결과: 라벨] + [본문 B6:H6 병합]
        """
        # R1: 제목
        ws.set_row(0, ROW_HEIGHT_TITLE)
        ws.merge_range(0, 0, 0, 7, sheet_title, fmt["title"])

        # R2: 부제
        ws.set_row(1, ROW_HEIGHT_META)
        ws.merge_range(1, 0, 1, 7, sheet_subtitle, fmt["subtitle"])

        # R3: 빈 행
        ws.set_row(2, 8)

        # R4: 메타 정보
        ws.set_row(3, ROW_HEIGHT_META)
        ws.write(3, 0, "회사명", fmt["meta_label"])
        ws.write(3, 1, spec.company, fmt["meta_value"])
        ws.write(3, 2, "결산일", fmt["meta_label"])
        ws.write(3, 3, spec.period_end, fmt["meta_value"])
        ws.write(3, 4, "작성자", fmt["meta_label"])
        ws.write(3, 5, spec.preparer, fmt["meta_value"])
        ws.write(3, 6, "작성일", fmt["meta_label"])
        ws.write(3, 7, spec.prepared_date, fmt["meta_value"])

        # R5: 테스트 방법 — §10: 행 높이 동적 계산
        method_height = self._calc_row_height(test_method, col_width_chars=80, base_height=ROW_HEIGHT_BODY * 2)
        ws.set_row(4, method_height)
        ws.write(4, 0, "테스트 방법:", fmt["result_label"])
        ws.merge_range(4, 1, 4, 7, test_method, fmt["result_text"])

        # R6: 테스트 결과 — §10: 행 높이 동적 계산
        result_height = self._calc_row_height(test_result, col_width_chars=80, base_height=ROW_HEIGHT_BODY * 2)
        ws.set_row(5, result_height)
        ws.write(5, 0, "테스트 결과:", fmt["result_label"])
        ws.merge_range(5, 1, 5, 7, test_result, fmt["result_text"])

        # R7: 빈 행 (구분선)
        ws.set_row(6, 8)

    # ── 7400 표지 시트 ────────────────────────────────────────────────────

    def _write_7400_sheet(
        self,
        wb: xlsxwriter.Workbook,
        fmt: dict,
        spec: WorkpaperSpec,
    ) -> None:
        """7400 표지 조서 시트를 작성한다."""
        ws = wb.add_worksheet("7400")
        self._apply_col_widths(ws, [3, 12, 20, 14, 14, 10, 10, 10])

        row = 0

        # R1: 메인 제목
        ws.set_row(row, ROW_HEIGHT_TITLE)
        ws.merge_range(row, 0, row, 7, "입 증 감 사 절 차", fmt["title"])
        row += 1

        # R2: 부제목
        ws.set_row(row, ROW_HEIGHT_META + 4)
        ws.merge_range(
            row, 0, row, 7,
            f"(7400. {spec.title})",
            fmt["subtitle"],
        )
        row += 1

        # R3: 빈 행
        ws.set_row(row, 6)
        row += 1

        # R4: 회사명·작성자 정보
        ws.set_row(row, ROW_HEIGHT_META)
        ws.write(row, 0, "회사명", fmt["meta_label"])
        ws.merge_range(row, 1, row, 3, spec.company, fmt["meta_value"])
        ws.write(row, 4, "작성자", fmt["meta_label"])
        ws.write(row, 5, spec.preparer, fmt["meta_value"])
        ws.write(row, 6, "작성일", fmt["meta_label"])
        ws.write(row, 7, spec.prepared_date, fmt["meta_value"])
        row += 1

        # R5: 결산일·검토자 정보
        ws.set_row(row, ROW_HEIGHT_META)
        ws.write(row, 0, "결산일", fmt["meta_label"])
        ws.merge_range(row, 1, row, 3, spec.period_end, fmt["meta_value"])
        ws.write(row, 4, "검토자", fmt["meta_label"])
        ws.write(row, 5, spec.reviewer, fmt["meta_value"])
        ws.write(row, 6, "검토일", fmt["meta_label"])
        ws.write(row, 7, spec.reviewed_date, fmt["meta_value"])
        row += 1

        # 빈 행
        ws.set_row(row, 6)
        row += 1

        # 경영진 주장 섹션
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "경영진 주장", fmt["section_header"])
        row += 1

        assertions = [
            ("A", "정확성(Accuracy)"),
            ("C", "완전성(Completeness)"),
            ("CO", "기간귀속(Cutoff)"),
            ("E", "실재성(Existence)"),
            ("O", "발생사실(Occurrence)"),
            ("V", "평가(Valuation)"),
            ("RO", "권리와 의무(Rights & Obligations)"),
            ("CL", "분류(Classification)"),
            ("U", "이해가능성(Understandability)"),
        ]
        for code, desc in assertions:
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.write(row, 0, code, fmt["meta_label"])
            ws.merge_range(row, 1, row, 7, f": {desc}", fmt["section_body"])
            row += 1

        # 빈 행
        ws.set_row(row, 6)
        row += 1

        # §1: 작성요령 섹션
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "작성요령", fmt["section_header"])
        row += 1

        writing_guide_lines = [
            (
                f"본 조서는 {spec.company}의 정보시스템조직을 통해 처리되는 회계자료의 "
                "입출력 통제를 검증하기 위해 작성한다."
            ),
            (
                "GL 분개장 전체를 대상으로 무결성(A01·A02·A03)과 부정위험 지표(B01~B09) "
                "11종의 자동화 테스트를 수행하고, 그 결과를 본 조서철의 각 별지(A01, A02, … B09-6)에 첨부한다."
            ),
            (
                "적출 결과 중 유의한 예외사항이 발견된 경우에는 회사로부터 소명자료를 "
                "입수하여 별도 평가한다."
            ),
        ]
        for line in writing_guide_lines:
            h = self._calc_row_height(line, col_width_chars=70, base_height=ROW_HEIGHT_BODY)
            ws.set_row(row, h)
            ws.merge_range(row, 0, row, 7, line, fmt["section_body"])
            row += 1

        # 빈 행
        ws.set_row(row, 6)
        row += 1

        # 절차 요약 섹션
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "주요 감사절차 개요", fmt["section_header"])
        row += 1

        procedures = [
            "1. 일반거래기록의 장표처리 완전성 검증",
            "2. 총계정원장과 각종 재무제표의 결론에 대한 정확성 검증",
            "3. 결산감사 시의 계속성, 정확성 검증",
            "4. 입력기초자료의 거래인식에 대한 검토",
            "5. 프로그램 변경 통제 및 접근통제에 대한 검토",
            "6. 재무보고 프로세스 및 분개와 기타 조정사항에 대한 검토",
        ]
        for proc in procedures:
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.merge_range(row, 0, row, 7, proc, fmt["section_body"])
            row += 1

        # 빈 행
        ws.set_row(row, 6)
        row += 1

        # 결론 섹션
        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "결론", fmt["section_header"])
        row += 1

        conclusions = [
            "(1) 입력자료는 정확하게 분개되고 집계되어 각종 명세서에 반영된다.",
            "(2) 입력자료와 출력자료는 연결되고 있으므로 출력자료의 신뢰성이 확보된다.",
            "(3) 입력과 출력자료를 검증한 결과 데이터의 증거능력이 확보되었다.",
        ]
        for conc in conclusions:
            ws.set_row(row, ROW_HEIGHT_BODY)
            ws.merge_range(row, 0, row, 7, conc, fmt["section_body"])
            row += 1

        # §4: 7400 인쇄 설정 — 세로 A4, 한 페이지 너비
        self._apply_print_setup(
            ws, spec,
            sheet_display_name="7400. 입출력통제 조서",
            landscape=False,
            fit_width=1,
            fit_height=0,
        )

    # ── 7401 시나리오 목록 시트 ───────────────────────────────────────────

    def _write_7401_sheet(
        self,
        wb: xlsxwriter.Workbook,
        fmt: dict,
        spec: WorkpaperSpec,
        results: dict[str, RuleResult],
    ) -> None:
        """7401 시나리오 목록 및 검토결과 시트를 작성한다.

        §2: 검토결과 분기 (정상/적출 N건/면제)
        §3: 8열 구성 — 적출 건수 컬럼 분리
        §4: 가로 A4 인쇄 설정
        """
        ws = wb.add_worksheet("7401")
        # §3: 8열로 변경 — 적출 건수 컬럼 추가
        self._apply_col_widths(ws, [3, 14, 22, 20, 8, 12, 10, 20])

        row = 0

        # 제목
        ws.set_row(row, ROW_HEIGHT_TITLE)
        ws.merge_range(row, 0, row, 7, "JET 시나리오 목록 및 검토 결과", fmt["title"])
        row += 1

        # 메타
        ws.set_row(row, ROW_HEIGHT_META)
        ws.write(row, 0, "회사명", fmt["meta_label"])
        ws.write(row, 1, spec.company, fmt["meta_value"])
        ws.write(row, 2, "결산일", fmt["meta_label"])
        ws.write(row, 3, spec.period_end, fmt["meta_value"])
        ws.write(row, 4, "작성자", fmt["meta_label"])
        ws.write(row, 5, spec.preparer, fmt["meta_value"])
        ws.merge_range(row, 6, row, 7, spec.prepared_date, fmt["meta_value"])
        row += 1

        ws.set_row(row, 6)
        row += 1

        # §3: 테이블 헤더 — 8열
        headers = [
            "Test No", "Test Name", "Test Objectives",
            "조서번호", "수행여부", "검토결과", "적출 건수", "비고",
        ]
        ws.set_row(row, ROW_HEIGHT_HEADER)
        for col_idx, hdr in enumerate(headers):
            ws.write(row, col_idx, hdr, fmt["table_header"])
        row += 1

        # 시나리오 행
        for scenario in spec.scenarios:
            ws.set_row(row, ROW_HEIGHT_BODY + 4)
            rule_result = results.get(scenario.code)

            if scenario.enabled:
                ws.write(row, 0, scenario.code, fmt["table_cell"])
                ws.write(row, 1, scenario.name, fmt["table_cell"])
                ws.write(row, 2, scenario.objective, fmt["table_cell"])
                ws.write(row, 3, scenario.code, fmt["table_cell"])
                ws.write(row, 4, "Y", fmt["pass_badge"])

                # §2: 검토결과 분기 — _get_result_badge는 포맷 키(str) 반환
                result_label, badge_key, finding_count_val, review_note = (
                    self._get_result_badge(scenario.code, rule_result)
                )
                ws.write(row, 5, result_label, fmt[badge_key])
                # 적출 건수 — 숫자형 (§3)
                if finding_count_val is not None:
                    ws.write(row, 6, finding_count_val, fmt["table_cell_num"])
                else:
                    ws.write(row, 6, "-", fmt["table_cell"])
                ws.write(row, 7, review_note, fmt["table_cell"])
            else:
                # 비활성 행 (B06 면제 등)
                is_waived = scenario.params.get("waived", False) if scenario.params else False
                badge_text = "면제" if is_waived else "N/A"
                note = (
                    scenario.params.get("waive_reason", "데이터 미입수")
                    if is_waived else "이번 실행에서 제외"
                )
                ws.write(row, 0, scenario.code, fmt["inactive_row"])
                ws.write(row, 1, scenario.name, fmt["inactive_row"])
                ws.write(row, 2, scenario.objective, fmt["inactive_row"])
                ws.write(row, 3, scenario.code, fmt["inactive_row"])
                ws.write(row, 4, badge_text, fmt["warn_badge"] if is_waived else fmt["inactive_badge"])
                ws.write(row, 5, "면제" if is_waived else "-", fmt["warn_badge"] if is_waived else fmt["inactive_badge"])
                ws.write(row, 6, "-", fmt["inactive_badge"])
                ws.write(row, 7, note[:100], fmt["inactive_row"])

            row += 1

        # Excel 한도 초과 안내 (100만 행 근접 시)
        _EXCEL_LIMIT = 1_048_575
        total_entries = max(
            (r.total_entries_evaluated for r in results.values() if r),
            default=0,
        )
        if total_entries >= int(_EXCEL_LIMIT * 0.9):
            ws.set_row(row + 1, 20)
            ws.merge_range(
                row + 1, 0, row + 1, 7,
                f"[Excel 한도 안내] GL 데이터 {total_entries:,}행 — Excel 한도({_EXCEL_LIMIT:,}행)에 "
                "근접합니다. 적출 시트의 마스터 데이터는 50,000행까지만 표시됩니다. "
                "전체 데이터 분석이 필요한 경우 CSV/Parquet 형식의 분할 파일로 업로드하세요.",
                fmt.get("warn_badge", fmt["table_cell"]),
            )

        # §4: 7401 인쇄 설정 — 가로 A4
        self._apply_print_setup(
            ws, spec,
            sheet_display_name="7401. 시나리오 목록",
            landscape=True,
            fit_width=1,
            fit_height=0,
        )

    def _get_result_badge(
        self,
        code: str,
        result: RuleResult | None,
    ) -> tuple[str, Any, int | None, str]:
        """§2: 검토결과 분기 — (라벨, 배지 포맷키, 적출 건수, 비고) 반환.

        Args:
            code: 시나리오 코드
            result: 실행 결과 (None이면 미실행)

        Returns:
            (result_label, fmt_key, finding_count_or_None, note_text)
            fmt_key는 문자열이므로 호출측에서 fmt[fmt_key] 로 참조한다.
        """
        # Q01은 메타 시나리오 — 룰 결과 없음, 항상 "생성됨"으로 표시
        if code == "Q01":
            return "생성됨", "pass_badge", None, "이상전표 통합 질의서 생성 완료"

        if result is None:
            return "미실행", "inactive_badge", None, "실행 결과 없음"

        # 면제(Waived) / skipped 처리
        if result.params.get("waived") or result.params.get("skipped"):
            return "면제", "warn_badge", None, result.params.get("waive_reason", "데이터 미입수")

        fc = result.finding_count

        if fc == 0:
            note = self._get_review_result(code, result)
            return "정상", "pass_badge", 0, note

        # 적출 건수 기준 배지 분기 (100건 기준)
        badge = "warn_badge" if fc < 100 else "fail_badge"
        note = self._get_review_result(code, result)
        return f"적출 {fc:,}건", badge, fc, note

    def _get_review_result(
        self,
        code: str,
        result: RuleResult | None,
    ) -> str:
        """룰 코드와 결과에서 검토결과 요약 문구를 생성한다."""
        if result is None:
            return "실행 결과 없음"

        if code == "A01":
            stats: IntegrityStats = result.extra.get("integrity_stats")
            if stats:
                if stats.has_issues:
                    return (
                        f"형식오류 {stats.format_error_count}건, "
                        f"필수 결측 {stats.missing_required_count}건 발견"
                    )
                return f"이상 없음 (총 {stats.total_lines:,}라인 검증)"
        elif code == "A02":
            dr_stats: DrCrStats = result.extra.get("dr_cr_stats")
            if dr_stats:
                if dr_stats.imbalanced_count == 0:
                    return (
                        f"모든 전표 차대변 균형 확인 "
                        f"(전표 {dr_stats.total_entries:,}건)"
                    )
                return (
                    f"불일치 전표 {dr_stats.imbalanced_count}건 적출 "
                    f"(전체 {dr_stats.total_entries:,}건)"
                )
        elif code == "A03":
            mc = result.extra.get("mismatch_count", 0)
            ac = result.extra.get("accounts_checked", 0)
            if mc == 0:
                return f"TB 일치 ({ac:,}계정 검증)"
            return f"불일치 {mc}계정 적출 (총 {ac:,}계정)"
        elif code == "B03":
            new_accounts = result.extra.get("new_accounts", [])
            used_count = result.extra.get("new_accounts_used_count", 0)
            uniq = result.extra.get("unique_entry_count", 0)
            return (
                f"신규계정 {len(new_accounts):,}종 (사용 {used_count:,}종) "
                f"/ 분개 {result.finding_count:,}건 / 전표 {uniq:,}개"
            )
        elif code == "B04":
            seldom_count = result.extra.get("seldom_account_count", 0)
            uniq = result.extra.get("unique_entry_count", 0)
            return (
                f"희소계정 {seldom_count:,}종 / 분개 {result.finding_count:,}건 "
                f"/ 전표 {uniq:,}개"
            )
        elif code == "B05":
            nr = result.extra.get("not_registered_count", 0)
            pr = result.extra.get("post_retirement_count", 0)
            sc = result.extra.get("system_account_count", 0)
            aff = result.extra.get("affiliate_count", 0)
            return (
                f"미등록 {nr:,} / 퇴직후 {pr:,} / 시스템 {sc:,} / 그룹사 {aff:,}건"
            )
        elif code == "B07":
            late = result.extra.get("late_count", 0)
            back = result.extra.get("backdated_only_count", 0)
            return f"지연 {late:,}건 / 역행 {back:,}건"
        elif code == "B08":
            return f"분석표 {result.finding_count:,}행 (전표유형×계정×차대 집계)"
        elif code == "B06":
            if result and result.extra.get("has_approver_data"):
                fc = result.finding_count
                return f"직무분리 위반 {fc:,}건" if fc > 0 else "직무분리 이상 없음"
            return "데이터 미입수 (Waived)"
        elif code == "B09":
            sub_total = sum(len(sr.findings) for sr in result.extra.get("sub_results", []))
            return f"희소조합 {result.finding_count:,}건 / 서브 {sub_total:,}건"
        elif code == "B10":
            absent = result.extra.get("absent_count", 0)
            short = result.extra.get("short_count", 0)
            vague = result.extra.get("vague_count", 0)
            return f"부재 {absent:,} / 짧음 {short:,} / 모호 {vague:,}건"
        elif code == "B11":
            prox = result.extra.get("proximity_count", 0)
            post = result.extra.get("post_input_count", 0)
            return f"결산일 인접 {prox:,}건 / 결산 후 입력 {post:,}건"
        elif code == "B12":
            return f"결산조정 분개 {result.finding_count:,}건 적출"

        if result.params.get("waived"):
            return "데이터 미입수 (Waived)"
        if result.params.get("skipped"):
            return "마스터 미제공으로 생략"
        if result.finding_count == 0:
            return "예외사항 없음"
        return f"{result.finding_count:,}건 적출"

    # ── A01 DataIntegrity 시트 ─────────────────────────────────────────────

    def _write_a01_sheet(
        self,
        wb: xlsxwriter.Workbook,
        fmt: dict,
        spec: WorkpaperSpec,
        result: RuleResult,
    ) -> None:
        """A01 DataIntegrity 결과 시트를 작성한다.

        §5: 용어 정비 (전표라인→분개행, 결측→누락)
        §7: KPI 카드 값에 단위 표기
        §8: 유효율 숫자형 저장 (0.0% 포맷)
        §4: 가로 A4 인쇄 설정
        """
        ws = wb.add_worksheet("A01")
        self._apply_col_widths(ws, [16, 12, 10, 10, 10, 10, 8, 12])

        stats: IntegrityStats | None = result.extra.get("integrity_stats")

        # ── 공통 헤더 ─────────────────────────────────────────────────────
        test_method = (
            f"SAP {_TERM_GL_LINE} 데이터의 필드별 무결성을 검증한다. "
            f"전표번호·전기일·계정코드·금액·사용자ID 등 필수 필드의 {_TERM_MISSING}·형식 오류를 점검하며, "
            "결과는 통계 요약으로 표시한다(개별 적출 없음)."
        )
        if stats:
            if stats.has_issues:
                test_result = (
                    f"총 {stats.total_lines:,}{_TERM_LINE} 검증 완료. "
                    f"형식오류 {stats.format_error_count}건, "
                    f"필수 {_TERM_MISSING} {stats.missing_required_count}건 발견. "
                    "상세는 아래 컬럼별 통계 참조."
                )
            else:
                test_result = (
                    f"총 {stats.total_lines:,}{_TERM_LINE} 검증 완료. "
                    "검증 불가능한 데이터 오류 발견되지 아니함. 예외사항 없음."
                )
        else:
            test_result = "실행 결과 없음"

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "A01. Data Integrity Test",
            f"{_TERM_GL_LINE} 데이터 필드 무결성 검증",
            test_method,
            test_result,
        )

        row = 7  # R8~

        # ── §7: KPI 카드 3개 — 값 + 단위 2행 구성 ────────────────────────
        if stats:
            kpi_items = [
                (f"{stats.total_lines:,}", f"행 ({_TERM_LINE_COUNT})", "accent_kpi", "accent_kpi_label"),
                (str(stats.missing_required_count), f"항목 ({_TERM_MISSING} 컬럼)", "accent_kpi", "accent_kpi_label"),
                (str(stats.format_error_count), "행 (형식오류)", "accent_kpi", "accent_kpi_label"),
            ]
            # 라벨 행은 별도로 위에
            label_texts = [f"총 {_TERM_LINE_COUNT}", f"필수 {_TERM_MISSING} 수", "형식오류 행 수"]
            ws.set_row(row, ROW_HEIGHT_KPI)
            ws.set_row(row + 1, ROW_HEIGHT_META - 4)
            ws.set_row(row + 2, ROW_HEIGHT_META)
            for i, ((val, unit, vfmt_key, _), lbl) in enumerate(zip(kpi_items, label_texts)):
                col_start = i * 2
                ws.merge_range(row, col_start, row, col_start + 1, val, fmt[vfmt_key])
                ws.merge_range(row + 1, col_start, row + 1, col_start + 1, unit, fmt["accent_kpi_label"])
                ws.merge_range(row + 2, col_start, row + 2, col_start + 1, lbl, fmt["accent_kpi_label"])
            row += 4

        # ── 컬럼별 검증 결과 테이블 ───────────────────────────────────────
        ws.set_row(row, 6)
        row += 1

        ws.set_row(row, ROW_HEIGHT_HEADER)
        ws.merge_range(row, 0, row, 7, "컬럼별 무결성 검증 결과", fmt["section_header"])
        row += 1

        # §5: "결측 건수" → "누락 건수"
        col_headers = [
            "컬럼명", "전체 행 수", "유효 행 수",
            f"{_TERM_MISSING} 건수", "형식오류 건수", "유효율", "상태", "비고",
        ]
        ws.set_row(row, ROW_HEIGHT_HEADER)
        for ci, hdr in enumerate(col_headers):
            ws.write(row, ci, hdr, fmt["table_header"])
        row += 1

        if stats:
            for col_stat in stats.column_stats:
                ws.set_row(row, ROW_HEIGHT_BODY)
                status_fmt = fmt["pass_badge"] if col_stat.status == "OK" else fmt["fail_badge"]
                ws.write(row, 0, col_stat.column_name, fmt["table_cell"])
                ws.write(row, 1, col_stat.total_count, fmt["table_cell_num"])
                ws.write(row, 2, col_stat.non_null_count, fmt["table_cell_num"])
                ws.write(row, 3, col_stat.null_count, fmt["table_cell_num"])
                ws.write(row, 4, col_stat.invalid_count, fmt["table_cell_num"])
                # §8: 숫자형으로 저장 (0.0% 포맷)
                ws.write(row, 5, col_stat.pass_rate, fmt["table_cell_pct"])
                ws.write(row, 6, col_stat.status, status_fmt)
                ws.write(row, 7, col_stat.notes or "정상", fmt["table_cell"])
                row += 1

        # 실행 메타
        row += 1
        ws.set_row(row, ROW_HEIGHT_BODY)
        exec_at = result.executed_at.strftime("%Y-%m-%d %H:%M:%S")
        ws.merge_range(
            row, 0, row, 7,
            f"실행일시: {exec_at}  /  룰버전: {result.rule_version}  /  "
            f"평가 {_TERM_LINE}: {result.total_entries_evaluated:,}건",
            fmt["section_body"],
        )

        # §4: A01 인쇄 설정 — 가로 A4, 헤더 행(R4) 반복
        self._apply_print_setup(
            ws, spec,
            sheet_display_name="A01. Data Integrity",
            landscape=True,
            fit_width=1,
            fit_height=0,
            repeat_header_row=row - len(stats.column_stats) - 1 if stats else None,
        )

    # ── A02 DR/CR Balance 시트 ────────────────────────────────────────────

    def _write_a02_sheet(
        self,
        wb: xlsxwriter.Workbook,
        fmt: dict,
        spec: WorkpaperSpec,
        result: RuleResult,
    ) -> None:
        """A02 DR/CR Balance 결과 시트를 작성한다.

        §5: 허용오차 표기 ±0.01원
        §6: 정상 case에도 검증 흔적용 sample 표 (상위 10건)
        §9: 불일치 0건 → success_kpi(초록), >0건 → danger_kpi(빨강)
        §4: 가로 A4 인쇄 설정
        """
        ws = wb.add_worksheet("A02")
        self._apply_col_widths(ws, [16, 12, 12, 12, 12, 12, 8, 10])

        dr_stats: DrCrStats | None = result.extra.get("dr_cr_stats")

        # ── 공통 헤더 ─────────────────────────────────────────────────────
        test_method = (
            "전표번호(entry_no) 단위로 차변 합계와 대변 합계가 일치하는지 검증한다. "
            f"SAP 회계 시스템에서는 분개 균형이 시스템 레벨에서 강제되므로 "
            f"허용오차 {_TERM_TOLERANCE}를 초과하는 불일치 전표가 발견되면 "
            "데이터 추출 또는 포맷 변환 오류를 의심해야 한다."
        )
        if dr_stats:
            if dr_stats.imbalanced_count == 0:
                test_result = (
                    f"전표 {dr_stats.total_entries:,}건 전체 차대변 균형 확인. "
                    "예외사항 없음."
                )
            else:
                test_result = (
                    f"전표 {dr_stats.total_entries:,}건 중 "
                    f"불일치 {dr_stats.imbalanced_count}건 적출. "
                    "아래 상세 목록 참조."
                )
        else:
            test_result = "실행 결과 없음"

        self._write_rule_sheet_header(
            ws, fmt, spec,
            "A02. Transaction DR/CR Test",
            "전표번호 단위 차대변 균형 검증",
            test_method,
            test_result,
        )

        row = 7

        # ── §9: KPI 카드 3개 ──────────────────────────────────────────────
        if dr_stats:
            imbalanced = dr_stats.imbalanced_count
            # KPI 3번째: 불일치 0건=success(초록), >0건=danger(빨강)
            third_val_fmt = "success_kpi" if imbalanced == 0 else "danger_kpi"
            third_lbl_fmt = "success_kpi_label" if imbalanced == 0 else "danger_kpi_label"

            kpi_items = [
                (f"{dr_stats.total_entries:,}", "전표", "accent_kpi", "accent_kpi_label", "총 전표번호 수"),
                (f"{dr_stats.balanced_entries:,}", "전표", "accent_kpi", "accent_kpi_label", "정상 전표 수"),
                (f"{imbalanced:,}", "전표", third_val_fmt, third_lbl_fmt, "불일치 전표 수"),
            ]
            ws.set_row(row, ROW_HEIGHT_KPI)
            ws.set_row(row + 1, ROW_HEIGHT_META - 4)
            ws.set_row(row + 2, ROW_HEIGHT_META)
            for i, (val, unit, vfmt_key, lfmt_key, lbl) in enumerate(kpi_items):
                col_start = i * 2
                ws.merge_range(row, col_start, row, col_start + 1, val, fmt[vfmt_key])
                ws.merge_range(row + 1, col_start, row + 1, col_start + 1, unit, fmt[lfmt_key])
                ws.merge_range(row + 2, col_start, row + 2, col_start + 1, lbl, fmt[lfmt_key])
            row += 4

        row += 1  # 빈 행

        if dr_stats and dr_stats.imbalanced_count == 0:
            # 정상 — 배지 + 메시지
            ws.set_row(row, ROW_HEIGHT_HEADER + 4)
            ws.merge_range(
                row, 0, row, 7,
                "예외사항 없음 — 모든 전표의 차변합계 = 대변합계 확인됨",
                fmt["pass_badge"],
            )
            row += 2

            # §6: 검증 흔적용 sample 표 (전표번호 ASC 상위 10건)
            ws.set_row(row, ROW_HEIGHT_HEADER)
            ws.merge_range(
                row, 0, row, 7,
                "검증 흔적 — 상위 10건 차대변 균형 확인 (전표번호 오름차순)",
                fmt["section_header"],
            )
            row += 1

            sample_headers = ["전표번호", "전기일", "차변합계", "대변합계", "차이", "일치여부", "", ""]
            ws.set_row(row, ROW_HEIGHT_HEADER)
            for ci, hdr in enumerate(sample_headers):
                ws.write(row, ci, hdr, fmt["table_header"])
            row += 1

            # entry_no 기준 groupby, ASC 정렬 후 상위 10건
            raw_entries = result.extra.get("dr_cr_stats")
            sample_groups = self._extract_a02_sample(result)
            for entry_no, entry_date_str, debit_sum, credit_sum, diff in sample_groups:
                ws.set_row(row, ROW_HEIGHT_BODY)
                ws.write(row, 0, entry_no, fmt["table_cell"])
                ws.write(row, 1, entry_date_str, fmt["table_cell_date"])
                ws.write(row, 2, debit_sum, fmt["table_cell_num"])
                ws.write(row, 3, credit_sum, fmt["table_cell_num"])
                ws.write(row, 4, diff, fmt["table_cell_num"])
                ws.write(row, 5, "✓ 정상", fmt["pass_badge"])
                ws.write(row, 6, "", fmt["table_cell"])
                ws.write(row, 7, "", fmt["table_cell"])
                row += 1

        elif dr_stats and dr_stats.imbalanced_count > 0:
            # 불일치 적출 테이블
            ws.set_row(row, ROW_HEIGHT_HEADER)
            ws.merge_range(row, 0, row, 7, "차대변 불일치 전표 목록", fmt["section_header"])
            row += 1

            detail_headers = [
                "전표번호", "전기일", "차변 합계", "대변 합계", "차이금액", "분개행 수", "상태", "비고",
            ]
            ws.set_row(row, ROW_HEIGHT_HEADER)
            for ci, hdr in enumerate(detail_headers):
                ws.write(row, ci, hdr, fmt["table_header"])
            row += 1

            for imb in dr_stats.imbalanced_entries:
                ws.set_row(row, ROW_HEIGHT_BODY)
                ws.write(row, 0, imb.entry_no, fmt["table_cell"])
                ws.write(row, 1, imb.entry_date.strftime("%Y-%m-%d"), fmt["table_cell_date"])
                ws.write(row, 2, float(imb.debit_total), fmt["table_cell_num"])
                ws.write(row, 3, float(imb.credit_total), fmt["table_cell_num"])

                # 차이금액 — 절댓값 > 0.01 이면 빨강
                diff_val = float(imb.difference)
                diff_fmt = fmt["fail_badge"] if abs(diff_val) > 0.01 else fmt["pass_badge"]
                ws.write(row, 4, diff_val, diff_fmt)
                ws.write(row, 5, imb.line_count, fmt["table_cell_num"])
                ws.write(row, 6, "적출", fmt["fail_badge"])
                ws.write(row, 7, "", fmt["table_cell"])
                row += 1

        # 실행 메타 — §5: 허용오차 표기 ±0.01원
        row += 1
        ws.set_row(row, ROW_HEIGHT_BODY)
        exec_at = result.executed_at.strftime("%Y-%m-%d %H:%M:%S")
        tol_raw = result.params.get("tolerance", "0.01")
        ws.merge_range(
            row, 0, row, 7,
            f"실행일시: {exec_at}  /  룰버전: {result.rule_version}  /  "
            f"평가 {_TERM_LINE}: {result.total_entries_evaluated:,}건  /  "
            f"허용오차: ±{tol_raw}원",
            fmt["section_body"],
        )

        # §4: A02 인쇄 설정 — 가로 A4
        self._apply_print_setup(
            ws, spec,
            sheet_display_name="A02. DR/CR Balance",
            landscape=True,
            fit_width=1,
            fit_height=0,
        )

    def _extract_a02_sample(
        self,
        result: RuleResult,
    ) -> list[tuple[str, str, float, float, float]]:
        """§6: A02 정상 case 검증 흔적 — balanced_sample에서 상위 10건 반환.

        A02 룰이 extra['balanced_sample']에 (entry_no, date, debit, credit, diff) 저장.

        Returns:
            (entry_no, entry_date_str, debit_sum, credit_sum, diff) 목록
        """
        sample_raw: list | None = result.extra.get("balanced_sample")
        if not sample_raw:
            return []

        rows = []
        for entry_no, entry_date, debit_total, credit_total, diff in sample_raw:
            date_str = entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date)
            rows.append((
                entry_no,
                date_str,
                float(debit_total),
                float(credit_total),
                float(diff),
            ))
        return rows
