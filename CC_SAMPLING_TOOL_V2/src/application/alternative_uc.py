"""AlternativeUC — 대체적 절차 등록 + coverage 산정 + persist."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from src.domain.entities import Kind, Verdict
from src.domain.alternative import coverage_verdict
from src.infrastructure.db.repository import (
    ConfirmationRepo, AltProcRepo,
)


@dataclass
class AltProcResult:
    coverage_pct: float
    verdict: str
    covered_amt: float
    non_response_total: float


class AlternativeUC:
    def __init__(self, session):
        self.s = session

    def register(
        self,
        project_id: int,
        kind: Kind,
        *,
        party_id: str,
        procedure_type: str,
        evidence_sum: float,
        note: Optional[str] = None,
    ) -> AltProcResult:
        AltProcRepo(self.s).upsert(
            project_id, kind, party_id=party_id,
            procedure_type=procedure_type, evidence_sum=evidence_sum,
            coverage_pct=0.0, note=note,
        )

        confirmations = ConfirmationRepo(self.s).list_by_project_kind(
            project_id, kind)
        non_response_total = sum(
            abs(c.expected) for c in confirmations
            if c.verdict == Verdict.NO_RESPONSE
        )

        all_procs = AltProcRepo(self.s).list_by_project_kind(project_id, kind)
        covered_amt = sum(p["evidence_sum"] for p in all_procs)

        pct, verdict = coverage_verdict(covered_amt, non_response_total)

        AltProcRepo(self.s).upsert(
            project_id, kind, party_id=party_id,
            procedure_type=procedure_type, evidence_sum=evidence_sum,
            coverage_pct=pct, note=note,
        )

        return AltProcResult(
            coverage_pct=pct, verdict=verdict,
            covered_amt=covered_amt, non_response_total=non_response_total,
        )
