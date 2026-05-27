"""SQLAlchemy ORM 모델

6개 테이블:
  Project              — 감사 프로젝트 (회사·기간·회계법인)
  Workpaper            — 채권 또는 채무 조서 1건 (샘플링 파라미터·결과 포함)
  Artifact             — 업로드 파일 및 생성 파일 (원장·FS·조서 xlsx 등)
  AuditTrail           — 변경 이력 로그
  ConfirmationReply    — 조회서 회신 PDF 추출·매칭·차이판정 결과 (Week 3)
  AlternativeProcedure — 대체적 절차 (Week 5 placeholder)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Project(Base):
    """감사 프로젝트 — 회사 단위. 채권/채무/both 구분."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    audit_firm: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    period_end: Mapped[str] = mapped_column(String(10), nullable=False)   # YYYY-MM-DD
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="both")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    created_by_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    workpapers: Mapped[list[Workpaper]] = relationship(
        "Workpaper", back_populates="project", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="project", cascade="all, delete-orphan"
    )
    audit_trails: Mapped[list[AuditTrail]] = relationship(
        "AuditTrail", back_populates="project", cascade="all, delete-orphan"
    )


class Workpaper(Base):
    """채권 또는 채무 조서 1건.

    sampling_params, sampling_result 는 JSON 직렬화 문자열로 저장.
    각 단계 완료 시각은 step1_completed_at ~ step5_completed_at 컬럼에 기록.
    """

    __tablename__ = "workpapers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)   # "receivable" | "payable"
    sampling_params: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON
    sampling_result: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON
    ledger_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fs_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rp_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workpaper_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    send_list_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    step1_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    step2_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    step3_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    step4_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    step5_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    project: Mapped[Project] = relationship("Project", back_populates="workpapers")
    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="workpaper",
        foreign_keys="[Artifact.workpaper_id]",
    )


class Artifact(Base):
    """업로드 파일 / 생성 파일 메타데이터.

    실제 파일은 data/projects/{project_id}/artifacts/{artifact_id}_{filename} 에 저장.
    kind: "ledger" | "fs" | "rp" | "workpaper" | "send_list" | "other"
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workpaper_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workpapers.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    uploaded_by_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    project: Mapped[Project] = relationship(
        "Project", back_populates="artifacts"
    )
    workpaper: Mapped[Workpaper | None] = relationship(
        "Workpaper", back_populates="artifacts",
        foreign_keys=[workpaper_id],
    )


class AuditTrail(Base):
    """변경 이력 — 생성·수정·삭제 모두 기록."""

    __tablename__ = "audit_trails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    user_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(50), nullable=False)   # "create"|"update"|"delete"|"run_sampling"
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON
    after_value: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project | None] = relationship("Project", back_populates="audit_trails")


# ── Week 3 ─────────────────────────────────────────────────────────────────
class ConfirmationReply(Base):
    """조회서 회신 — PDF 추출·거래처매칭·차이판정 결과 저장."""

    __tablename__ = "confirmation_replies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workpaper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workpapers.id", ondelete="CASCADE"), nullable=False
    )
    pdf_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # Artifact FK (소프트)

    # 거래처 매칭
    party_name_raw: Mapped[str] = mapped_column(String(500), nullable=False, default="")   # PDF 추출 원문
    party_name_matched: Mapped[str | None] = mapped_column(String(500), nullable=True)     # 매칭된 후보명
    party_match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    party_match_method: Mapped[str | None] = mapped_column(String(30), nullable=True)      # "exact"|"fuzzy_partial"|"fuzzy_token"|"failed"

    # 추출 잔액
    extracted_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_balance_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="KRW")
    reply_date: Mapped[str | None] = mapped_column(String(10), nullable=True)   # YYYY-MM-DD

    # 대사
    ledger_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    difference: Mapped[float | None] = mapped_column(Float, nullable=True)      # ledger - extracted
    difference_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # "matched" | "mismatch" | "extraction_failed" | "pending" | "needs_review"

    # 사용자 검토 확정
    reviewer_confirmed_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # None = 미검토, "confirmed_matched" | "confirmed_mismatch" | "overridden"

    # 추출 메타
    extraction_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    extraction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ── Week 5 placeholder ────────────────────────────────────────────────────
class AlternativeProcedure(Base):
    """대체적 절차 (Week 5 구현 예정). 스키마 placeholder."""

    __tablename__ = "alternative_procedures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workpaper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workpapers.id", ondelete="CASCADE"), nullable=False
    )
    party_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    procedure_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    performed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
