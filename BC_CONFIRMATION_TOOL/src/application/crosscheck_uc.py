from pathlib import Path
from sqlmodel import Session, select
from src.domain.crosscheck import bidirectional_compare, prior_compare, listed_in_cs
from src.domain.party_normalize import PartyNormalizer
from src.infrastructure.cs_loader import ControlSheetLoader
from src.infrastructure.union_monthly import parse_collateral_or_guarantee, parse_union_monthly
from src.infrastructure.address_validator import AddressValidator
from src.infrastructure.db.models import FileAsset, Counterparty

ROOT = Path(__file__).resolve().parents[2]

def _normalize_cs_row(row: dict, norm: PartyNormalizer) -> dict:
    """CS row → enriched dict with normalized canonical/branch + raw fields."""
    text = " ".join(filter(None, [row.get("name"), row.get("branch")]))
    np = norm.normalize(text or "")
    return {
        "bc_no": row.get("bc_no"),
        "raw_name": row.get("name"),
        "raw_branch": row.get("branch"),
        "channel": row.get("channel"),
        "address": row.get("address"),
        "canonical": np.canonical,
        "branch": np.branch,
        "is_foreign": np.is_foreign,
    }

def _load_cs_parties(path: Path, norm: PartyNormalizer) -> list[tuple[str, str | None]]:
    rows = ControlSheetLoader(path).load_bc_rows()
    return [(d["canonical"], d["branch"]) for d in (_normalize_cs_row(r, norm) for r in rows)]

def _load_listed_parties(path: Path, norm: PartyNormalizer) -> list[tuple[str, str | None]]:
    names = parse_collateral_or_guarantee(path)
    out = []
    for n in names:
        np = norm.normalize(n)
        out.append((np.canonical, np.branch))
    return list(set(out))

def _upsert_from_cs(session: Session, project_id: int, cs_rows: list[dict],
                    existing_by_key: dict) -> list[Counterparty]:
    """CS를 source of truth로 BC-N 재정렬 + G/L 안 잡힌 금융기관 추가.

    CS가 있으면:
      - CS의 BC-N을 그대로 사용
      - 기존 G/L sampling counterparty가 CS와 매칭되면 → CS의 BC-N으로 renumber
      - CS에만 있는 항목 → 신규 추가 (CS의 BC-N 그대로)
      - G/L에만 있고 CS 없는 항목 → BC-GL-N 부여 (예외 케이스)
    """
    added = []
    # CS bc_no → 이미 사용 중인지 추적
    cs_used_bcs: set[str] = set()
    for csr in cs_rows:
        key = (csr["canonical"], csr["branch"])
        cs_bc = csr.get("bc_no") or f"BC-CS-{len(cs_used_bcs)+1}"
        cs_used_bcs.add(cs_bc)
        if key in existing_by_key:
            # 기존 G/L counterparty — CS의 BC-N으로 renumber + 채널·주소 보강
            c = existing_by_key[key]
            c.bc_no = cs_bc
            if csr.get("channel"): c.channel = csr["channel"]
            if csr.get("address"): c.address = csr["address"]
            if csr.get("raw_name"): c.raw_name = csr["raw_name"]
            session.add(c)
            continue
        # CS-only 신규 추가
        c = Counterparty(
            project_id=project_id,
            bc_no=cs_bc,
            canonical_name=csr["canonical"],
            branch=csr["branch"],
            is_foreign=csr["is_foreign"],
            raw_name=csr.get("raw_name"),
            channel=csr.get("channel"),
            address=csr.get("address"),
        )
        session.add(c)
        added.append(c)
        existing_by_key[key] = c
    # G/L 에서 추출됐지만 CS에 없는 counterparty → BC-GL-N으로 renumber (충돌 방지)
    gl_only_idx = 1
    for key, c in existing_by_key.items():
        if c.bc_no in cs_used_bcs and (c.canonical_name, c.branch) in {(r["canonical"], r["branch"]) for r in cs_rows}:
            continue  # already CS-numbered
        if not c.bc_no.startswith("BC-GL-") and c.bc_no not in cs_used_bcs:
            continue  # 안 건드림 (CS 없이 sampling만 한 경우)
        if (c.canonical_name, c.branch) not in {(r["canonical"], r["branch"]) for r in cs_rows}:
            c.bc_no = f"BC-GL-{gl_only_idx}"; gl_only_idx += 1
            session.add(c)
    session.commit()
    for c in added:
        session.refresh(c)
    return added

def run_crosscheck(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    files = {f.kind: f for f in session.exec(select(FileAsset).where(FileAsset.project_id == project_id)).all()}

    # CS 전체 row enriched (auto-upsert·주소 모두 사용)
    cs_rows_full = []
    if "cs" in files:
        raw = ControlSheetLoader(Path(files["cs"].stored_path)).load_bc_rows()
        cs_rows_full = [_normalize_cs_row(r, norm) for r in raw]
    cs_parties = [(d["canonical"], d["branch"]) for d in cs_rows_full]

    # CS auto-upsert: G/L 안 잡힌 금융기관도 Counterparty에 추가
    cps = session.exec(select(Counterparty).where(Counterparty.project_id == project_id)).all()
    cp_by_key = {(c.canonical_name, c.branch): c for c in cps}
    _upsert_from_cs(session, project_id, cs_rows_full, cp_by_key)

    # 갱신된 counterparty list 다시 로드
    cps = session.exec(select(Counterparty).where(Counterparty.project_id == project_id)).all()
    extracted = [(c.canonical_name, c.branch) for c in cps]
    cp_by_key = {(c.canonical_name, c.branch): c for c in cps}

    prior_parties = _load_cs_parties(Path(files["prior_cs"].stored_path), norm) if "prior_cs" in files else []
    union_parties = [(np.canonical, np.branch) for n in (parse_union_monthly(Path(files["union"].stored_path)) if "union" in files else []) for np in [norm.normalize(n)]]
    coll_parties = _load_listed_parties(Path(files["collateral"].stored_path), norm) if "collateral" in files else []
    guar_parties = _load_listed_parties(Path(files["guarantee"].stored_path), norm) if "guarantee" in files else []
    bidir = bidirectional_compare(extracted, cs_parties)
    prior = prior_compare(extracted, prior_parties)
    union = listed_in_cs(union_parties, cs_parties)
    coll  = listed_in_cs(coll_parties, cs_parties)
    guar  = listed_in_cs(guar_parties, cs_parties)
    # 4-5 address (CS 내 postal channel만)
    address_results = []
    if cs_rows_full:
        validator = AddressValidator()
        for r in cs_rows_full:
            if "우편" in (r.get("channel") or ""):
                addr = r.get("address") or ""
                address_results.append({
                    "bc_no": r.get("bc_no"),
                    "name": r.get("raw_name"),
                    "input": addr,
                    **validator.validate(addr),
                })
    # persist into Counterparty columns
    for r in bidir:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.cs_present = (r["status"] == "both")
    for r in prior:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.prior_present = (r["status"] == "both")
    for r in union:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.union_listed = r["present"]
    for r in coll:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.collateral_listed = r["present"]
    for r in guar:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.guarantee_listed = r["present"]
    # address: bc_no 기준 매칭 — 같은 BC-N의 counterparty에 결과 기록
    for r in address_results:
        for c in cps:
            if c.bc_no == r.get("bc_no"):
                c.address_valid = r.get("status")
                break
    session.commit()
    return {
        "bidirectional": bidir, "prior": prior,
        "union": union, "collateral": coll, "guarantee": guar,
        "address": address_results,
    }
