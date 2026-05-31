"""DesignSamplingUC — Population → SampleDesign orchestration.

설계서 §6.1 [3]. AR/AP 각 호출 분리 (병렬 실행은 호출자 책임).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from src.domain.entities import Account, Kind, SelectionReason, Strata
from src.domain.sampling.sample_size import sample_size_mus
from src.domain.sampling.classification import classify_population
from src.domain.sampling.stratified import (
    should_use_single_stratum, suggest_strata, stratified_pps,
)
from src.domain.sampling.allocation import allocate_strata
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)


@dataclass
class DesignParams:
    confidence: float
    expected_ms_pct: float
    key_threshold: float
    n_strata: int = 4
    seed: Optional[int] = None
    n_override: Optional[int] = None  # 수동 표본수. None이면 자동산정
    # AR 커버리지 모드: 잔액 큰 순 누적합 ≥ coverage_pct * total 도달까지 강제포함.
    # 0이면 비활성. 0.70 = 70% 커버. 표준 절차 3-2 (AR 70~80% 커버리지).
    coverage_pct: float = 0.0
    # 개별중요항목(|잔액| ≥ key_threshold) 강제포함 = 전수검사(ISA 530 top-stratum).
    # 커버리지 모드는 FORCED_COVERAGE가 큰 항목을 이미 포함하므로 False로 호출해 중복 방지.
    force_key_items: bool = True


@dataclass
class DesignResult:
    kind: Kind
    n_total: int
    n_forced: int
    n_excluded: int
    n_representative: int
    used_seed: Optional[int]
    strata: list[Strata]
    population_bv: float


class DesignSamplingUC:
    def __init__(self, session):
        self.s = session
        self.proj = ProjectRepo(session)
        self.acc = AccountRepo(session)
        self.sample = SampleRepo(session)

    def design(
        self,
        project_id: int,
        kind: Kind,
        params: DesignParams,
    ) -> DesignResult:
        project = self.proj.get(project_id)
        accounts = self.acc.list_by_project_kind(project_id, kind)

        # AP 샘플링 기준 — ISA 505 완전성:
        #   (활동량 큰) AND (기말 잔액 작은) 거래처 우선.
        # score = max(0, |활동량| - |잔액|) = paid-off 추정액.
        # 활동량 큰데 잔액 거의 0 → score 큼 (채무 누락 의심).
        # 활동량 작은 거래처 → score 작음 (무관).
        # 잔액 ≥ 활동량 → score 0 (정상 채무 잔액 있음).
        # ledger에 활동량(debit) 분리 안 됨 → 잔액 fallback.
        weight_attr = "balance_krw"
        if kind == Kind.AP and accounts:
            has_activity = any(abs(getattr(a, "debit_amt", 0)) > 0
                                for a in accounts)
            if has_activity:
                for a in accounts:
                    activity = abs(getattr(a, "debit_amt", 0) or 0)
                    bal = abs(getattr(a, "balance_krw", 0) or 0)
                    a._ap_completeness_score = max(0.0, activity - bal)
                weight_attr = "_ap_completeness_score"

        if not accounts:
            return DesignResult(
                kind=kind, n_total=0, n_forced=0, n_excluded=0,
                n_representative=0, used_seed=params.seed,
                strata=[], population_bv=0.0,
            )

        # classification — 자기회사 self-deal 제외 + AP는 잔액0+활동량 남김
        forced, excluded, remaining = classify_population(
            accounts, key_threshold=params.key_threshold,
            self_name=project.client, kind=kind.value,
        )

        # 개별중요항목(|잔액| ≥ key_threshold) 강제포함 — 전수검사(ISA 530 top-stratum).
        # ① 개수지정·③ MUS 모드에서 거액 거래처가 확률추출로 누락되는 것을 방지.
        # ② 커버리지 모드는 force_key_items=False — 아래 FORCED_COVERAGE가 이미 포함.
        # count 모드는 표본수=max(필수, 지정수)라 중요항목이 지정수 내면 개수 불변,
        # 초과하면 늘어남(중요항목 수 자체가 지정수 초과 → 전수 원칙상 정상).
        import math as _math
        if (params.force_key_items and remaining
                and params.key_threshold
                and _math.isfinite(params.key_threshold)
                and params.key_threshold > 0):
            kt = params.key_threshold
            _kept: list[Account] = []
            for a in remaining:
                if abs(getattr(a, "balance_krw", 0.0)) >= kt:
                    forced.append((a, SelectionReason.FORCED_KEY))
                else:
                    _kept.append(a)
            remaining = _kept

        # AR 커버리지 모드: 잔액 큰 순 누적 ≥ target까지 추가 강제포함.
        # 커버리지 기준은 비RP(remaining=제3자) 모집단 — RP는 별도 강제포함이고
        # 특관자 조회는 외부조회 대비 증거력이 약해, RP 잔액을 커버리지에 산입하면
        # RP가 커버리지를 다 채워 제3자 거래처가 한 곳도 선정 안 되는 결함 발생.
        # cum=0에서 시작해 제3자 큰 거래처가 비RP 잔액의 coverage_pct를 직접 채우게 함.
        if (kind == Kind.AR and params.coverage_pct
                and params.coverage_pct > 0 and remaining):
            total_remaining = sum(abs(a.balance_krw) for a in remaining)
            target = total_remaining * params.coverage_pct
            rem_sorted = sorted(remaining, key=lambda a: -abs(a.balance_krw))
            cum = 0.0
            new_remaining: list[Account] = []
            for a in rem_sorted:
                if cum < target:
                    forced.append((a, SelectionReason.FORCED_COVERAGE))
                    cum += abs(a.balance_krw)
                else:
                    new_remaining.append(a)
            remaining = new_remaining

        # population_bv는 sample_size 계산용 — excluded(self-deal·비거래처·
        # bad debt·잔액 0) 제외한 forced + remaining만. 모집단 과대 → 표본수 과대 방지.
        forced_bv_sum = sum(abs(getattr(a, "balance_krw", 0.0)) for a, _ in forced)
        rem_bv_sum = sum(abs(getattr(a, "balance_krw", 0.0)) for a in remaining)
        population_bv = forced_bv_sum + rem_bv_sum
        expected_ms = project.tolerable * params.expected_ms_pct
        if params.coverage_pct and params.coverage_pct > 0:
            # AR 커버리지 모드: forced(RP + 커버리지 KEY)만 표본. PPS X.
            n_total = len(forced)
        elif params.n_override is not None:
            # 사용자 수동 입력 — 강제포함 보장 + 그 만큼 채우기
            n_total = max(len(forced), params.n_override)
        else:
            n_total = sample_size_mus(
                book_value=population_bv,
                confidence=params.confidence,
                tolerable=project.tolerable,
                expected_ms=expected_ms,
            )

        n_rep_target = max(0, n_total - len(forced))

        # AP completeness 모드: stratify 우회 → score 큰 순 top N 직접 채택
        # (활동량 큰 + 잔액 작은 거래처 보장).
        if kind == Kind.AP and weight_attr == "_ap_completeness_score":
            scored = sorted(
                [a for a in remaining
                  if getattr(a, "_ap_completeness_score", 0) > 0],
                key=lambda a: -a._ap_completeness_score,
            )
            rep_sample = scored[:n_rep_target]
            strata = [Strata(low=0.0, high=0.0, n_required=n_rep_target)]
        else:
            # 단일 strata + 전체 PPS — 최대 weight 거래처 systematic 첫 interval 보장.
            # (stratify는 top strata에 n_required=1 할당 시 최대 거래처 누락 가능)
            max_b = max((abs(getattr(a, weight_attr, 0.0)) for a in remaining),
                         default=0.0)
            strata = [Strata(low=0.0, high=max_b, n_required=n_rep_target)]
            from src.domain.sampling.mus import pps_select
            rep_sample = pps_select(remaining, n_rep_target,
                                      seed=params.seed,
                                      weight_attr=weight_attr)
        # fillers 보강 — count 모드(n_override 명시)만 적용.
        # materiality·coverage 모드는 통계 분포 왜곡 방지 위해 PPS 결과 그대로.
        if (params.n_override is not None
                and len(rep_sample) < n_rep_target):
            chosen_ids = {id(a) for a in rep_sample}
            fillers = sorted(
                (a for a in remaining if id(a) not in chosen_ids),
                key=lambda a: -abs(getattr(a, weight_attr, 0.0)),
            )
            need = n_rep_target - len(rep_sample)
            rep_sample = list(rep_sample) + fillers[:need]
        rep_with_reason: list[tuple[Account, SelectionReason]] = [
            (a, SelectionReason.REP) for a in rep_sample
        ]

        all_selections = list(forced) + rep_with_reason
        self.sample.persist(project_id, kind, all_selections)

        from src.infrastructure.db.repository import SampleDesignRepo
        SampleDesignRepo(self.s).upsert(
            project_id, kind,
            confidence=params.confidence,
            key_threshold=params.key_threshold,
            expected_ms_pct=params.expected_ms_pct,
            n_strata=params.n_strata,
            seed=params.seed,
            population_bv=population_bv,
            n_total=len(all_selections),
            strata_snapshot=[
                {"low": s.low, "high": s.high, "n_required": s.n_required}
                for s in strata
            ],
        )

        return DesignResult(
            kind=kind,
            n_total=len(all_selections),
            n_forced=len(forced),
            n_excluded=len(excluded),
            n_representative=len(rep_with_reason),
            used_seed=params.seed,
            strata=strata,
            population_bv=population_bv,
        )
