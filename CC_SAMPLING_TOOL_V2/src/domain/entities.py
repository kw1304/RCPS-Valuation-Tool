"""도메인 엔티티 — 순수 dataclass·enum (Flask·SQLAlchemy·pandas 의존성 없음).

설계서: docs/superpowers/specs/2026-05-28-cc-sampling-tool-v2-design.md §2
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional


class Kind(str, Enum):
    AR = "AR"  # 채권 (매출채권 등)
    AP = "AP"  # 채무 (매입채무 등)


class SelectionReason(str, Enum):
    EXCLUDED_BAD = "EXCLUDED_BAD"
    EXCLUDED_ZERO = "EXCLUDED_ZERO"
    FORCED_RP = "FORCED_RP"
    FORCED_KEY = "FORCED_KEY"
    REP = "REP"


class Verdict(str, Enum):
    MATCH = "MATCH"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"
    NO_RESPONSE = "NO_RESPONSE"


class ResponseStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    NO_RESPONSE = "NO_RESPONSE"
    EXTRACT_FAILED = "EXTRACT_FAILED"


@dataclass
class Project:
    client: str
    period_end: date
    base_ccy: str
    materiality: float
    tolerable: float
    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Account:
    party_id: str
    name: str
    gl_account: str
    balance_orig: float
    ccy: str
    fx_rate: float
    balance_krw: float
    is_related_party: bool = False
    is_bad_debt: bool = False
    allowance_amt: float = 0.0
    aging_bucket: Optional[str] = None
    src_sheet: Optional[str] = None
    src_row: Optional[int] = None
    debit_amt: float = 0.0   # 당기 증가 (AR=매출, AP=매입)
    credit_amt: float = 0.0  # 당기 감소
    business_number: Optional[str] = None
    account_breakdowns: dict = None  # {sheet_name: balance_krw}

    def __post_init__(self):
        if self.account_breakdowns is None:
            self.account_breakdowns = {}

    @property
    def allowance_ratio(self) -> float:
        if abs(self.balance_krw) < 1e-9:
            return 0.0
        return self.allowance_amt / abs(self.balance_krw)


@dataclass
class Strata:
    low: float
    high: float
    n_required: int

    def contains(self, amount: float) -> bool:
        return self.low <= amount <= self.high


@dataclass
class Sample:
    kind: Kind
    accounts: list[tuple[Account, SelectionReason]] = field(default_factory=list)


@dataclass
class Confirmation:
    kind: Kind
    account_party_id: str
    expected: float
    status: ResponseStatus = ResponseStatus.PENDING
    confirmed: Optional[float] = None
    diff: Optional[float] = None
    diff_reason: Optional[str] = None
    pdf_path: Optional[str] = None
    verdict: Optional[Verdict] = None
    sent_at: Optional[datetime] = None
    extracted_at: Optional[datetime] = None


@dataclass
class AlternativeProcedure:
    kind: Kind
    account_party_id: str
    procedure_type: str
    evidence_sum: float
    coverage_pct: float = 0.0


@dataclass
class ProjectionResult:
    kind: Kind
    projected_misstatement: float
    basic_precision: float
    incremental_allowance: float
    upper_limit: float
    tolerable: float
    verdict: Literal["WITHIN_TOLERABLE", "EXCEED"]
