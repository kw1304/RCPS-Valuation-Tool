import json
from pathlib import Path
from sqlmodel import Session, select
from src.infrastructure.db.models import FileAsset, Counterparty, ExtractedRecord
from src.infrastructure.pdf.extractor import extract_text_and_tables, extract_rows
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
from src.infrastructure.pdf.row_parsers.ac3_derivative import parse_ac3
from src.infrastructure.pdf.row_parsers.ac7_insurance import parse_ac7
from src.infrastructure.pdf.row_parsers.fallback import fallback_parse
from src.domain.party_normalize import PartyNormalizer
from src.domain.record_dedup import dedup_records

ROOT = Path(__file__).resolve().parents[2]


def _dispatch(ac: str, block: str, bc_no: str, bank: str, route: dict | None = None):
    route = route or {}
    direction = route.get("direction", "received")
    if ac == "AC1":
        return parse_ac1_deposit(block, bc_no=bc_no, bank=bank)
    if ac == "AC1_DETAIL":
        return parse_ac1_security_details(block, bc_no=bc_no, bank=bank)
    if ac == "AC2":
        return parse_ac2(block, bc_no=bc_no, bank=bank)
    if ac == "AC3":
        return parse_ac3(block, bc_no=bc_no, bank=bank)
    if ac == "AC4":
        return parse_ac4(block, bc_no=bc_no, bank=bank, direction=direction)
    if ac == "AC5":
        return parse_ac5(block, bc_no=bc_no, bank=bank, direction=direction)
    if ac == "AC6":
        return parse_ac6(block, bc_no=bc_no, bank=bank, direction=direction, sub=route.get("sub"))
    if ac == "AC7":
        return parse_ac7(block, bc_no=bc_no, bank=bank)
    return []  # AC8 후순위 (라우팅 섹션 없음, 파서 미구현)


# 구현된 파서가 있는 AC. 그 외로 라우팅되면 수동검토 스텁을 emit 한다.
IMPLEMENTED_ACS = {"AC1", "AC1_DETAIL", "AC2", "AC3", "AC4", "AC5", "AC6", "AC7"}


import re

# 무거래 블록 마커 (공백 무관). 이런 블록은 스텁을 emit 하지 않는다.
_NO_TX = re.compile(r"해당\s*거래\s*없음|해당\s*사항\s*없음|해당\s*거래없음")
_MONEY = re.compile(r"\d{1,3}(?:,\d{3})+")          # 콤마 구분 금액
_NUM_TOKEN = re.compile(r"\d+")


# --- 내용기반 라우팅 (미매핑 섹션 복구) -----------------------------------
# 거래내역 첨부 마커: 이 문구 이후는 transaction log → 담보/어음 파싱 대상에서 제외.
_TX_ATTACH = re.compile(r"거래\s*내역을?\s*첨부")
# 거래내역(transaction log) 신호 토큰: 이 섹션은 무시해야 함.
_TX_LOG_SIGNAL = ("거래내역", "입고", "출고", "매도", "매수", "잔고", "첨부",
                  "정산금액", "예수금")
# 담보(collateral) 신호.
_COLLATERAL_SIGNAL = ("담보", "감정금액", "설정금액", "근저당", "질권", "담보제공",
                      "감정 금액", "설정 금액")
# 어음/수표 신호.
_BILLS_SIGNAL = ("어음", "수표", "당좌")

# --- AC6 거래·결제 명세 로그 억제 ----------------------------------------
# 당좌거래명세(§10)·전자어음 결제명세(§7)는 확인 대상 어음·수표 보유가 아니라
# 거래/결제 로그다. 수백건으로 폭증하므로 AC6 레코드를 만들지 않는다.
# (당좌예금 잔액은 §1 AC1에 이미 집계됨.)
#
# 진짜 보유(§8 담보·견질 보관 어음 등)는 어음금액/만기일/발행일 + 거래처가 있는
# 소수의 holding 행이며, 입금/지급·적요·일련번호 enumeration 구조가 아니다.
_LOG_HEADER = re.compile(r"거래\s*명세|당좌\s*거래|결제\s*명세")
# 일별 거래원장: 입금금액 + 지급금액 (현금흐름 컬럼) 동시 등장.
_FLOW_COLS = (re.compile(r"입\s*금\s*금\s*액"), re.compile(r"지\s*급\s*금\s*액"))
# 적요(거래 메모) 컬럼.
_JEOKYO = re.compile(r"적\s*요")
# 전자어음 일련번호 (per-serial enumeration) — 결제/발행명세 로그 마커.
_SERIAL = re.compile(r"\d{20,}")  # 00320251031000014866 등 20자리+ 일련번호
# holding 신호: 보유 어음·수표 표의 금액·만기·발행 컬럼.
_HOLDING_COLS = (re.compile(r"어음\s*금액"), re.compile(r"만\s*기\s*일"),
                 re.compile(r"발\s*행\s*일"))


