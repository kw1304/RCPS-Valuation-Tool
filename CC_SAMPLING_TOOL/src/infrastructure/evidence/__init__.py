"""증빙 자동 추출 패키지 — Week 5.

EvidenceExtract: 단일 파일 추출 결과 dataclass
FolderAggregate: 폴더(거래처) 단위 합산 결과 dataclass
extractor.extract_evidence(path) → EvidenceExtract
aggregator.aggregate_folder(folder_path) → FolderAggregate
"""
from .extractor import EvidenceExtract, extract_evidence
from .aggregator import FolderAggregate, aggregate_folder

__all__ = [
    "EvidenceExtract", "extract_evidence",
    "FolderAggregate", "aggregate_folder",
]
