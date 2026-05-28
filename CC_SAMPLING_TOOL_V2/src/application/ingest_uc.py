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

        # 1) 시트 자동감지 — AR/AP 매칭되는 모든 시트 누적
        wb = openpyxl.load_workbook(ledger_path, read_only=True)
        sheet_assignments: dict[str, list[str]] = {"AR": [], "AP": []}
        for sn in wb.sheetnames:
            kind = detect_sheet_kind(sn)
            if kind in ("AR", "AP"):
                sheet_assignments[kind].append(sn)

        # 2) RP/충당금 사전로드
        rp_names: set[str] = set()
        synonym_groups: list[list[str]] = []
        if rp_path is not None:
            rp_sheet = self._auto_sheet(rp_path, "RP")
            if rp_sheet:
                rp_names = parse_related_parties(rp_path, rp_sheet)
                from src.infrastructure.ingest.rp_parser import parse_rp_synonym_groups
                synonym_groups = parse_rp_synonym_groups(rp_path, rp_sheet)

        from src.domain.party_normalize import build_synonym_groups
        synonym_map = build_synonym_groups(synonym_groups)

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
            sns = sheet_assignments.get(kind_str, [])
            if not sns:
                continue

            all_enriched: list[Account] = []
            confidences_per_sheet: list[float] = []

            for sn in sns:
                accs, meta = load_account_sheet(ledger_path, sn)
                confidences_per_sheet.append(meta["confidence"])

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
                    # fuzzy RP match: (주)·㈜·공백 차이 흡수
                    from src.domain.party_normalize import match_party
                    is_rp = match_party(a.name, list(rp_names)) is not None if rp_names else False
                    all_enriched.append(Account(
                        party_id=a.party_id, name=a.name,
                        gl_account=a.gl_account,
                        balance_orig=a.balance_orig,
                        ccy=a.ccy.upper(), fx_rate=rate,
                        balance_krw=balance_krw,
                        is_related_party=is_rp,
                        is_bad_debt=bool(allow.get("is_bad_debt", False)),
                        allowance_amt=float(allow.get("allowance_amt",
                                                      a.allowance_amt)),
                        aging_bucket=a.aging_bucket,
                        src_sheet=a.src_sheet, src_row=a.src_row,
                        debit_amt=a.debit_amt, credit_amt=a.credit_amt,
                        business_number=a.business_number,
                        account_breakdowns={a.src_sheet: balance_krw}
                                            if a.src_sheet else {},
                    ))

            # 같은 거래처 집계 — 사업자번호/정규화 이름/synonym map 기준
            aggregated = _aggregate_by_party(all_enriched, synonym_map=synonym_map)

            self.acc.replace_all(project_id, Kind(kind_str), aggregated)
            counts[kind_str] = len(aggregated)
            totals[kind_str] = sum(abs(a.balance_krw) for a in aggregated)
            # 평균 confidence (시트별)
            confidences[kind_str] = (
                sum(confidences_per_sheet) / len(confidences_per_sheet)
                if confidences_per_sheet else 0.0
            )

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


def _aggregate_by_party(
    accounts: list[Account],
    synonym_map: dict[str, str] = None,
) -> list[Account]:
    """거래처 fuzzy 합산.

    매칭 우선순위:
    1. 사업자번호 동일 → 합산
    2. 정규화 이름 동일 → 합산
    3. synonym_map 같은 그룹 → 합산

    합산 시 account_breakdowns dict는 시트별로 누적.
    RP/BAD/allowance는 OR로 합침. name은 한글 우선 + 가장 긴 것 채택.
    src_sheet는 여러 시트 join ("외상매출금+미수금" 형태).
    """
    from collections import defaultdict
    from src.domain.party_normalize import canonical_party_key

    synonym_map = synonym_map or {}
    groups: dict[str, list[Account]] = defaultdict(list)

    for a in accounts:
        key = canonical_party_key(a.name, a.business_number, synonym_map)
        if not key:
            key = a.party_id or f"_{id(a)}"  # fallback
        groups[key].append(a)

    out: list[Account] = []
    for key, items in groups.items():
        if len(items) == 1:
            out.append(items[0])
            continue

        first = items[0]
        balance_orig = sum(x.balance_orig for x in items)
        balance_krw = sum(x.balance_krw for x in items)
        debit_amt = sum(x.debit_amt for x in items)
        credit_amt = sum(x.credit_amt for x in items)
        allowance_amt = sum(x.allowance_amt for x in items)
        is_rp = any(x.is_related_party for x in items)
        is_bad = any(x.is_bad_debt for x in items)
        # 한글 포함 + 가장 긴 name 우선
        def _name_score(n):
            has_kr = any('가' <= ch <= '힯' for ch in n) if n else False
            return (1 if has_kr else 0, len(n or ""))
        name = max((x.name for x in items), key=_name_score)
        # business_number 첫 유효값
        biz = next((x.business_number for x in items if x.business_number), None)
        # party_id 첫 유효값
        pid = next((x.party_id for x in items if x.party_id), first.party_id)
        # src_sheet — 모든 시트 join
        sheets = sorted({x.src_sheet for x in items if x.src_sheet})
        src_sheet = "+".join(sheets) if sheets else first.src_sheet
        # account_breakdowns — dict merge (시트별 잔액)
        breakdowns: dict = {}
        for x in items:
            for sheet, amt in (x.account_breakdowns or {}).items():
                breakdowns[sheet] = breakdowns.get(sheet, 0.0) + amt

        out.append(Account(
            party_id=pid, name=name,
            gl_account=first.gl_account,
            balance_orig=balance_orig,
            ccy=first.ccy, fx_rate=first.fx_rate,
            balance_krw=balance_krw,
            is_related_party=is_rp,
            is_bad_debt=is_bad,
            allowance_amt=allowance_amt,
            aging_bucket=first.aging_bucket,
            src_sheet=src_sheet, src_row=first.src_row,
            debit_amt=debit_amt, credit_amt=credit_amt,
            business_number=biz,
            account_breakdowns=breakdowns,
        ))
    return out
