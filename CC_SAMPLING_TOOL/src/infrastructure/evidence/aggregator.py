"""폴더 단위 증빙 합산기 — Week 5 v2 (Week 2 정확도 강화).

BC-{N}_{거래처명} 폴더를 읽어 모든 증빙 파일을 추출하고,
통화별 금액을 합산한 FolderAggregate 를 반환한다.

폴더명 파싱 패턴: BC-(숫자)_(거래처명)
  - BC-14_New Future International Trade Co → bc_numbers=[14], party_name="New Future ..."
  - BC-5,12_채권채무조회서_불일치 소명.xlsx → 단일 파일이므로 aggregate_folder 미사용

하위 폴더는 재귀 탐색 (1단계만; BC-21의 1/2 서브폴더 처리).

Week 2 확장:
  - matched_party_name / match_confidence / match_candidates (top-3)
  - covered_amount_krw / ledger_balance_krw / coverage_ratio
  - conclusion ("충분" | "부분" | "미해소" | "needs_review")
  - low_confidence_files (confidence < LOW_CONFIDENCE_THRESHOLD)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .extractor import EvidenceExtract, extract_evidence

if TYPE_CHECKING:
    from src.domain.currency import CurrencyResolver
    from src.infrastructure.loaders import UploadGuideData

log = logging.getLogger("cc_sampling.evidence.aggregator")

# 지원 확장자
_SUPPORTED_EXTS = {".xls", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg"}

# BC 폴더명 파싱 패턴
_BC_FOLDER_PAT = re.compile(r"^BC-(\d+(?:,\d+)*)_(.+)$", re.IGNORECASE)

# 낮은 신뢰도 임계값
LOW_CONFIDENCE_THRESHOLD = 0.5

# 결론 임계값 (감사실무 기준)
_COVERAGE_SUFFICIENT = 0.95
_COVERAGE_PARTIAL = 0.50


@dataclass
class FolderAggregate:
    """폴더(거래처) 단위 증빙 합산 결과."""

    folder_path: Path
    bc_numbers: list[int]               # 예: [14], [5, 12]
    party_name: Optional[str]           # 폴더명에서 파싱된 거래처명
    extracts: list[EvidenceExtract]     # 파일별 추출 결과

    # 통화별 합산 (extraction_method != "failed" 인 것만)
    amounts_by_currency: dict[str, float] = field(default_factory=dict)

    # 대표값 (단일 통화면 그것, 복수면 KRW 우선)
    total_amount: Optional[float] = None
    total_currency: Optional[str] = None

    # 통계
    total_files: int = 0
    success_count: int = 0
    failed_count: int = 0
    needs_review_count: int = 0         # failed 이지만 파일 자체는 존재

    # ── Week 2: 거래처 매칭 결과 ──────────────────────────────────────────
    matched_party_name: Optional[str] = None
    match_confidence: float = 0.0
    match_candidates: list[str] = field(default_factory=list)  # top-3

    # ── Week 2: 커버리지·결론 ─────────────────────────────────────────────
    covered_amount_krw: Optional[float] = None    # 증빙 합산액 KRW 환산
    ledger_balance_krw: Optional[float] = None    # 장부가 KRW (외부 주입)
    coverage_ratio: Optional[float] = None        # covered / ledger
    conclusion: str = "needs_review"              # "충분"|"부분"|"미해소"|"needs_review"

    # ── Week 2: 낮은 신뢰도 파일 ─────────────────────────────────────────
    low_confidence_files: list[Path] = field(default_factory=list)


def parse_bc_folder_name(folder_name: str) -> tuple[list[int], Optional[str]]:
    """BC-{N}_{거래처명} 폴더명을 파싱.

    Returns:
        (bc_numbers, party_name)
        파싱 실패 시 ([], None)
    """
    m = _BC_FOLDER_PAT.match(folder_name.strip())
    if not m:
        return [], None
    nums_str, party = m.group(1), m.group(2).strip()
    bc_numbers = [int(n) for n in nums_str.split(",")]
    return bc_numbers, party


def _auto_conclusion(coverage_ratio: Optional[float]) -> str:
    """커버리지 비율 → 결론 판정."""
    if coverage_ratio is None:
        return "needs_review"
    if coverage_ratio >= _COVERAGE_SUFFICIENT:
        return "충분"
    if coverage_ratio >= _COVERAGE_PARTIAL:
        return "부분"
    return "미해소"


def aggregate_folder(
    folder_path: Path,
    party_name: Optional[str] = None,
    recursive: bool = True,
    # ── Week 2 추가 파라미터 ─────────────────────────────────────────────
    final_sampled_candidates: Optional[list[str]] = None,
    upload_guide_data=None,              # UploadGuideData | None
    currency_resolver=None,             # CurrencyResolver | None
    ledger_balance_krw: Optional[float] = None,
    party_name_override: Optional[str] = None,
) -> FolderAggregate:
    """폴더 내 모든 지원 파일을 추출·합산.

    Args:
        folder_path:               BC-{N}_{거래처명} 폴더 (또는 임의 폴더)
        party_name:                명시적 거래처명 (None 이면 폴더명에서 파싱)
        recursive:                 True 이면 1단계 하위 폴더까지 탐색
        final_sampled_candidates:  Step 1 최종 선택 거래처명 목록 (매칭용)
        upload_guide_data:         UploadGuideData (동적 alias + 사업자번호)
        currency_resolver:         CurrencyResolver (원통화 → KRW 환산)
        ledger_balance_krw:        장부가 KRW (커버리지 계산용)
        party_name_override:       사용자 확정 거래처명 (매칭 우선순위 최상위)

    Returns:
        FolderAggregate
    """
    folder_path = Path(folder_path)

    # 폴더명 파싱
    bc_numbers, parsed_party = parse_bc_folder_name(folder_path.name)
    effective_party = party_name_override or party_name or parsed_party

    # 파일 수집 (1단계 하위 폴더 포함)
    files: list[Path] = []
    for item in sorted(folder_path.iterdir()):
        if item.is_file() and item.suffix.lower() in _SUPPORTED_EXTS:
            files.append(item)
        elif recursive and item.is_dir():
            # 1단계 하위 폴더만 (BC-21의 "1", "2" 같은 서브폴더)
            for sub_item in sorted(item.iterdir()):
                if sub_item.is_file() and sub_item.suffix.lower() in _SUPPORTED_EXTS:
                    files.append(sub_item)

    extracts: list[EvidenceExtract] = []
    for f in files:
        try:
            ex = extract_evidence(f)
            extracts.append(ex)
        except Exception as e:
            log.warning("추출 오류 %s: %s", f.name, e)
            from .extractor import EvidenceExtract
            extracts.append(EvidenceExtract(
                file_path=f, file_type=f.suffix.lower().lstrip("."),
                document_type=None, extracted_amount=None,
                extracted_currency=None, extracted_date=None,
                extracted_party=None, extraction_method="failed",
                confidence=0.0, raw_text=str(e),
            ))

    # 통화별 합산 + 낮은 신뢰도 파일 분류
    amounts_by_currency: dict[str, float] = {}
    success_count = 0
    failed_count = 0
    needs_review_count = 0
    low_confidence_files: list[Path] = []

    for ex in extracts:
        if ex.extraction_method == "failed":
            failed_count += 1
            if ex.file_path.exists():
                needs_review_count += 1
                low_confidence_files.append(ex.file_path)
        elif ex.extracted_amount is not None:
            cur = ex.extracted_currency or "KRW"
            amounts_by_currency[cur] = amounts_by_currency.get(cur, 0.0) + ex.extracted_amount
            success_count += 1
            if ex.confidence < LOW_CONFIDENCE_THRESHOLD:
                low_confidence_files.append(ex.file_path)
        else:
            # 추출 자체는 됐으나 금액이 없는 경우
            failed_count += 1
            needs_review_count += 1
            low_confidence_files.append(ex.file_path)

    # 대표값 결정
    total_amount: Optional[float] = None
    total_currency: Optional[str] = None
    if amounts_by_currency:
        if "KRW" in amounts_by_currency:
            total_currency = "KRW"
        else:
            # KRW 없으면 금액 가장 큰 통화
            total_currency = max(amounts_by_currency, key=lambda k: amounts_by_currency[k])
        total_amount = amounts_by_currency[total_currency]

    # ── Week 2: 거래처 매칭 ──────────────────────────────────────────────
    matched_party_name: Optional[str] = None
    match_confidence: float = 0.0
    match_candidates: list[str] = []

    # 파일명 폴백: 추출된 거래처명이 없으면 effective_party 사용
    extracted_party_from_files: Optional[str] = None
    for ex in extracts:
        if ex.extracted_party and len(ex.extracted_party) > 2:
            extracted_party_from_files = ex.extracted_party
            break

    query_name = party_name_override or extracted_party_from_files or effective_party

    if party_name_override:
        # 사용자가 직접 확정한 이름 → confidence 1.0
        matched_party_name = party_name_override
        match_confidence = 1.0
    elif query_name and final_sampled_candidates:
        try:
            from src.domain.matching import match_party
            mr = match_party(
                query_name,
                final_sampled_candidates,
                upload_guide_data=upload_guide_data,
                filename_hint=folder_path.name,
            )
            if mr.matched_name:
                matched_party_name = mr.matched_name
                match_confidence = mr.confidence
            match_candidates = mr.candidates[:3]
        except Exception as e:
            log.warning("거래처 매칭 오류: %s", e)
    elif effective_party:
        # 후보 없으면 폴더명 그대로
        matched_party_name = effective_party
        match_confidence = 0.5

    # ── Week 2: KRW 환산 + 커버리지 계산 ────────────────────────────────
    covered_amount_krw: Optional[float] = None

    if amounts_by_currency:
        if "KRW" in amounts_by_currency:
            covered_amount_krw = amounts_by_currency["KRW"]
        elif currency_resolver is not None:
            # 비KRW 통화를 환산
            total_krw = 0.0
            all_converted = True
            for cur, amt in amounts_by_currency.items():
                converted = currency_resolver.original_to_krw(amt, cur)
                if converted is not None:
                    total_krw += converted
                else:
                    all_converted = False
                    log.warning("통화 환산 불가: %s %.2f", cur, amt)
            if total_krw > 0:
                covered_amount_krw = total_krw
            elif not all_converted:
                covered_amount_krw = None  # 환산 실패 → needs_review
        else:
            # CurrencyResolver 없음 — 원통화 금액을 KRW 대용으로 (낮은 정확도)
            covered_amount_krw = total_amount

    # 커버리지 비율
    coverage_ratio: Optional[float] = None
    if ledger_balance_krw and ledger_balance_krw > 0 and covered_amount_krw is not None:
        coverage_ratio = min(1.0, covered_amount_krw / ledger_balance_krw)

    conclusion = _auto_conclusion(coverage_ratio)
    if match_confidence < 0.5 and matched_party_name is None:
        # 매칭 실패 → needs_review 강제
        conclusion = "needs_review"

    return FolderAggregate(
        folder_path=folder_path,
        bc_numbers=bc_numbers,
        party_name=effective_party,
        extracts=extracts,
        amounts_by_currency=amounts_by_currency,
        total_amount=total_amount,
        total_currency=total_currency,
        total_files=len(files),
        success_count=success_count,
        failed_count=failed_count,
        needs_review_count=needs_review_count,
        # Week 2
        matched_party_name=matched_party_name,
        match_confidence=match_confidence,
        match_candidates=match_candidates,
        covered_amount_krw=covered_amount_krw,
        ledger_balance_krw=ledger_balance_krw,
        coverage_ratio=coverage_ratio,
        conclusion=conclusion,
        low_confidence_files=low_confidence_files,
    )
