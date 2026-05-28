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

        if not accounts:
            return DesignResult(
                kind=kind, n_total=0, n_forced=0, n_excluded=0,
                n_representative=0, used_seed=params.seed,
                strata=[], population_bv=0.0,
            )

        forced, excluded, remaining = classify_population(
            accounts, key_threshold=params.key_threshold,
        )

        population_bv = sum(abs(a.balance_krw) for a in accounts)
        expected_ms = project.tolerable * params.expected_ms_pct
        n_total = sample_size_mus(
            book_value=population_bv,
            confidence=params.confidence,
            tolerable=project.tolerable,
            expected_ms=expected_ms,
        )

        n_rep_target = max(0, n_total - len(forced))

        if remaining and not should_use_single_stratum(remaining):
            strata = suggest_strata(remaining, n_strata=params.n_strata)
        else:
            max_b = max((abs(a.balance_krw) for a in remaining), default=0.0)
            strata = [Strata(low=0.0, high=max_b, n_required=0)]
        strata = allocate_strata(strata, remaining, total_n=n_rep_target)

        rep_sample = stratified_pps(remaining, strata, seed=params.seed)
        rep_with_reason: list[tuple[Account, SelectionReason]] = [
            (a, SelectionReason.REP) for a in rep_sample
        ]

        all_selections = list(forced) + rep_with_reason
        self.sample.persist(project_id, kind, all_selections)

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
