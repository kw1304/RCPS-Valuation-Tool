"""폴더 단위 증빙 합산기 — Week 5.

BC-{N}_{거래처명} 폴더를 읽어 모든 증빙 파일을 추출하고,
통화별 금액을 합산한 FolderAggregate 를 반환한다.

폴더명 파싱 패턴: r'BC-(\d+(?:,\d+)*)_(.+)'
  - BC-14_New Future International Trade Co → bc_numbers=[14], party_name="New Future ..."
  - BC-5,12_채권채무조회서_불일치 소명.xlsx → 단일 파일이므로 aggregate_folder 미사용

하위 폴더는 재귀 탐색 (1단계만; BC-21의 1/2 서브폴더 처리).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .extractor import EvidenceExtract, extract_evidence

log = logging.getLogger("cc_sampling.evidence.aggregator")

# 지원 확장자
_SUPPORTED_EXTS = {".xls", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg"}

# BC 폴더명 파싱 패턴
_BC_FOLDER_PAT = re.compile(r"^BC-(\d+(?:,\d+)*)_(.+)$", re.IGNORECASE)


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


def aggregate_folder(
    folder_path: Path,
    party_name: Optional[str] = None,
    recursive: bool = True,
) -> FolderAggregate:
    """폴더 내 모든 지원 파일을 추출·합산.

    Args:
        folder_path: BC-{N}_{거래처명} 폴더 (또는 임의 폴더)
        party_name: 명시적 거래처명 (None 이면 폴더명에서 파싱)
        recursive: True 이면 1단계 하위 폴더까지 탐색

    Returns:
        FolderAggregate
    """
    folder_path = Path(folder_path)

    # 폴더명 파싱
    bc_numbers, parsed_party = parse_bc_folder_name(folder_path.name)
    effective_party = party_name or parsed_party

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

    # 통화별 합산
    amounts_by_currency: dict[str, float] = {}
    success_count = 0
    failed_count = 0
    needs_review_count = 0

    for ex in extracts:
        if ex.extraction_method == "failed":
            failed_count += 1
            if ex.file_path.exists():
                needs_review_count += 1
        elif ex.extracted_amount is not None:
            cur = ex.extracted_currency or "KRW"
            amounts_by_currency[cur] = amounts_by_currency.get(cur, 0.0) + ex.extracted_amount
            success_count += 1
        else:
            # 추출 자체는 됐으나 금액이 없는 경우
            failed_count += 1
            needs_review_count += 1

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
    )
