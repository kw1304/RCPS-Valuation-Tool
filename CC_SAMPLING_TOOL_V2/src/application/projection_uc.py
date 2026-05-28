"""ProjectionUC — Confirmation → ISA 530 PPS projection + persist.

설계서 §6.1 [7], §5.8. Phase 1 domain.projection.pps 활용.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from src.domain.entities import Kind, Verdict
from src.domain.projection.pps import project_misstatement
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo, ProjectionRepo,
)


@dataclass
class ProjectionView:
    kind: Kind
    projected_misstatement: float
    basic_precision: float
    incremental_allowance: float
    upper_limit: float
    tolerable: float
    verdict: str
    sample_size: int
    sampling_interval: float


class ProjectionUC:
    def __init__(self, session):
        self.s = session

    def compute(
        self,
        project_id: int,
        kind: Kind,
        confidence: float = 0.95,
    ) -> ProjectionView:
        proj = ProjectRepo(self.s).get(project_id)
        accounts = AccountRepo(self.s).list_by_project_kind(project_id, kind)
        sample = SampleRepo(self.s).list_by_project_kind(project_id, kind)
        confirmations = ConfirmationRepo(self.s).list_by_project_kind(
            project_id, kind)

        population_bv = sum(abs(a.balance_krw) for a in accounts)
        n = max(1, len(sample))
        sampling_interval = population_bv / n if n > 0 else 0.0

        ms_inputs: list[tuple[float, float]] = []
        for c in confirmations:
            if c.verdict == Verdict.DISCREPANCY and c.diff is not None:
                ms = abs(c.expected - (c.confirmed or 0))
                ms_inputs.append((ms, abs(c.expected)))

        result = project_misstatement(
            kind=kind,
            confidence=confidence,
            sampling_interval=sampling_interval,
            tolerable=proj.tolerable,
            sampled_misstatements=ms_inputs,
        )

        ProjectionRepo(self.s).upsert(
            project_id, kind, confidence=confidence,
            sampling_interval=sampling_interval,
            tolerable=proj.tolerable,
            projected_misstatement=result.projected_misstatement,
            basic_precision=result.basic_precision,
            incremental_allowance=result.incremental_allowance,
            upper_limit=result.upper_limit,
            verdict=result.verdict,
            strata_snapshot=[{"low": 0.0,
                              "high": max((abs(a.balance_krw) for a in accounts),
                                          default=0.0),
                              "n_required": n}],
        )

        return ProjectionView(
            kind=kind,
            projected_misstatement=result.projected_misstatement,
            basic_precision=result.basic_precision,
            incremental_allowance=result.incremental_allowance,
            upper_limit=result.upper_limit,
            tolerable=proj.tolerable,
            verdict=result.verdict,
            sample_size=n,
            sampling_interval=sampling_interval,
        )
