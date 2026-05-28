"""SQLAlchemy 모델 — domain entity와 1:1 매핑.

NOTE: domain은 이 모듈을 import 금지.
의존방향: api/application → domain ← infrastructure.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    ForeignKey, CheckConstraint, Text,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class ProjectRow(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    client = Column(String(200), nullable=False)
    period_end = Column(Date, nullable=False)
    base_ccy = Column(String(3), nullable=False, default="KRW")
    materiality = Column(Float, nullable=False)
    tolerable = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    accounts = relationship("AccountRow", back_populates="project",
                            cascade="all, delete-orphan")


class AccountRow(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_account_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    party_id = Column(String(50), nullable=False)
    name = Column(String(200), nullable=False)
    gl_account = Column(String(50), nullable=False)
    balance_orig = Column(Float, nullable=False)
    ccy = Column(String(3), nullable=False)
    fx_rate = Column(Float, nullable=False)
    balance_krw = Column(Float, nullable=False)
    is_related_party = Column(Boolean, default=False, nullable=False)
    is_bad_debt = Column(Boolean, default=False, nullable=False)
    allowance_amt = Column(Float, default=0.0, nullable=False)
    debit_amt = Column(Float, default=0.0, nullable=False)
    credit_amt = Column(Float, default=0.0, nullable=False)
    aging_bucket = Column(String(50))
    src_sheet = Column(String(200))
    src_row = Column(Integer)

    project = relationship("ProjectRow", back_populates="accounts")


class SampleRow(Base):
    __tablename__ = "samples"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_sample_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    selection_reason = Column(String(20), nullable=False)


class ConfirmationRow(Base):
    __tablename__ = "confirmations"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_conf_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    expected = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    confirmed = Column(Float)
    diff = Column(Float)
    diff_reason = Column(String(100))
    pdf_path = Column(Text)
    verdict = Column(String(20))
    sent_at = Column(DateTime)
    extracted_at = Column(DateTime)


class AlternativeProcedureRow(Base):
    __tablename__ = "alternative_procedures"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_altproc_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    procedure_type = Column(String(50), nullable=False)
    evidence_sum = Column(Float, nullable=False, default=0.0)
    coverage_pct = Column(Float, nullable=False, default=0.0)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProjectionRow(Base):
    __tablename__ = "projections"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_projection_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    confidence = Column(Float, nullable=False)
    sampling_interval = Column(Float, nullable=False)
    tolerable = Column(Float, nullable=False)
    projected_misstatement = Column(Float, nullable=False)
    basic_precision = Column(Float, nullable=False)
    incremental_allowance = Column(Float, nullable=False)
    upper_limit = Column(Float, nullable=False)
    verdict = Column(String(30), nullable=False)
    strata_snapshot = Column(Text)
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SampleDesignRow(Base):
    __tablename__ = "sample_designs"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_design_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    confidence = Column(Float, nullable=False)
    key_threshold = Column(Float, nullable=False)
    expected_ms_pct = Column(Float, nullable=False)
    n_strata = Column(Integer, nullable=False)
    seed = Column(Integer)
    population_bv = Column(Float, nullable=False)
    n_total = Column(Integer, nullable=False)
    strata_snapshot = Column(Text)
    designed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
