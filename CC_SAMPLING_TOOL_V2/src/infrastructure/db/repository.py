"""Repository — ORM Row ↔ domain dataclass 변환.

application UC만 호출. domain은 이 모듈 import 금지.
"""
from __future__ import annotations
from datetime import date
from src.domain.entities import (
    Account, Project, Kind, SelectionReason,
)
from src.infrastructure.db.models import (
    ProjectRow, AccountRow, SampleRow,
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
        """재ingest 시: 기존 동일 (project, kind) 모두 삭제 후 insert."""
        (self.s.query(AccountRow)
         .filter(AccountRow.project_id == project_id,
                 AccountRow.kind == kind.value)
         .delete(synchronize_session=False))
        self.s.commit()
        self.bulk_insert(project_id, kind, accounts)

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
        """기존 (project, kind) sample 삭제 후 신규 insert."""
        (self.s.query(SampleRow)
         .filter(SampleRow.project_id == project_id,
                 SampleRow.kind == kind.value)
         .delete(synchronize_session=False))
        self.s.commit()

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
