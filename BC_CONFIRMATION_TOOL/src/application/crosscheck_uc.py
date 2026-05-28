from pathlib import Path
from sqlmodel import Session, select
from src.domain.crosscheck import bidirectional_compare, prior_compare, listed_in_cs
from src.domain.party_normalize import PartyNormalizer
from src.infrastructure.cs_loader import ControlSheetLoader
from src.infrastructure.union_monthly import parse_collateral_or_guarantee, parse_union_monthly
from src.infrastructure.address_validator import AddressValidator
from src.infrastructure.db.models import FileAsset, Counterparty

ROOT = Path(__file__).resolve().parents[2]

def _load_cs_parties(path: Path, norm: PartyNormalizer) -> list[tuple[str, str | None]]:
    rows = ControlSheetLoader(path).load_bc_rows()
    out = []
    for r in rows:
        text = " ".join(filter(None, [r.get("name"), r.get("branch")]))
        np = norm.normalize(text or "")
        out.append((np.canonical, np.branch))
    return out

def _load_listed_parties(path: Path, norm: PartyNormalizer) -> list[tuple[str, str | None]]:
    names = parse_collateral_or_guarantee(path)
    out = []
    for n in names:
        np = norm.normalize(n)
        out.append((np.canonical, np.branch))
    # dedup
    return list(set(out))

def run_crosscheck(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    cps = session.exec(select(Counterparty).where(Counterparty.project_id == project_id)).all()
    extracted = [(c.canonical_name, c.branch) for c in cps]
    files = {f.kind: f for f in session.exec(select(FileAsset).where(FileAsset.project_id == project_id)).all()}
    cs_parties = _load_cs_parties(Path(files["cs"].stored_path), norm) if "cs" in files else []
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
    if cs_parties and "cs" in files:
        validator = AddressValidator()
        rows = ControlSheetLoader(Path(files["cs"].stored_path)).load_bc_rows()
        for r in rows:
            if (r.get("channel") or "").strip() in {"우편","우편 회신"}:
                addr = r.get("address") or ""
                address_results.append({
                    "bc_no": r.get("bc_no"),
                    "name": r.get("name"),
                    "input": addr,
                    **validator.validate(addr),
                })
    # persist into Counterparty columns
    cp_by_key = {(c.canonical_name, c.branch): c for c in cps}
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
    session.commit()
    return {
        "bidirectional": bidir, "prior": prior,
        "union": union, "collateral": coll, "guarantee": guar,
        "address": address_results,
    }
