"""Repository — ORM Row ↔ domain dataclass 변환.

application UC만 호출. domain은 이 모듈 import 금지.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from src.domain.entities import (
    Account, Project, Kind, SelectionReason, ResponseStatus, Verdict,
)
from src.infrastructure.db.models import (
    ProjectRow, AccountRow, SampleRow,
    ConfirmationRow, AlternativeProcedureRow, ProjectionRow,
)


class ProjectRepo:
    def __init__(self, session):
        self.s = session

    def create(self, *, client: str, period_end: date, base_ccy: str,
               materiality: float, tolerable: float) -> int:
        row = ProjectRow(client=client, period_end=period_end,
                         base_ccy=base_ccy, materiality=materiality,
                         tolerable=tolerable)
        self.s.add(row)
        self.s.commit()
        return row.id

    def get(self, project_id: int) -> Project:
        row = self.s.get(ProjectRow, project_id)
        if row is None:
            raise KeyError(f"project {project_id} not found")
        return Project(
            id=row.id, client=row.client, period_end=row.period_end,
            base_ccy=row.base_ccy, materiality=row.materiality,
            tolerable=row.tolerable, created_at=row.created_at,
        )

    def list_all(self) -> list[Project]:
        rows = self.s.query(ProjectRow).order_by(ProjectRow.created_at.desc()).all()
        return [
            Project(id=r.id, client=r.client, period_end=r.period_end,
                    base_ccy=r.base_ccy, materiality=r.materiality,
                    tolerable=r.tolerable, created_at=r.created_at)
            for r in rows
        ]


class AccountRepo:
    def __init__(self, session):
        self.s = session

    def bulk_insert(self, project_id: int, kind: Kind,
                    accounts: list[Account]) -> None:
        rows = [
            AccountRow(
                project_id=project_id, kind=kind.value,
                party_id=a.party_id, name=a.name, gl_account=a.gl_account,
                balance_orig=a.balance_orig, ccy=a.ccy, fx_rate=a.fx_rate,
                balance_krw=a.balance_krw,
                is_related_party=a.is_related_party,
                is_bad_debt=a.is_bad_debt, allowance_amt=a.allowance_amt,
                aging_bucket=a.aging_bucket,
                src_sheet=a.src_sheet, src_row=a.src_row,
            )
            for a in accounts
        ]
        self.s.add_all(rows)
        self.s.commit()

    def list_by_project_kind(self, project_id: int,
                             kind: Kind) -> list[Account]:
        rows = (self.s.query(AccountRow)
                .filter(AccountRow.project_id == project_id,
                        AccountRow.kind == kind.value)
                .order_by(AccountRow.id)
                .all())
        return [self._to_domain(r) for r in rows]

    def replace_all(self, project_id: int, kind: Kind,
                    accounts: list[Account]) -> None:
        """재ingest 시: 기존 동일 (project, kind) 모두 삭제 후 insert (atomic)."""
        (self.s.query(AccountRow)
         .filter(AccountRow.project_id == project_id,
                 AccountRow.kind == kind.value)
         .delete(synchronize_session=False))
        rows = [
            AccountRow(
                project_id=project_id, kind=kind.value,
                party_id=a.party_id, name=a.name, gl_account=a.gl_account,
                balance_orig=a.balance_orig, ccy=a.ccy, fx_rate=a.fx_rate,
                balance_krw=a.balance_krw,
                is_related_party=a.is_related_party,
                is_bad_debt=a.is_bad_debt, allowance_amt=a.allowance_amt,
                aging_bucket=a.aging_bucket,
                src_sheet=a.src_sheet, src_row=a.src_row,
            )
            for a in accounts
        ]
        self.s.add_all(rows)
        self.s.commit()

    @staticmethod
    def _to_domain(r: AccountRow) -> Account:
        return Account(
            party_id=r.party_id, name=r.name, gl_account=r.gl_account,
            balance_orig=r.balance_orig, ccy=r.ccy, fx_rate=r.fx_rate,
            balance_krw=r.balance_krw,
            is_related_party=r.is_related_party,
            is_bad_debt=r.is_bad_debt, allowance_amt=r.allowance_amt,
            aging_bucket=r.aging_bucket,
            src_sheet=r.src_sheet, src_row=r.src_row,
        )


class SampleRepo:
    def __init__(self, session):
        self.s = session

    def persist(self, project_id: int, kind: Kind,
                selections: list[tuple[Account, SelectionReason]]) -> None:
        """기존 (project, kind) sample 삭제 후 신규 insert (atomic)."""
        account_rows = (self.s.query(AccountRow)
                        .filter(AccountRow.project_id == project_id,
                                AccountRow.kind == kind.value)
                        .all())
        by_party = {r.party_id: r.id for r in account_rows}

        rows = []
        for acc, reason in selections:
            aid = by_party.get(acc.party_id)
            if aid is None:
                raise ValueError(
                    f"account party_id {acc.party_id!r} not found in DB"
                )
            rows.append(SampleRow(
                project_id=project_id, account_id=aid,
                kind=kind.value, selection_reason=reason.value,
            ))
        # delete-then-insert in single transaction
        (self.s.query(SampleRow)
         .filter(SampleRow.project_id == project_id,
                 SampleRow.kind == kind.value)
         .delete(synchronize_session=False))
        self.s.add_all(rows)
        self.s.commit()

    def list_by_project_kind(self, project_id: int, kind: Kind
                             ) -> list[tuple[Account, SelectionReason]]:
        rows = (self.s.query(SampleRow, AccountRow)
                .join(AccountRow, SampleRow.account_id == AccountRow.id)
                .filter(SampleRow.project_id == project_id,
                        SampleRow.kind == kind.value)
                .all())
        return [
            (AccountRepo._to_domain(a_row),
             SelectionReason(s_row.selection_reason))
            for s_row, a_row in rows
        ]


@dataclass
class _ConfDTO:
    party_id: str
    name: str
    balance_krw: float
    expected: float
    confirmed: Optional[float]
    diff: Optional[float]
    diff_reason: Optional[str]
    verdict: Optional[Verdict]
    status: ResponseStatus
    pdf_path: Optional[str]


class ConfirmationRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, party_id: str,
               expected: float, confirmed: Optional[float],
               verdict: Optional[Verdict], diff_reason: Optional[str],
               pdf_path: Optional[str], status: ResponseStatus) -> None:
        sample = (self.s.query(SampleRow, AccountRow)
                  .join(AccountRow, SampleRow.account_id == AccountRow.id)
                  .filter(SampleRow.project_id == project_id,
                          SampleRow.kind == kind.value,
                          AccountRow.party_id == party_id)
                  .first())
        if sample is None:
            raise ValueError(
                f"sample for project={project_id} kind={kind.value} party={party_id!r} not found")
        sample_row, acc_row = sample

        existing = (self.s.query(ConfirmationRow)
                    .filter(ConfirmationRow.project_id == project_id,
                            ConfirmationRow.sample_id == sample_row.id)
                    .first())
        diff = None if confirmed is None else (confirmed - expected)
        verdict_val = verdict.value if verdict is not None else None
        now = datetime.utcnow()

        if existing is None:
            row = ConfirmationRow(
                project_id=project_id, sample_id=sample_row.id,
                kind=kind.value, expected=expected,
                status=status.value, confirmed=confirmed, diff=diff,
                diff_reason=diff_reason, pdf_path=pdf_path,
                verdict=verdict_val,
                sent_at=None,
                extracted_at=now if confirmed is not None else None,
            )
            self.s.add(row)
        else:
            existing.expected = expected
            existing.status = status.value
            existing.confirmed = confirmed
            existing.diff = diff
            existing.diff_reason = diff_reason
            existing.pdf_path = pdf_path
            existing.verdict = verdict_val
            if confirmed is not None:
                existing.extracted_at = now
        self.s.commit()

    def list_by_project_kind(self, project_id: int, kind: Kind) -> list:
        rows = (self.s.query(ConfirmationRow, AccountRow)
                .join(SampleRow, ConfirmationRow.sample_id == SampleRow.id)
                .join(AccountRow, SampleRow.account_id == AccountRow.id)
                .filter(ConfirmationRow.project_id == project_id,
                        ConfirmationRow.kind == kind.value)
                .all())
        out = []
        for conf, acc in rows:
            out.append(_ConfDTO(
                party_id=acc.party_id, name=acc.name,
                balance_krw=acc.balance_krw,
                expected=conf.expected, confirmed=conf.confirmed,
                diff=conf.diff, diff_reason=conf.diff_reason,
                verdict=Verdict(conf.verdict) if conf.verdict else None,
                status=ResponseStatus(conf.status),
                pdf_path=conf.pdf_path,
            ))
        return out


class AltProcRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, party_id: str,
               procedure_type: str, evidence_sum: float,
               coverage_pct: float, note: Optional[str] = None) -> None:
        sample = (self.s.query(SampleRow, AccountRow)
                  .join(AccountRow, SampleRow.account_id == AccountRow.id)
                  .filter(SampleRow.project_id == project_id,
                          SampleRow.kind == kind.value,
                          AccountRow.party_id == party_id)
                  .first())
        if sample is None:
            raise ValueError(
                f"sample for project={project_id} party={party_id!r} not found")
        sample_row, _ = sample

        existing = (self.s.query(AlternativeProcedureRow)
                    .filter(AlternativeProcedureRow.project_id == project_id,
                            AlternativeProcedureRow.sample_id == sample_row.id)
                    .first())
        if existing is None:
            self.s.add(AlternativeProcedureRow(
                project_id=project_id, sample_id=sample_row.id,
                kind=kind.value, procedure_type=procedure_type,
                evidence_sum=evidence_sum, coverage_pct=coverage_pct,
                note=note,
            ))
        else:
            existing.procedure_type = procedure_type
            existing.evidence_sum = evidence_sum
            existing.coverage_pct = coverage_pct
            existing.note = note
        self.s.commit()

    def list_by_project_kind(self, project_id: int, kind: Kind
                             ) -> list[dict]:
        rows = (self.s.query(AlternativeProcedureRow, AccountRow)
                .join(SampleRow, AlternativeProcedureRow.sample_id == SampleRow.id)
                .join(AccountRow, SampleRow.account_id == AccountRow.id)
                .filter(AlternativeProcedureRow.project_id == project_id,
                        AlternativeProcedureRow.kind == kind.value)
                .all())
        return [{
            "party_id": acc.party_id, "name": acc.name,
            "procedure_type": ap.procedure_type,
            "evidence_sum": ap.evidence_sum,
            "coverage_pct": ap.coverage_pct,
            "note": ap.note,
        } for ap, acc in rows]


class ProjectionRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, confidence: float,
               sampling_interval: float, tolerable: float,
               projected_misstatement: float, basic_precision: float,
               incremental_allowance: float, upper_limit: float,
               verdict: str, strata_snapshot: list[dict]) -> None:
        snap = json.dumps(strata_snapshot, ensure_ascii=False)
        existing = (self.s.query(ProjectionRow)
                    .filter(ProjectionRow.project_id == project_id,
                            ProjectionRow.kind == kind.value)
                    .order_by(ProjectionRow.computed_at.desc())
                    .first())
        if existing is None:
            self.s.add(ProjectionRow(
                project_id=project_id, kind=kind.value,
                confidence=confidence,
                sampling_interval=sampling_interval,
                tolerable=tolerable,
                projected_misstatement=projected_misstatement,
                basic_precision=basic_precision,
                incremental_allowance=incremental_allowance,
                upper_limit=upper_limit, verdict=verdict,
                strata_snapshot=snap,
            ))
        else:
            existing.confidence = confidence
            existing.sampling_interval = sampling_interval
            existing.tolerable = tolerable
            existing.projected_misstatement = projected_misstatement
            existing.basic_precision = basic_precision
            existing.incremental_allowance = incremental_allowance
            existing.upper_limit = upper_limit
            existing.verdict = verdict
            existing.strata_snapshot = snap
            existing.computed_at = datetime.utcnow()
        self.s.commit()

    def get_latest(self, project_id: int, kind: Kind) -> Optional[dict]:
        row = (self.s.query(ProjectionRow)
               .filter(ProjectionRow.project_id == project_id,
                       ProjectionRow.kind == kind.value)
               .order_by(ProjectionRow.computed_at.desc())
               .first())
        if row is None:
            return None
        return {
            "kind": row.kind, "confidence": row.confidence,
            "sampling_interval": row.sampling_interval,
            "tolerable": row.tolerable,
            "projected_misstatement": row.projected_misstatement,
            "basic_precision": row.basic_precision,
            "incremental_allowance": row.incremental_allowance,
            "upper_limit": row.upper_limit, "verdict": row.verdict,
            "strata_snapshot": json.loads(row.strata_snapshot or "[]"),
            "computed_at": row.computed_at.isoformat()
                            if row.computed_at else None,
        }


class SampleDesignRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, confidence: float,
               key_threshold: float, expected_ms_pct: float,
               n_strata: int, seed: Optional[int], population_bv: float,
               n_total: int, strata_snapshot: list[dict]) -> None:
        from src.infrastructure.db.models import SampleDesignRow
        snap = json.dumps(strata_snapshot, ensure_ascii=False)
        existing = (self.s.query(SampleDesignRow)
                    .filter(SampleDesignRow.project_id == project_id,
                            SampleDesignRow.kind == kind.value)
                    .first())
        if existing is None:
            self.s.add(SampleDesignRow(
                project_id=project_id, kind=kind.value,
                confidence=confidence, key_threshold=key_threshold,
                expected_ms_pct=expected_ms_pct, n_strata=n_strata,
                seed=seed, population_bv=population_bv, n_total=n_total,
                strata_snapshot=snap,
            ))
        else:
            existing.confidence = confidence
            existing.key_threshold = key_threshold
            existing.expected_ms_pct = expected_ms_pct
            existing.n_strata = n_strata
            existing.seed = seed
            existing.population_bv = population_bv
            existing.n_total = n_total
            existing.strata_snapshot = snap
            existing.designed_at = datetime.utcnow()
        self.s.commit()

    def get_latest(self, project_id: int, kind: Kind) -> Optional[dict]:
        from src.infrastructure.db.models import SampleDesignRow
        row = (self.s.query(SampleDesignRow)
               .filter(SampleDesignRow.project_id == project_id,
                       SampleDesignRow.kind == kind.value)
               .first())
        if row is None:
            return None
        return {
            "confidence": row.confidence,
            "key_threshold": row.key_threshold,
            "expected_ms_pct": row.expected_ms_pct,
            "n_strata": row.n_strata,
            "seed": row.seed,
            "population_bv": row.population_bv,
            "n_total": row.n_total,
            "strata_snapshot": json.loads(row.strata_snapshot or "[]"),
        }
