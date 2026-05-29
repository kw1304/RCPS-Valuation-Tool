import json
from pathlib import Path
from sqlmodel import Session, select
from src.infrastructure.db.models import FileAsset, Counterparty, ExtractedRecord
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.filename_parser import parse_filename
from src.infrastructure.pdf.section_classifier import classify_sections
from src.infrastructure.pdf.generic_parser import (
    parse_ac1_deposit, parse_ac1_security_details, parse_ac2_borrowing, parse_ac3_derivative,
    parse_ac4_guarantee, parse_ac5_collateral, parse_ac6_bills,
    parse_ac7_insurance, parse_ac8_general,
)
from src.domain.party_normalize import PartyNormalizer

ROOT = Path(__file__).resolve().parents[2]
PARSERS = {
    "AC1": parse_ac1_deposit, "AC2": parse_ac2_borrowing,
    "AC3": parse_ac3_derivative, "AC4": parse_ac4_guarantee,
    "AC5": parse_ac5_collateral, "AC6": parse_ac6_bills,
    "AC7": parse_ac7_insurance, "AC8": parse_ac8_general,
}


def parse_responses(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    files = session.exec(
        select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.kind == "response")
    ).all()
    cps = {(c.canonical_name, c.branch): c for c in session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ).all()}
    records_summary = []
    for f in files:
        meta = parse_filename(f.original_name)
        bc_no = meta.get("bc_no")
        bank_raw = meta.get("bank_raw") or ""
        np = norm.normalize(bank_raw) if bank_raw else None
        bank = np.canonical if np else bank_raw
        ext = extract_text_and_tables(Path(f.stored_path))
        text = ext["text"]
        if len(text.strip()) < 80:
            # 스캔 PDF (텍스트 거의 없음) → OCR
            ocr = ocr_pdf(Path(f.stored_path))
            text = ocr["text"]
            confidence = "low"
        else:
            confidence = "high"
        sections = classify_sections(text)
        cp = cps.get((np.canonical, np.branch)) if np else None
        if cp:
            cp.response_arrived = True
            session.add(cp)
        # AC1_DETAIL — 유가증권 종목별 상세명세 (전체 text에서 추출)
        try:
            detail_recs = parse_ac1_security_details(text, bc_no=bc_no or "", bank=bank or "")
        except Exception:
            detail_recs = []
        for rec in detail_recs:
            payload = rec.model_dump_json()
            er = ExtractedRecord(
                project_id=project_id,
                counterparty_id=cp.id if cp else 0,
                ac_section="AC1_DETAIL",
                payload_json=payload,
                confidence=confidence,
                source_file=f.original_name,
            )
            session.add(er)
            session.flush()
            records_summary.append({
                "section": "AC1_DETAIL", "bc_no": bc_no, "bank": bank,
                "confidence": confidence, "payload": json.loads(payload),
            })
        for ac, section_text in sections.items():
            parser = PARSERS[ac]
            try:
                recs = parser(section_text, bc_no=bc_no or "", bank=bank or "")
            except Exception:
                recs = []
            for rec in recs:
                payload = rec.model_dump_json()
                er = ExtractedRecord(
                    project_id=project_id,
                    counterparty_id=cp.id if cp else 0,
                    ac_section=ac,
                    payload_json=payload,
                    confidence=confidence,
                    source_file=f.original_name,
                )
                session.add(er)
                session.flush()
                records_summary.append({
                    "section": ac, "bc_no": bc_no, "bank": bank,
                    "confidence": confidence, "payload": json.loads(payload),
                })
    session.commit()
    return {"records": records_summary}
