"""MatchResponseUC — PDF 1건 → 추출 + judge + persist."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from src.domain.entities import Kind, Verdict, ResponseStatus
from src.domain.matching import judge_response
from src.infrastructure.db.repository import (
    AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.infrastructure.pdf.extractor import extract_text, PdfExtractError
from src.infrastructure.pdf.amount_extractor import extract_party_amount


@dataclass
class MatchResult:
    matched_party: Optional[str]
    confirmed: Optional[float]
    verdict: Verdict
    extraction_confidence: float


class MatchResponseUC:
    def __init__(self, session):
        self.s = session

    def match_one(
        self, pid: int, kind: Kind, pdf_path: Path,
        diff_reason: Optional[str] = None,
    ) -> MatchResult:
        sample = SampleRepo(self.s).list_by_project_kind(pid, kind)
        candidates = [acc.name for acc, _ in sample]
        by_name = {acc.name: acc for acc, _ in sample}

        try:
            text = extract_text(pdf_path)
        except PdfExtractError:
            text = ""

        extr = extract_party_amount(text, candidate_parties=candidates)

        acc = by_name.get(extr.matched_party) if extr.matched_party else None
        if acc is None:
            return MatchResult(
                matched_party=None, confirmed=None,
                verdict=Verdict.NO_RESPONSE,
                extraction_confidence=0.0,
            )

        verdict = judge_response(
            expected=acc.balance_krw,
            confirmed=extr.amount, diff_reason=diff_reason,
        )
        status = (ResponseStatus.RECEIVED
                  if extr.amount is not None else ResponseStatus.NO_RESPONSE)
        ConfirmationRepo(self.s).upsert(
            pid, kind, party_id=acc.party_id,
            expected=acc.balance_krw, confirmed=extr.amount,
            verdict=verdict, diff_reason=diff_reason,
            pdf_path=str(pdf_path), status=status,
        )
        return MatchResult(
            matched_party=acc.party_id, confirmed=extr.amount,
            verdict=verdict, extraction_confidence=extr.confidence,
        )
