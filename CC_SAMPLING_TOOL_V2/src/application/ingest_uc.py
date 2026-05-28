"""IngestUC — 파일 → Population[AR/AP] persist orchestration.

설계서 §6.1 [2].
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import openpyxl

from src.domain.entities import Account, Kind
from src.domain.fx import convert_to_base, FxRateMissing
from src.infrastructure.db.repository import ProjectRepo, AccountRepo
from src.infrastructure.ingest.excel_loader import (
    detect_sheet_kind, load_account_sheet,
)
from src.infrastructure.ingest.rp_parser import parse_related_parties
from src.infrastructure.ingest.allowance_parser import parse_allowance
from src.infrastructure.ingest.fs_parser import parse_fs_totals


@dataclass
class IngestResult:
    project_id: int
    ar_count: int
    ap_count: int
    ar_total_krw: float
    ap_total_krw: float
    confidence_ar: float
    confidence_ap: float
    fs_totals: dict
    needs_mapping_confirmation: bool


class IngestUC:
    def __init__(self, session, fx_client):
        self.s = session
        self.fx = fx_client
        self.proj = ProjectRepo(session)
        self.acc = AccountRepo(session)

    def ingest(
        self,
        project_id: int,
        ledger_path: Path,
        fs_path: Optional[Path],
        rp_path: Optional[Path],
        allowance_path: Optional[Path],
    ) -> IngestResult:
        project = self.proj.get(project_id)

        # 1) 시트 자동감지
        wb = openpyxl.load_workbook(ledger_path, read_only=True)
        sheet_assignment: dict[str, str] = {}
        for sn in wb.sheetnames:
            kind = detect_sheet_kind(sn)
            if kind in ("AR", "AP"):
                sheet_assignment.setdefault(kind, sn)

        # 2) RP/충당금 사전로드
        rp_names: set[str] = set()
        if rp_path is not None:
            rp_sheet = self._auto_sheet(rp_path, "RP")
            if rp_sheet:
                rp_names = parse_related_parties(rp_path, rp_sheet)

        allow_map: dict[str, dict] = {}
        if allowance_path is not None:
            allow_sheet = self._auto_sheet(allowance_path, "ALLOWANCE")
            if allow_sheet:
                allow_map = parse_allowance(allowance_path, allow_sheet)

        # 3) FS totals (cross-check 정보)
        fs_totals: dict[str, float] = {}
        if fs_path is not None:
            fs_sheet = self._auto_sheet(fs_path, "FS")
            if fs_sheet:
                fs_totals = parse_fs_totals(fs_path, fs_sheet)

        # 4) AR/AP 로드 + 플래그 + 환산 + persist
        counts = {"AR": 0, "AP": 0}
        totals = {"AR": 0.0, "AP": 0.0}
        confidences = {"AR": 0.0, "AP": 0.0}
        for kind_str in ("AR", "AP"):
            sn = sheet_assignment.get(kind_str)
            if sn is None:
                continue
            accs, meta = load_account_sheet(ledger_path, sn)
            confidences[kind_str] = meta["confidence"]

            enriched: list[Account] = []
            for a in accs:
                rate = a.fx_rate
                if a.ccy.upper() != project.base_ccy.upper():
                    try:
                        rate = self.fx.lookup(a.ccy, project.period_end)
                    except Exception:
                        rate = a.fx_rate
                try:
                    balance_krw = convert_to_base(
                        a.balance_orig, a.ccy, project.base_ccy, rate
                    )
                except FxRateMissing:
                    balance_krw = a.balance_orig

                allow = allow_map.get(a.party_id, {})
                enriched.append(Account(
                    party_id=a.party_id, name=a.name,
                    gl_account=a.gl_account,
                    balance_orig=a.balance_orig,
                    ccy=a.ccy.upper(), fx_rate=rate,
                    balance_krw=balance_krw,
                    is_related_party=(a.name in rp_names),
                    is_bad_debt=bool(allow.get("is_bad_debt", False)),
                    allowance_amt=float(allow.get("allowance_amt",
                                                  a.allowance_amt)),
                    aging_bucket=a.aging_bucket,
                    src_sheet=a.src_sheet, src_row=a.src_row,
                ))

            self.acc.replace_all(project_id, Kind(kind_str), enriched)
            counts[kind_str] = len(enriched)
            totals[kind_str] = sum(abs(a.balance_krw) for a in enriched)

        needs_confirm = (
            (confidences["AR"] > 0 and confidences["AR"] < 0.95)
            or (confidences["AP"] > 0 and confidences["AP"] < 0.95)
        )

        return IngestResult(
            project_id=project_id,
            ar_count=counts["AR"], ap_count=counts["AP"],
            ar_total_krw=totals["AR"], ap_total_krw=totals["AP"],
            confidence_ar=confidences["AR"],
            confidence_ap=confidences["AP"],
            fs_totals=fs_totals,
            needs_mapping_confirmation=needs_confirm,
        )

    @staticmethod
    def _auto_sheet(path: Path, target_kind: str) -> Optional[str]:
        wb = openpyxl.load_workbook(path, read_only=True)
        for sn in wb.sheetnames:
            if detect_sheet_kind(sn) == target_kind:
                return sn
        return wb.sheetnames[0] if wb.sheetnames else None
