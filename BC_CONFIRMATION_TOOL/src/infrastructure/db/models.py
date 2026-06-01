from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    fiscal_date: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Counterparty(SQLModel, table=True):
    # 같은 프로젝트 내 (정규화명, 지점) 중복 거래처 방지 backstop.
    __table_args__ = (
        UniqueConstraint("project_id", "canonical_name", "branch",
                         name="uq_cp_project_name_branch"),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    bc_no: str                                  # BC-1
    canonical_name: str                          # 국민은행
    raw_name: Optional[str] = None
    branch: Optional[str] = None
    is_foreign: bool = False
    channel: Optional[str] = None                # online | postal
    address: Optional[str] = None
    address_valid: Optional[str] = None          # ok | mismatch | not_found | failed
    cs_present: Optional[bool] = None
    prior_present: Optional[bool] = None
    union_listed: Optional[bool] = None
    collateral_listed: Optional[bool] = None
    guarantee_listed: Optional[bool] = None
    response_arrived: bool = False
    gl_sampled: bool = False                     # True iff sampled from G/L (Step 4)
    bs_balance: float = 0.0
    pl_volume: float = 0.0
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FileAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str                                    # gl | cs | prior_cs | union | collateral | guarantee | response
    bc_no: Optional[str] = None
    channel: Optional[str] = None
    original_name: str
    stored_path: str
    parsed_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExtractedRecord(SQLModel, table=True):
    """AC1~AC8 추출 record. ac_section으로 시트 구분."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    # 매칭 안 된 회신본은 0(미배정). FK 강제(PRAGMA)는 기존 테이블 NOT NULL 재구축이
    # 필요해 보류 — nullable 전환은 별도 마이그레이션 작업으로 분리.
    counterparty_id: int = Field(foreign_key="counterparty.id", index=True)
    ac_section: str                              # AC1 | AC2 | ... | AC8
    payload_json: str                            # 도메인 모델 직렬화
    confidence: str = "high"                     # high | medium | low
    source_file: Optional[str] = None
    source_page: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    needs_manual_review: bool = False            # 우편/비표준 → 감사인 직접 확인
    form_family: Optional[str] = None            # bank|securities|insurance|surety|unknown
