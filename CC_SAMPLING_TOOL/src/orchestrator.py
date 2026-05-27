"""
오케스트레이터 — 회사자료 + 파라미터 → 조서 출력

high-level flow:
  1. 거래처별 원장 로드 → 거래처 합계
  2. 완전성 검토 (vs 재무제표)
  3. 발송제외 적용
  4. PM 산출 (총자산 × ratio × adj)
  5. Key item 기준금액 산출 → Key item 추출
  6. 표본규모 결정
  7. MUS 추출
  8. 특관자 강제 포함
  9. 조서 출력
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd

from src.domain.mus import run_mus
from src.domain.population import (
    aggregate_by_party,
    check_completeness,
    classify_parties,
    load_ledger_rows,
)
from src.domain.sample_size import SampleSizeInput, compute_sample_size
from src.infrastructure.reporter import build_report
from src.infrastructure.report.generic_reporter import (
    ReportContext,
    PartyContactInfo,
    ExclusionRow,
    ConfirmationReplyInfo,
    AlternativeProcedureEntry,
    build_generic_report,
)
# 하위 호환: template_reporter 는 7620 회귀 테스트용으로 유지 (DEPRECATED)
from src.infrastructure.template_reporter import (
    ReportContext as _LegacyReportContext,
    build_template_report,
)


@dataclass
class SamplingParams:
    company_name: str
    period_end: date
    kind: Literal["receivable", "payable"]
    performance_materiality: float
    risk_level: str = "유의적위험"
    control_reliance: str = "Y"
    key_item_ratio_override: float | None = None
    confidence_factor_override: float | None = None
    fs_amounts_by_group: dict[str, float] = field(default_factory=dict)
    completeness_notes: dict[str, str] = field(default_factory=dict)
    excluded_parties: dict[str, str] = field(default_factory=dict)
    related_parties: set[str] = field(default_factory=set)
    force_include_related: bool = True
    random_seed: int | None = None
    random_start: float | None = None
    preparer: str = ""
    reviewer: str = ""


@dataclass
class SamplingOutput:
    completeness: object
    size_result: object
    decisions: list
    mus_result: object
    population_amount: float


def run_sampling(df_ledger: pd.DataFrame, params: SamplingParams) -> SamplingOutput:
    # 1. 거래처별 집계
    # 컬럼 자동 감지 — 7620 이외 클라이언트 대응 (시트 헤더 키워드 기반)
    from src.infrastructure.schemas.ledger_schema import detect_ledger_columns
    col_map = detect_ledger_columns(df_ledger)
    rows = load_ledger_rows(df_ledger, kind=params.kind, col_map=col_map)
    parties_all = aggregate_by_party(rows, kind=params.kind, sign_normalize=True)

    # 발송제외 적용 후 모집단
    parties_active = {
        n: pb for n, pb in parties_all.items()
        if n not in params.excluded_parties and pb.total > 0
    }

    # 2. 완전성 검토
    completeness = check_completeness(
        parties=parties_all,
        fs_amounts=params.fs_amounts_by_group,
        notes=params.completeness_notes,
    )

    population_amount = sum(pb.total for pb in parties_active.values())

    # 3. 초기 분류 (key_item_threshold 미정 상태) → 임시 threshold = PM × ratio
    from src.domain.sample_size import resolve_key_item_ratio
    ratio = resolve_key_item_ratio(
        params.risk_level, params.control_reliance, params.key_item_ratio_override
    )
    threshold = params.performance_materiality * ratio

    decisions = classify_parties(
        parties=parties_active,
        key_item_threshold=threshold,
        related_party_names=params.related_parties,
        excluded_parties=params.excluded_parties,
    )
    # 발송제외도 decision에 포함 (조서용)
    for name, reason in params.excluded_parties.items():
        if name in parties_all and name not in {d.name for d in decisions}:
            from src.domain.population import PartyDecision
            decisions.append(PartyDecision(
                name=name, balance=parties_all[name].total,
                is_excluded=True, is_related_party=False,
                is_key_item=False, is_representative=False, final_sampled=False,
                exclusion_reason=reason,
            ))

    key_item_amount = sum(d.balance for d in decisions if d.is_key_item)

    # 4. 표본규모 결정
    size_result = compute_sample_size(SampleSizeInput(
        population_amount=population_amount,
        performance_materiality=params.performance_materiality,
        risk_level=params.risk_level,           # type: ignore
        control_reliance=params.control_reliance,  # type: ignore
        key_item_ratio_override=params.key_item_ratio_override,
        confidence_factor_override=params.confidence_factor_override,
        key_item_amount=key_item_amount,
    ))

    # 5. MUS — Key item·제외 거래처 빼고 추출
    pool = [
        (d.name, d.balance) for d in decisions
        if not d.is_excluded and not d.is_key_item and d.balance > 0
    ]
    pool.sort(key=lambda x: x[0])   # 명세서 순서 (이름 기준)

    mus_result = run_mus(
        pool=pool,
        sample_size=size_result.final_sample_size,
        sample_interval=size_result.sample_interval,
        random_start=params.random_start,
        seed=params.random_seed,
    )

    sampled_set = set(mus_result.sampled_names)
    for d in decisions:
        if d.name in sampled_set:
            d.is_representative = True

    # 6. 특관자 강제 포함
    if params.force_include_related:
        for d in decisions:
            if d.is_related_party and not d.is_excluded:
                d.final_sampled = True

    # 7. 최종 샘플링 = Key item OR Representative OR (특관자 강제)
    for d in decisions:
        if d.is_key_item or d.is_representative:
            d.final_sampled = True

    return SamplingOutput(
        completeness=completeness,
        size_result=size_result,
        decisions=decisions,
        mus_result=mus_result,
        population_amount=population_amount,
    )


def write_report(
    out: SamplingOutput,
    params: SamplingParams,
    out_path: str | Path,
    template_id: str | None = None,
    contacts: list[PartyContactInfo] | None = None,
    exclusion_rows: list[ExclusionRow] | None = None,
    pdf_replies: list[ConfirmationReplyInfo] | None = None,
    alt_procedures: list[AlternativeProcedureEntry] | None = None,
) -> None:
    """조서 출력 — 빈 워크북에서 7개 시트 직접 작성.

    template_id 는 향후 시각 테마 선택용으로 유지하나 현재는 무시.
    기존 build_template_report 는 7620 회귀 테스트에서 직접 호출 가능 (DEPRECATED).
    """
    prefix = "C100" if params.kind == "receivable" else "AA100"
    ctx = ReportContext(
        company_name=params.company_name,
        period_end=params.period_end,
        kind=params.kind,
        preparer=params.preparer,
        reviewer=params.reviewer,
        workpaper_no_prefix=prefix,
    )
    build_generic_report(
        out_path=out_path,
        ctx=ctx,
        completeness=out.completeness,
        size_result=out.size_result,
        decisions=out.decisions,
        mus_result=out.mus_result,
        performance_materiality=params.performance_materiality,
        population_amount=out.population_amount,
        contacts=contacts,
        exclusion_rows=exclusion_rows,
        pdf_replies=pdf_replies,
        alt_procedures=alt_procedures,
    )
