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
    return []  # AC3·AC7·AC8 후순위 (파서 미구현)


# 구현된 파서가 있는 AC. 그 외로 라우팅되면 수동검토 스텁을 emit 한다.
IMPLEMENTED_ACS = {"AC1", "AC1_DETAIL", "AC2", "AC4", "AC5", "AC6"}


import re

# 무거래 블록 마커 (공백 무관). 이런 블록은 스텁을 emit 하지 않는다.
_NO_TX = re.compile(r"해당\s*거래\s*없음|해당\s*사항\s*없음|해당\s*거래없음")
_MONEY = re.compile(r"\d{1,3}(?:,\d{3})+")          # 콤마 구분 금액
_NUM_TOKEN = re.compile(r"\d+")


def _has_real_data(block: str) -> bool:
    """수동검토 스텁을 띄울 만한 '실제 데이터'가 있는지 판정.
    무거래 블록(해당 거래 없음 등)은 False. 조회기준일·페이지번호(1/6)만 있는
    블록도 False. 콤마 금액 또는 숫자 토큰 2개 이상이면 True."""
    if _NO_TX.search(block):
        return False
    if _MONEY.search(block):
        return True
    return len(_NUM_TOKEN.findall(block)) >= 2


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
            store_ac = "AC1_DETAIL" if ac == "AC1_DETAIL" else ac
            conf = "low" if ocr_used else "high"
            try:
                recs = _dispatch(ac, block, bc_no, bank, route)
            except Exception as e:
                # BUG5: 파서 예외를 삼키지 말고 수동검토 스텁으로 가시화 (계속 진행)
                _persist(store_ac, {
                    "raw": block[:300],
                    "note": f"parser 예외 — 수동확인 ({type(e).__name__}: {e})",
                }, True, "low")
                continue
            if recs:
                for rec in recs:
                    _persist(store_ac, rec, False, conf)
            elif ac not in IMPLEMENTED_ACS and _has_real_data(block):
                # BUG4: 미구현 AC(AC3·AC7·AC8)인데 실제 데이터(숫자)가 있는 섹션 →
                # 감사인이 섹션 존재를 인지하도록 수동검토 스텁 1건 persist
                _persist(store_ac, {
                    "raw": block[:300],
                    "note": "parser 미구현 — 수동확인",
                }, True, "low")

    session.commit()
    return {"records": records_summary}