def _is_ac6_transaction_log(block: str) -> bool:
    """AC6로 라우팅된 블록이 거래/결제 명세 로그인지 판정.

    True → 보유가 아니라 로그이므로 억제(레코드 0건).
    판정 신호(보수적, 하나라도 강하게 맞으면 로그):
      1) 헤더에 거래명세/당좌거래/결제명세.
      2) 입금금액 AND 지급금액 (일별 거래원장 현금흐름 컬럼).
      3) 일련번호(20자리+) per-serial enumeration 행이 다수(>=20) — 결제/발행명세.
    단, 보유(holding) 컬럼(어음금액/만기일/발행일)이 주도하고 로그 신호가 약하면
    로그로 보지 않는다(§8 등 진짜 보유 보존)."""
    head = "\n".join(block.splitlines()[:3])

    # 1) 헤더 명세 마커
    if _LOG_HEADER.search(head):
        return True
    # 2) 입금/지급 현금흐름 컬럼 동시 등장 (당좌거래명세 §10)
    if all(p.search(head) for p in _FLOW_COLS):
        return True
    if all(p.search(head) for p in _FLOW_COLS[:1]) and _JEOKYO.search(head) \
            and _FLOW_COLS[1].search(head):
        return True
    # 3) per-serial 일련번호 enumeration 다수 (전자어음 결제명세 §7)
    serial_rows = sum(1 for ln in block.splitlines() if _SERIAL.search(ln))
    if serial_rows >= 20:
        # holding 컬럼이 헤더에 있고 serial 행이 적으면 보유로 간주 — 여기선 다수라 로그.
        return True
    return False


def _collateral_subblock(block: str) -> str:
    """담보 sub-block = '거래내역을 첨부' 마커 이전 텍스트.

    유가증권 회신서의 비표준 섹션은 [담보 표] + [거래내역 첨부] 가 한 섹션에
    섞여 들어온다. 거래내역(transaction log)의 큰 금액(현금매도 10억 등)을 담보로
    오인하지 않도록, 담보 판정·파싱은 마커 이전 부분만 대상으로 한다."""
    m = _TX_ATTACH.search(block)
    return block[: m.start()] if m else block


def route_or_classify(family: str, section_no: int, block: str) -> dict | None:
    """프로파일 라우팅 우선, 없으면 내용기반 분류.

    반환: {ac, direction?, sub?, block?, content_routed?} 또는 None.
      - 매핑된 섹션: FormProfile.route 결과 그대로.
      - 미매핑 + 비자명(real 금액) 섹션: 담보 sub-block(거래내역 마커 이전) 내용으로 분류.
          담보 신호 ∧ ¬거래내역 신호 → AC5(provided), block=담보 sub-block.
          어음 신호 ∧ ¬거래내역 신호 → AC6.
          그 외(거래내역/미상) → None (조용히 버리지 않되, 잘못 라우팅도 안 함).
    content_routed=True 인 record 는 비표준 섹션 출신이므로 수동검토 플래그를 단다."""
    route = _profile_singleton().route(family, section_no)
    if route:
        # AC6 거래/결제 명세 로그(§10 당좌거래명세·§7 전자어음 결제명세)는 억제.
        # 보유가 아니라 로그 → 레코드 폭증 방지 (잔액은 AC1 §1에 집계됨).
        if route.get("ac") == "AC6" and _is_ac6_transaction_log(block):
            return None
        return route

    sub = _collateral_subblock(block)
    if not _has_real_data(sub):
        return None  # 담보부 무거래(해당 거래 없음) 또는 금액 없음 → 무시
    has_tx_log = any(k in sub for k in _TX_LOG_SIGNAL)
    if has_tx_log:
        return None  # 거래내역 신호가 담보부에 섞여 있으면 안전하게 무시
    if any(k in sub for k in _COLLATERAL_SIGNAL):
        return {"ac": "AC5", "direction": "provided",
                "block": sub, "content_routed": True}
    if any(k in sub for k in _BILLS_SIGNAL):
        if _is_ac6_transaction_log(sub):
            return None
        return {"ac": "AC6", "block": sub, "content_routed": True}
    return None


_PROFILE_CACHE: FormProfile | None = None


