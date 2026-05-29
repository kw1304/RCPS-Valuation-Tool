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
    def _load_recs(ac_section):
        raw = session.exec(
            select(ExtractedRecord).where(
                ExtractedRecord.project_id == project_id,
                ExtractedRecord.ac_section == ac_section,
            )
        ).all()
        return [json.loads(r.payload_json) for r in raw]

    wb = toss_workbook.build_workbook(
        company=project.name,
        fiscal_date=project.fiscal_date,
        cps=cps,
        ac0_sections=ac0_sections,
        ac1_recs=_load_recs("AC1"),
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


def _safe_write(sheet, cell_ref: str, value) -> None:
    """Merged cell 에 쓰기 시도 시 조용히 skip."""
    cell = sheet[cell_ref]
    if isinstance(cell, MergedCell):
        return
    cell.value = value


def _fill_control_sheet(wb, cps: list[Counterparty]):
    """Fill AC control sheet with counterparty summary."""
    sheet = next((wb[s] for s in wb.sheetnames if "control sheet" in s.lower()), None)
    if sheet is None:
        return

    for i, cp in enumerate(cps):
        r = 6 + i
        _safe_write(sheet, f"B{r}", cp.bc_no)
        _safe_write(sheet, f"C{r}", cp.canonical_name)
        if cp.branch:
            _safe_write(sheet, f"D{r}", cp.branch)
        _safe_write(sheet, f"E{r}", cp.channel or "")
        _safe_write(sheet, f"F{r}", cp.address or "")
        _safe_write(sheet, f"J{r}", "회신" if cp.response_arrived else "미회신")


def _fill_ac0(wb, cps: list[Counterparty], files: dict, norm):
    """V1 AC0 시트의 5개 sub-section을 각각 fill.

    V1 AC0 구조:
      R11    Section 1 header: 전기 금융조회 대상 / 회사 list 포함? / 제외사유
      R12+   Section 1 data (전기 CS list)
      R47    Section 2 header: 은행연합회 월보 / 회사 list 포함? / 제외사유
      R48+   Section 2 data (월보 list)
      R71    Section 3 header: 구분(계정) / 계정별원장상 금융기관 / 회사 list 포함?
      R72+   Section 3 data (G/L 계정별)
      R91    Section 4 header: 담보·보증명세서 / 회사 list 포함?
      R92+   Section 4 data
      R102   Section 5 header: 구분 / 부서 / 인터넷상 주소 / G:일치여부
      R103+  Section 5 data (우편 조회처 주소)
    """
    sheet = next((wb[s] for s in wb.sheetnames if s.startswith("AC0.")), None)
    if sheet is None:
        return

    # CS 에 포함된 (canonical, branch) 집합 — 비교 기준
    cs_keys: set[tuple[str, str | None]] = set()
    cs_rows = []
    if "cs" in files:
        cs_rows = ControlSheetLoader(Path(files["cs"].stored_path)).load_bc_rows()
        for r in cs_rows:
            text = " ".join(filter(None, [r.get("name"), r.get("branch")]))
            np = norm.normalize(text or "")
            cs_keys.add((np.canonical, np.branch))

    def _in_cs(canon: str, branch: str | None) -> str:
        return "Y" if (canon, branch) in cs_keys else "N"

    # === Section 1: 전기 CS list ===
    if "prior_cs" in files:
        prior_rows = ControlSheetLoader(Path(files["prior_cs"].stored_path)).load_bc_rows()
        seen = set()
        row_idx = 12
        for pr in prior_rows:
            text = " ".join(filter(None, [pr.get("name"), pr.get("branch")]))
            np = norm.normalize(text or "")
            key = (np.canonical, np.branch)
            if key in seen:
                continue
            seen.add(key)
            display = np.canonical + (f" {np.branch}" if np.branch else "")
            _safe_write(sheet, f"C{row_idx}", display)
            _safe_write(sheet, f"D{row_idx}", _in_cs(np.canonical, np.branch))
            row_idx += 1
            if row_idx > 44:
                break

    # === Section 2: 은행연합회 월보 list ===
    if "union" in files:
        names = parse_union_monthly(Path(files["union"].stored_path))
        seen = set()
        row_idx = 48
        for n in names:
            np = norm.normalize(n)
            if not np.matched:
                continue
            key = (np.canonical, np.branch)
            if key in seen:
                continue
            seen.add(key)
            display = np.canonical + (f" {np.branch}" if np.branch else "")
            _safe_write(sheet, f"C{row_idx}", display)
            _safe_write(sheet, f"D{row_idx}", _in_cs(np.canonical, np.branch))
            row_idx += 1
            if row_idx > 67:
                break

    # === Section 3: G/L 계정별원장 검토 ===
    # gl_sampled=True 인 모든 counterparty, 중요도(|bs|+|pl|) 큰 순 sort
    gl_cps = [
        cp for cp in cps
        if getattr(cp, "gl_sampled", False) or cp.bs_balance != 0 or cp.pl_volume != 0
    ]
    gl_cps.sort(key=lambda c: -(abs(c.bs_balance) + abs(c.pl_volume)))
    # 행 확장으로 모든 G/L cp 표시 (Section 4 헤더 R90~ 이후 row shift 됨)
    SEC3_START = 72
    SEC3_DEFAULT_END = 88
    needed = len(gl_cps)
    sec3_extra = max(0, needed - (SEC3_DEFAULT_END - SEC3_START + 1))
    if sec3_extra > 0:
        try:
            sheet.insert_rows(idx=SEC3_DEFAULT_END + 1, amount=sec3_extra)
        except Exception:
            sec3_extra = 0
    row_idx = SEC3_START
    seen = set()
    for cp in gl_cps:
        key = (cp.canonical_name, cp.branch)
        if key in seen:
            continue
        seen.add(key)
        if cp.bs_balance != 0:
            acc_label = "B/S 잔액"
        elif cp.pl_volume != 0:
            acc_label = "P/L 거래"
        else:
            acc_label = "거래 발생"
        display = cp.canonical_name + (f" {cp.branch}" if cp.branch else "")
        _safe_write(sheet, f"C{row_idx}", acc_label)
        _safe_write(sheet, f"D{row_idx}", display)
        _safe_write(sheet, f"E{row_idx}", _in_cs(cp.canonical_name, cp.branch))
        row_idx += 1
        if row_idx > SEC3_DEFAULT_END + sec3_extra:
            break

    # === Section 4: 담보·보증 명세서 (Section 3 확장에 따라 row shift) ===
    listed_names = set()
    if "collateral" in files:
        for n in parse_collateral_or_guarantee(Path(files["collateral"].stored_path)):
            np = norm.normalize(n)
            if np.matched:
                listed_names.add((np.canonical, np.branch))
    if "guarantee" in files:
        for n in parse_collateral_or_guarantee(Path(files["guarantee"].stored_path)):
            np = norm.normalize(n)
            if np.matched:
                listed_names.add((np.canonical, np.branch))
    row_idx = 92 + sec3_extra
    for canon, branch in sorted(listed_names, key=lambda kb: (kb[0], kb[1] or "")):
        display = canon + (f" {branch}" if branch else "")
        _safe_write(sheet, f"C{row_idx}", display)
        _safe_write(sheet, f"D{row_idx}", _in_cs(canon, branch))
        row_idx += 1
        if row_idx > 100 + sec3_extra:
            break

    # === Section 5: 우편 조회처 주소 유효성 ===
    row_idx = 103 + sec3_extra
    for r in cs_rows:
        if "우편" not in (r.get("channel") or ""):
            continue
        # 우리 counterparty 매칭
        text = " ".join(filter(None, [r.get("name"), r.get("branch")]))
        np = norm.normalize(text or "")
        cp = next((c for c in cps if (c.canonical_name, c.branch) == (np.canonical, np.branch)), None)
        # address_valid: ok|foreign → Y, mismatch|incomplete → △, not_found|failed → N
        valid_status = (cp.address_valid if cp else None) or ""
        if valid_status == "ok":
            addr_valid = "Y"
        elif valid_status == "foreign":
            addr_valid = "Y (해외)"
        elif valid_status in {"mismatch", "incomplete"}:
            addr_valid = "△ 검토필요"
        else:
            addr_valid = "수기확인"
        display = np.canonical + (f" {np.branch}" if np.branch else "")
        _safe_write(sheet, f"C{row_idx}", display)
        _safe_write(sheet, f"D{row_idx}", r.get("branch") or "")
        _safe_write(sheet, f"E{row_idx}", r.get("address") or "")
        _safe_write(sheet, f"G{row_idx}", addr_valid)
        row_idx += 1
        if row_idx > 110 + sec3_extra:
            break


def _stamp_project_info(wb, company_name: str, fiscal_date: str):
    """Stamp 회사명·기준일 onto each AC sheet.
    AC control sheet의 A1·A3에 박으면 AC1~AC10은 formula로 자동 참조."""
    # 회사명: 보통 'A1' 위치. AC1~AC10은 formula로 control sheet를 참조함.
    for sheet_name in wb.sheetnames:
        if sheet_name.startswith("AC1~AC8"):
            continue  # divider sheet
        ws = wb[sheet_name]
        # A1: 회사명 (control sheet에서만 직접 stamp; 나머지는 formula 유지)
        if "control sheet" in sheet_name.lower() or sheet_name.startswith("AC0."):
            _safe_write(ws, "A1", f"{company_name} 주식회사")
        # A3: 기준일
        _safe_write(ws, "A3", fiscal_date)


# AC0는 5개 sub-section의 data row 영역만 clear (header·절차텍스트·결론 보존)
_AC0_SUBSECTION_RANGES = [
    (12, 44),    # Section 1: 전기 CS list data
    (48, 67),    # Section 2: 월보 list data
    (72, 88),    # Section 3: G/L 계정별 data
    (92, 100),   # Section 4: 담보·보증 data
    (103, 110),  # Section 5: 우편 주소 data
]

# AC1~AC8 data row 영역 (start_row, max data end — V1 결론 직전).
# end_row 이후는 결론·합계·footer → 절대 침범 X
_DATA_REGION = {
    "AC1.": (11, 128),   # 금융자산: 결론 R129
    "AC2.": (12, 47),    # 차입금: 결론 R48
    "AC3.": (12, 26),    # 파생상품: 결론 R27
    "AC4.": (13, 61),    # 지급보증: 결론 R62
    "AC5.": (12, 60),    # 담보제공자산: 결론 R61
    "AC6.": (13, 43),    # 어음·수표: 결론 R44
    "AC7.": (12, 45),    # 보험: 결론 R46
    "AC8.": (12, 20),    # 리스: 결론 R21
}

# 각 시트별 clear 대상 column 범위 (헤더 column 보존)
_DATA_COLS = "CDEFGHIJKLMNOPQ"

# 보호 키워드 (footer·합계·소제목 보존)
_PROTECT_KEYWORDS = ("합계","소계","계 :","Total","total","해당없음","결론","감사인 의견","구분")


def _clear_data_rows(wb):
    """V1 template의 전년도 예시 데이터를 비움. 헤더·서식·병합·footer·결론 보존."""
    # AC0 — sub-section별 data row만 (header·절차·결론 텍스트 절대 건드리지 않음)
    ac0 = next((wb[s] for s in wb.sheetnames if s.startswith("AC0.")), None)
    if ac0 is not None:
        for start, end in _AC0_SUBSECTION_RANGES:
            for r in range(start, min(end, ac0.max_row) + 1):
                for col_letter in _DATA_COLS:
                    _try_clear(ac0, col_letter, r)
    # AC1~AC8 — 데이터 영역 전체 clear
    for prefix, (start, end) in _DATA_REGION.items():
        sheet_name = next((s for s in wb.sheetnames if s.startswith(prefix)), None)
        if sheet_name is None:
            continue
        ws = wb[sheet_name]
        for r in range(start, min(end, ws.max_row) + 1):
            for col_letter in _DATA_COLS:
                _try_clear(ws, col_letter, r)


def _try_clear(ws, col: str, row: int):
    try:
        cell = ws[f"{col}{row}"]
        if isinstance(cell, MergedCell):
            return
        val = cell.value
        if val is None:
            return
        if isinstance(val, str) and any(k in val for k in _PROTECT_KEYWORDS):
            return
        cell.value = None
    except Exception:
        pass
