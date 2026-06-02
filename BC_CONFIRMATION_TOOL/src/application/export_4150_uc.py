import json
from datetime import datetime
from pathlib import Path
from sqlmodel import Session, select
from src.infrastructure.db.models import Project, Counterparty, ExtractedRecord, FileAsset
from src.infrastructure.excel_writer import toss_workbook
from src.infrastructure.cs_loader import ControlSheetLoader
from src.infrastructure.union_monthly import parse_collateral_or_guarantee, parse_union_monthly
from src.infrastructure.address_validator import AddressValidator
from src.domain.ac_models import (
    FinancialAsset, Borrowing, Derivative, Guarantee,
    Collateral, BillCheck, Insurance, GeneralDeal,
)
from src.domain.party_normalize import PartyNormalizer

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "OUTPUT"

MODEL_BY_SECTION = {
    "AC1": FinancialAsset, "AC2": Borrowing, "AC3": Derivative,
    "AC4": Guarantee, "AC5": Collateral, "AC6": BillCheck,
    "AC7": Insurance, "AC8": GeneralDeal,
}


def export_4150(session: Session, project_id: int) -> Path:
    """Build fresh Toss-style 4150 AC workbook from DB + uploaded files."""
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fy = project.fiscal_date[:4]
    out_path = OUTPUT_DIR / f"4150_AC_금융기관조회_{project.name}_FY{fy}_{ts}.xlsx"

    # Load counterparties + files
    cps = list(session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ).all())
    files = {f.kind: f for f in session.exec(
        select(FileAsset).where(FileAsset.project_id == project_id)
    ).all()}
    norm = PartyNormalizer.load(ROOT / "configs")

    # === AC0 5 sections ===
    cs_keys: set[tuple[str, str | None]] = set()
    cs_rows = []
    if "cs" in files:
        cs_rows = ControlSheetLoader(Path(files["cs"].stored_path)).load_bc_rows()
        for r in cs_rows:
            text = " ".join(filter(None, [r.get("name"), r.get("branch")]))
            np = norm.normalize(text or "")
            cs_keys.add((np.canonical, np.branch))

    def _in_cs_status(canon, branch):
        return "Y" if (canon, branch) in cs_keys else "N"

    # Section 1: 전기 CS
    prior_items = []
    if "prior_cs" in files:
        seen = set()
        for pr in ControlSheetLoader(Path(files["prior_cs"].stored_path)).load_bc_rows():
            text = " ".join(filter(None, [pr.get("name"), pr.get("branch")]))
            np = norm.normalize(text or "")
            key = (np.canonical, np.branch)
            if key in seen: continue
            seen.add(key)
            name = np.canonical + (f" {np.branch}" if np.branch else "")
            prior_items.append({"name": name, "status": _in_cs_status(*key), "reason": ""})

    # Section 2: 월보
    union_items = []
    if "union" in files:
        seen = set()
        for n in parse_union_monthly(Path(files["union"].stored_path)):
            np = norm.normalize(n)
            if not np.matched: continue
            key = (np.canonical, np.branch)
            if key in seen: continue
            seen.add(key)
            name = np.canonical + (f" {np.branch}" if np.branch else "")
            union_items.append({"name": name, "status": _in_cs_status(*key), "reason": ""})

    # Section 3: G/L sampling
    gl_items = []
    gl_cps = [c for c in cps if getattr(c, "gl_sampled", False) or c.bs_balance != 0 or c.pl_volume != 0]
    gl_cps.sort(key=lambda c: -(abs(c.bs_balance) + abs(c.pl_volume)))
    seen = set()
    for cp in gl_cps:
        key = (cp.canonical_name, cp.branch)
        if key in seen: continue
        seen.add(key)
        if cp.bs_balance != 0:
            label = "B/S 잔액"
        elif cp.pl_volume != 0:
            label = "P/L 거래"
        else:
            label = "거래 발생"
        name = cp.canonical_name + (f" {cp.branch}" if cp.branch else "")
        gl_items.append({"label": label, "name": name, "status": _in_cs_status(*key), "reason": ""})

    # Section 4: 담보·보증
    coll_seen = set()
    coll_items = []
    for kind in ("collateral", "guarantee"):
        if kind not in files: continue
        for n in parse_collateral_or_guarantee(Path(files[kind].stored_path)):
            np = norm.normalize(n)
            if not np.matched: continue
            key = (np.canonical, np.branch)
            if key in coll_seen: continue
            coll_seen.add(key)
            name = np.canonical + (f" {np.branch}" if np.branch else "")
            coll_items.append({"name": name, "status": _in_cs_status(*key), "reason": ""})
    coll_items.sort(key=lambda d: d["name"])

    # Section 5: 우편 주소
    addr_items = []
    if cs_rows:
        validator = AddressValidator()
        for r in cs_rows:
            if "우편" not in (r.get("channel") or ""): continue
            text = " ".join(filter(None, [r.get("name"), r.get("branch")]))
            np = norm.normalize(text or "")
            address = r.get("address") or ""
            res = validator.validate(address)
            status = res.get("status", "")
            # display label
            label_map = {
                "ok": "Y", "foreign": "Y (해외)",
                "mismatch": "△ 정정필요", "incomplete": "△ 보완필요",
                "not_found": "N (없음)", "failed": "수기확인",
            }
            addr_items.append({
                "bc_no": r.get("bc_no", ""),
                "name": np.canonical + (f" {np.branch}" if np.branch else ""),
                "branch": r.get("branch", "") or "",
                "address": address,
                "status": label_map.get(status, status),
            })

    ac0_sections = {
        "prior": prior_items,
        "union": union_items,
        "gl": gl_items,
        "collateral": coll_items,
        "address": addr_items,
    }

    # === AC1~AC8 records ===
    # AC 시트 BC번호를 회신본 파일명 번호가 아니라 가나다 통일 counterparty 번호로 표기.
    _cp_bc_by_id = {c.id: c.bc_no for c in cps}
    _cp_bc_by_name = {c.canonical_name: c.bc_no for c in cps}

    def _load_recs(ac_section):
        raw = session.exec(
            select(ExtractedRecord).where(
                ExtractedRecord.project_id == project_id,
                ExtractedRecord.ac_section == ac_section,
            )
        ).all()
        out = []
        for r in raw:
            payload = json.loads(r.payload_json)
            # 매칭된 counterparty 의 가나다 BC번호로 치환(없으면 은행명으로, 그래도 없으면 원본).
            bc = _cp_bc_by_id.get(r.counterparty_id) or _cp_bc_by_name.get(payload.get("bank", ""))
            if bc:
                payload["bc_no"] = bc
            out.append(payload)
        return out

    wb = toss_workbook.build_workbook(
        company=project.name,
        fiscal_date=project.fiscal_date,
        cps=cps,
        ac0_sections=ac0_sections,
        ac1_recs=_load_recs("AC1"),
        ac1_detail_recs=_load_recs("AC1_DETAIL"),
        ac2_recs=_load_recs("AC2"),
        ac3_recs=_load_recs("AC3"),
        ac4_recs=_load_recs("AC4"),
        ac5_recs=_load_recs("AC5"),
        ac6_recs=_load_recs("AC6"),
        ac7_recs=_load_recs("AC7"),
        ac8_recs=_load_recs("AC8"),
    )
    wb.save(out_path)
    return out_path