def _profile_singleton() -> FormProfile:
    global _PROFILE_CACHE
    if _PROFILE_CACHE is None:
        _PROFILE_CACHE = FormProfile.load()
    return _PROFILE_CACHE


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
    # 이중계상 방지: 개별 회신본(tagged) + 합본 스캔(untagged, 파일명 메타 없음)이 함께
    # 들어오면 같은 holding 이 두 번 persist 된다. 모든 후보를 먼저 모은 뒤 dedup_records
    # 로 한 번에 처리한다 — tagged 는 항상 보존(동일 금액의 다른 은행 행 병합 금지),
    # untagged 결합본 중복만 제거.
    pending: list[dict] = []  # 수집 버퍼: {ac, payload_obj, manual, confidence, bc_no, bank, cp, family}

    for f in files:
        meta = parse_filename(f.original_name)
        bc_no = meta.get("bc_no") or ""
        bank_raw = meta.get("bank_raw") or ""
        np = norm.normalize(bank_raw) if bank_raw else None
        bank = np.canonical if np else bank_raw
        # 좌표 기반 행 재구성: 무테 표의 줄바꿈 금액을 라벨 행과 재결합한다.
        text = extract_rows(Path(f.stored_path))
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
            # 즉시 저장하지 않고 버퍼에 모은다. dedup_records 는 전체 집합을 봐야
            # tagged/untagged 판단이 정확하다(파일 처리 순서 무관).
            payload_dict = payload_obj if isinstance(payload_obj, dict) \
                else payload_obj.model_dump()
            pending.append({
                "ac_section": ac, "payload": payload_dict, "payload_obj": payload_obj,
                "manual": manual, "confidence": confidence,
                "bc_no": bc_no, "bank": bank, "cp": cp, "family": family,
                "source_file": f.original_name,
            })

        if family == "unknown":
            for rec in fallback_parse(text, bc_no=bc_no, bank=bank):
                _persist(rec["ac_section"], rec["payload"], True, "low")
            continue

        blocks = split_sections(text)
        for section_no, block in blocks.items():
            route = route_or_classify(family, section_no, block)
            if not route:
                continue
            ac = route["ac"]
            store_ac = "AC1_DETAIL" if ac == "AC1_DETAIL" else ac
            content_routed = route.get("content_routed", False)
            # 내용기반 라우팅 섹션은 담보 sub-block(거래내역 마커 이전)만 파싱한다.
            parse_block = route.get("block", block)
            conf = "low" if ocr_used else "high"
            try:
                recs = _dispatch(ac, parse_block, bc_no, bank, route)
            except Exception as e:
                # BUG5: 파서 예외를 삼키지 말고 수동검토 스텁으로 가시화 (계속 진행)
                _persist(store_ac, {
                    "raw": parse_block[:300],
                    "note": f"parser 예외 — 수동확인 ({type(e).__name__}: {e})",
                }, True, "low")
                continue
            if recs:
                # 비표준 섹션(content_routed) 출신은 감사인 확인용으로 수동검토 플래그.
                for rec in recs:
                    _persist(store_ac, rec, content_routed, conf)
            elif ac not in IMPLEMENTED_ACS and _has_real_data(block):
                # BUG4: 미구현 AC(AC3·AC7·AC8)인데 실제 데이터(숫자)가 있는 섹션 →
                # 감사인이 섹션 존재를 인지하도록 수동검토 스텁 1건 persist
                _persist(store_ac, {
                    "raw": block[:300],
                    "note": "parser 미구현 — 수동확인",
                }, True, "low")

    # dedup: tagged(개별 회신본) 보존, untagged(합본 스캔) 중복만 제거 → 그 뒤 persist.
    for rec in dedup_records(pending):
        payload_obj = rec["payload_obj"]
        cp = rec["cp"]
        payload = json.dumps(payload_obj, default=str, ensure_ascii=False) \
            if isinstance(payload_obj, dict) else payload_obj.model_dump_json()
        er = ExtractedRecord(
            project_id=project_id, counterparty_id=cp.id if cp else 0,
            ac_section=rec["ac_section"], payload_json=payload,
            confidence=rec["confidence"], source_file=rec["source_file"],
            needs_manual_review=rec["manual"], form_family=rec["family"],
        )
        session.add(er)
        session.flush()
        records_summary.append({"section": rec["ac_section"], "bc_no": rec["bc_no"],
                                "bank": rec["bank"], "confidence": rec["confidence"],
                                "needs_manual_review": rec["manual"],
                                "payload": json.loads(payload)})

    session.commit()
    return {"records": records_summary}
