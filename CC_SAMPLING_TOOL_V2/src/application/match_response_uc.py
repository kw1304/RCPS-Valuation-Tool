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

        # filename 매칭만 사용 — text fallback 차단 (발신자 거명 오매칭 방지).
        # PDF 회신서는 보통 거래처명을 파일명에 포함하므로 신뢰 가능.
        from src.domain.party_normalize import match_party
        filename = Path(pdf_path).stem
        matched_name = match_party(filename, candidates)

        # text는 금액 추출 용도로만 사용 (거래처 매칭 X)
        extr = extract_party_amount(text, candidate_parties=[])
        # 금액 추출은 별도 — text에서 가장 큰 숫자 사용
        # extract_party_amount는 matched_party가 None이어도 amount는 추출.

        acc = by_name.get(matched_name) if matched_name else None
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
