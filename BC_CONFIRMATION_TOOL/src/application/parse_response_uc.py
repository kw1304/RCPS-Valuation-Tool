import json
from pathlib import Path
from sqlmodel import Session, select
from src.infrastructure.db.models import FileAsset, Counterparty, ExtractedRecord
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.filename_parser import parse_filename
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_deposit, parse_ac1_security_details
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2
from src.infrastructure.pdf.row_parsers.ac4_guarantee import parse_ac4
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5
from src.infrastructure.pdf.row_parsers.ac6_bills import parse_ac6
from src.infrastructure.pdf.row_parsers.fallback import fallback_parse
from src.domain.party_normalize import PartyNormalizer

ROOT = Path(__file__).resolve().parents[2]


def _dispatch(ac: str, block: str, bc_no: str, bank: str, route: dict):
    direction = route.get("direction", "received")
    if ac == "AC1":
        return parse_ac1_deposit(block, bc_no=bc_no, bank=bank)
    if ac == "AC1_DETAIL":
        return parse_ac1_security_details(block, bc_no=bc_no, bank=bank)
    if ac == "AC2":
        return parse_ac2(block, bc_no=bc_no, bank=bank)
    if ac == "AC4":
        return parse_ac4(block, bc_no=bc_no, bank=bank, direction=direction)
    if ac == "AC5":
        return parse_ac5(block, bc_no=bc_no, bank=bank, direction=direction)
    if ac == "AC6":
        return parse_ac6(block, bc_no=bc_no, bank=bank, direction=direction, sub=route.get("sub"))
    return []  # AC3·AC7·AC8 후순위


def parse_responses(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    profile = FormProfile.load()
    files = session.exec(
        select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.kind == "response")
    ).all()
    cps = {(c.canonical_name, c.branch): c for c in session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ).all()}
    records_summary = []

    for f in files:
        meta = parse_filename(f.original_name)
        bc_no = meta.get("bc_no") or ""
        bank_raw = meta.get("bank_raw") or ""
        np = norm.normalize(bank_raw) if bank_raw else None
        bank = np.canonical if np else bank_raw
        ext = extract_text_and_tables(Path(f.stored_path))
        text = ext["text"]
        # 스캔 PDF (텍스트 거의 없음) → OCR, 신뢰도 하향
        ocr_used = len(text.strip()) < 80
        if ocr_used:
            text = ocr_pdf(Path(f.stored_path))["text"]
        cp = cps.get((np.canonical, np.branch)) if np else None
        if cp:
            cp.response_arrived = True
            session.add(cp)

        family = identify_form(text)

        def _persist(ac, payload_obj, manual, confidence):
            payload = json.dumps(payload_obj, default=str, ensure_ascii=False) \
                if isinstance(payload_obj, dict) else payload_obj.model_dump_json()
            er = ExtractedRecord(
                project_id=project_id, counterparty_id=cp.id if cp else 0,
                ac_section=ac, payload_json=payload, confidence=confidence,
                source_file=f.original_name, needs_manual_review=manual,
                form_family=family,
            )
            session.add(er)
            session.flush()
            records_summary.append({"section": ac, "bc_no": bc_no, "bank": bank,
                                    "confidence": confidence, "needs_manual_review": manual,
                                    "payload": json.loads(payload)})

        if family == "unknown":
            for rec in fallback_parse(text, bc_no=bc_no, bank=bank):
                _persist(rec["ac_section"], rec["payload"], True, "low")
            continue

        blocks = split_sections(text)
        for section_no, block in blocks.items():
            route = profile.route(family, section_no)
            if not route:
                continue
            ac = route["ac"]
            try:
                recs = _dispatch(ac, block, bc_no, bank, route)
            except Exception:
                recs = []
            store_ac = "AC1_DETAIL" if ac == "AC1_DETAIL" else ac
            conf = "low" if ocr_used else "high"
            for rec in recs:
                _persist(store_ac, rec, False, conf)

    session.commit()
    return {"records": records_summary}
