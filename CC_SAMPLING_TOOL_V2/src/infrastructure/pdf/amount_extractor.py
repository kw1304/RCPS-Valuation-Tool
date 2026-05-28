"""PDF 텍스트 → 거래처/금액 추출 (heuristic).

설계서 §6.1 [5]. 한국 회신서 양식 다양 — 거래처 후보 list와 매칭.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractionResult:
    matched_party: Optional[str]
    amount: Optional[float]
    confidence: float = 0.0


_AMOUNT_RE = re.compile(r"[-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-]?\d+(?:\.\d+)?")


def extract_party_amount(
    text: str,
    candidate_parties: list[str],
) -> ExtractionResult:
    """텍스트에서 거래처명·금액 추출.

    전략:
    1. candidate_parties 중 텍스트에 등장한 첫 번째 거래처 선택
    2. 텍스트 내 가장 큰 |금액| 채택
    """
    from src.domain.party_normalize import normalize_party_name
    matched = None
    norm_text = normalize_party_name(text)
    for p in candidate_parties:
        if normalize_party_name(p) in norm_text:
            matched = p
            break

    amounts = []
    for m in _AMOUNT_RE.finditer(text):
        s = m.group(0).replace(",", "")
        try:
            amounts.append(float(s))
        except ValueError:
            continue

    if not amounts:
        return ExtractionResult(matched_party=matched, amount=None,
                                confidence=0.0)
    best = max(amounts, key=abs)
    conf = 0.0
    if matched is not None:
        conf = 0.9 if abs(best) >= 1000 else 0.5
    return ExtractionResult(matched_party=matched, amount=best, confidence=conf)
