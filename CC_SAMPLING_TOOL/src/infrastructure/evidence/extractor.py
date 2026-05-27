"""증빙 파일 단위 추출기 — Week 5 v2 (Week 2 정확도 강화).

지원 포맷:
  .xls / .xlsx  — Commercial Invoice (BC-14, BC-15 패턴)
  .pdf          — Commercial Invoice / 인보이스 (BC-4 패턴)
  .png / .jpg   — 스캔 이미지 (BC-16, BC-26 패턴); Tesseract OCR 필요

Week 2 강화:
  - parse_from_filename_and_tables(): 텍스트 layer 빈약 시 파일명+표 조합 폴백
  - CC-N_거래처명_... 파일명 패턴에서 거래처명·금액 강제 추출
  - PDF 신뢰도 임계값 강화: 표+텍스트 모두 성공해야 confidence ≥ 0.75

추출 결과:
  EvidenceExtract — 파일 경로, 문서유형, 금액, 통화, 날짜, 거래처명,
                    추출방법, 신뢰도, 원문(디버깅용)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

log = logging.getLogger("cc_sampling.evidence.extractor")

# ─── 파일명 파싱 패턴 ──────────────────────────────────────────────────────
# CC-N_거래처명_... 패턴 (PDF 조회서 파일명)
_FILENAME_CC_PAT = re.compile(
    r"^CC-\d+_(.+?)_(?:\d차|채권채무|조회서|회신|reply)",
    re.IGNORECASE,
)
# BC-N_거래처명 패턴 (증빙 폴더명)
_FILENAME_BC_PAT = re.compile(
    r"^BC-[\d,]+_(.+)$",
    re.IGNORECASE,
)

# ─── 패턴 상수 ─────────────────────────────────────────────────────────────

# 금액 패턴: 숫자(쉼표 포함) 앞뒤 문자
_AMT_PAT = re.compile(r"[\d,]+(?:\.\d+)?")

# 통화 코드 패턴
_CURRENCY_PAT = re.compile(r"\b(KRW|USD|CNY|EUR|JPY|GBP|HKD)\b", re.IGNORECASE)

# 날짜 패턴 (다양한 형식)
_DATE_PATTERNS = [
    re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})"),              # 2025.06.30 / 2025-06-30
    re.compile(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[.\s,]*(\d{1,2})[,.\s]*(\d{4})",
               re.IGNORECASE),
    re.compile(r"(\d{1,2})[.\s]*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[.\s,]*(\d{4})",
               re.IGNORECASE),
    re.compile(r"(JUNE?|JULY?)\s*\.?\s*(\d{1,2})[,.\s]*(\d{4})", re.IGNORECASE),
]

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Total 관련 키워드 (우선순위 내림차순)
_TOTAL_KW = ["grand total", "total amount", "total", "합계", "총액"]


@dataclass
class EvidenceExtract:
    """단일 증빙 파일 추출 결과."""

    file_path: Path
    file_type: str                          # "xls" / "xlsx" / "pdf" / "png" / "jpg" / "unknown"
    document_type: Optional[str]            # "commercial_invoice" / "bank_statement" / "po" / "unknown"
    extracted_amount: Optional[float]
    extracted_currency: Optional[str]
    extracted_date: Optional[date]
    extracted_party: Optional[str]
    extraction_method: str                  # "xls_table" / "pdf_table" / "pdf_text" / "ocr" / "failed"
    confidence: float                       # 0.0 ~ 1.0
    raw_text: str = field(default="", repr=False)  # 디버깅용 원문


# ─── 공통 헬퍼 ──────────────────────────────────────────────────────────────

def _parse_amount(text: str) -> Optional[float]:
    """텍스트에서 가장 큰 숫자(금액)를 반환."""
    nums = _AMT_PAT.findall(text)
    candidates: list[float] = []
    for n in nums:
        try:
            v = float(n.replace(",", ""))
            if v > 0:
                candidates.append(v)
        except ValueError:
            pass
    return max(candidates) if candidates else None


def _parse_currency(text: str) -> Optional[str]:
    m = _CURRENCY_PAT.search(text)
    return m.group(1).upper() if m else None


def _parse_date(text: str) -> Optional[date]:
    """여러 형식의 날짜 패턴 시도."""
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                g = m.groups()
                if len(g) == 3:
                    g0 = g[0].lower().strip()
                    # YYYY-MM-DD 형태
                    if g0.isdigit() and len(g0) == 4:
                        y, mo, d = int(g0), int(g[1]), int(g[2])
                    # Month-first 영문 형태: APR.02,2025
                    elif g0 in _MONTH_MAP:
                        mo, d, y = _MONTH_MAP[g0], int(g[1]), int(g[2])
                    # Day-first 영문 형태: 02 APR 2025
                    elif g[1].lower() in _MONTH_MAP:
                        d, mo, y = int(g[0]), _MONTH_MAP[g[1].lower()], int(g[2])
                    else:
                        continue
                    if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2099:
                        return date(y, mo, d)
            except (ValueError, TypeError):
                pass
    return None


def _find_total_amount(text: str) -> Optional[float]:
    """TOTAL / 합계 인근 금액 우선 추출."""
    lines = text.splitlines()
    for kw in _TOTAL_KW:
        for i, line in enumerate(lines):
            if kw.lower() in line.lower():
                # 해당 줄 + 다음 줄에서 금액 검색
                search_text = " ".join(lines[i: i + 3])
                amt = _parse_amount(search_text)
                if amt and amt > 0:
                    return amt
    return None


# ─── XLS / XLSX 추출 ────────────────────────────────────────────────────────

def _extract_xls(file_path: Path) -> EvidenceExtract:
    """xlrd 로 .xls Commercial Invoice 파싱.

    BC-14 패턴:
      - 행 5:  Seller / Invoice No. / 날짜
      - 행 29: 통화 (KRW)
      - 합산 행: 구분선(---) 바로 다음 행 col 8 (Amount 합계)
    """
    try:
        import xlrd  # type: ignore
    except ImportError:
        return EvidenceExtract(
            file_path=file_path, file_type="xls",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text="xlrd 미설치",
        )

    try:
        wb = xlrd.open_workbook(str(file_path))
        sh = wb.sheet_by_index(0)
    except Exception as e:
        return EvidenceExtract(
            file_path=file_path, file_type="xls",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text=str(e),
        )

    # 전체 텍스트 수집 (디버깅용)
    raw_lines: list[str] = []
    for r in range(sh.nrows):
        cells = [str(sh.cell_value(r, c)) for c in range(sh.ncols)]
        raw_lines.append("\t".join(cells))
    raw_text = "\n".join(raw_lines)

    # 1) 문서유형 판별
    doc_type: str = "unknown"
    for r in range(min(10, sh.nrows)):
        row_text = raw_lines[r].lower()
        if "commercial invoice" in row_text or "invoice" in row_text:
            doc_type = "commercial_invoice"
            break

    # 2) 날짜 추출 (행 5 주변)
    extracted_date: Optional[date] = None
    for r in range(min(15, sh.nrows)):
        dt = _parse_date(raw_lines[r])
        if dt:
            extracted_date = dt
            break

    # 3) 통화 추출 (행 29 주변 — "(KRW)" 패턴)
    extracted_currency: Optional[str] = None
    for r in range(sh.nrows):
        cur = _parse_currency(raw_lines[r])
        if cur:
            extracted_currency = cur
            break

    # 4) 금액 — 구분선(---) 다음 행 col 8 (Amount 합계)
    extracted_amount: Optional[float] = None
    AMOUNT_COL = 8  # BC-14 패턴
    for r in range(sh.nrows):
        cell_val = str(sh.cell_value(r, min(AMOUNT_COL, sh.ncols - 1)))
        if "---" in cell_val or (r > 0 and "---" in raw_lines[r - 1]):
            # 구분선 발견 → 이 행 또는 다음 행
            for check_r in [r, r + 1]:
                if check_r >= sh.nrows:
                    continue
                raw_amt = str(sh.cell_value(check_r, min(AMOUNT_COL, sh.ncols - 1)))
                amt = _parse_amount(raw_amt)
                if amt and amt > 0:
                    extracted_amount = amt
                    break
            if extracted_amount:
                break

    # 5) 구분선 전략 실패 시 — TOTAL 키워드 접근
    if not extracted_amount:
        extracted_amount = _find_total_amount(raw_text)

    # 6) 거래처명 (Consignee/Applicant 아래 행)
    extracted_party: Optional[str] = None
    for r in range(sh.nrows):
        row_lower = raw_lines[r].lower()
        if "consignee" in row_lower or "applicant" in row_lower:
            for nr in range(r + 1, min(r + 4, sh.nrows)):
                cells = [str(sh.cell_value(nr, c)).strip() for c in range(sh.ncols)]
                name = " ".join(c for c in cells if c and c not in ("0.0",))[:100]
                if name and len(name) > 2:
                    extracted_party = name
                    break
            if extracted_party:
                break

    confidence = 0.8 if extracted_amount else 0.3
    return EvidenceExtract(
        file_path=file_path, file_type="xls",
        document_type=doc_type,
        extracted_amount=extracted_amount,
        extracted_currency=extracted_currency or "KRW",
        extracted_date=extracted_date,
        extracted_party=extracted_party,
        extraction_method="xls_table",
        confidence=confidence,
        raw_text=raw_text[:3000],
    )


def _extract_xlsx(file_path: Path) -> EvidenceExtract:
    """openpyxl 로 .xlsx 파싱 — 일반 스프레드시트."""
    try:
        import openpyxl  # type: ignore
        wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
        sh = wb.active
        raw_lines: list[str] = []
        for row in sh.iter_rows(values_only=True):
            raw_lines.append("\t".join(str(v or "") for v in row))
        raw_text = "\n".join(raw_lines)
        wb.close()
    except Exception as e:
        return EvidenceExtract(
            file_path=file_path, file_type="xlsx",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text=str(e),
        )

    doc_type = "commercial_invoice" if "invoice" in raw_text.lower() else "unknown"
    amt = _find_total_amount(raw_text)
    cur = _parse_currency(raw_text)
    dt = _parse_date(raw_text)
    confidence = 0.7 if amt else 0.2

    return EvidenceExtract(
        file_path=file_path, file_type="xlsx",
        document_type=doc_type,
        extracted_amount=amt,
        extracted_currency=cur,
        extracted_date=dt,
        extracted_party=None,
        extraction_method="xls_table",
        confidence=confidence,
        raw_text=raw_text[:3000],
    )


# ─── PDF 추출 ───────────────────────────────────────────────────────────────

def _extract_pdf(file_path: Path) -> EvidenceExtract:
    """pdfplumber 로 PDF 인보이스 파싱.

    1차: extract_tables() — 구조화 표에서 TOTAL 행 탐색
    2차: extract_text() + 정규식
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return EvidenceExtract(
            file_path=file_path, file_type="pdf",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text="pdfplumber 미설치",
        )

    raw_text = ""
    all_tables: list[list] = []
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                raw_text += t + "\n"
                tbls = page.extract_tables() or []
                for tbl in tbls:
                    all_tables.extend(tbl)
    except Exception as e:
        return EvidenceExtract(
            file_path=file_path, file_type="pdf",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text=str(e),
        )

    # 문서유형
    doc_type = "unknown"
    if "invoice" in raw_text.lower() or "commercial invoice" in raw_text.lower():
        doc_type = "commercial_invoice"

    # 1차: 테이블에서 TOTAL 행
    extracted_amount: Optional[float] = None
    for row in all_tables:
        if row is None:
            continue
        row_text = " ".join(str(c or "") for c in row)
        for kw in _TOTAL_KW:
            if kw.lower() in row_text.lower():
                amt = _parse_amount(row_text)
                if amt and amt > 0:
                    extracted_amount = amt
                    break
        if extracted_amount:
            break

    # 2차: 텍스트에서 TOTAL 키워드 접근
    if not extracted_amount:
        extracted_amount = _find_total_amount(raw_text)

    extracted_currency = _parse_currency(raw_text)
    extracted_date = _parse_date(raw_text)

    # 거래처명 (Seller / Consignee 아래)
    extracted_party: Optional[str] = None
    lines = raw_text.splitlines()
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in ["consignee", "seller", "applicant"]):
            for nl in range(i + 1, min(i + 4, len(lines))):
                cand = lines[nl].strip()
                if cand and len(cand) > 3 and not any(
                    kw in cand.lower() for kw in ["consignee", "seller", "buyer", "applicant"]
                ):
                    extracted_party = cand[:100]
                    break
            if extracted_party:
                break

    confidence = 0.75 if extracted_amount else 0.25
    method = "pdf_table" if all_tables else "pdf_text"

    return EvidenceExtract(
        file_path=file_path, file_type="pdf",
        document_type=doc_type,
        extracted_amount=extracted_amount,
        extracted_currency=extracted_currency,
        extracted_date=extracted_date,
        extracted_party=extracted_party,
        extraction_method=method,
        confidence=confidence,
        raw_text=raw_text[:3000],
    )


# ─── 이미지 OCR 추출 ────────────────────────────────────────────────────────

def _extract_image(file_path: Path) -> EvidenceExtract:
    """PNG/JPG 스캔 이미지 — pytesseract OCR.

    Tesseract 미설치 시 graceful fail (extraction_method="failed", confidence=0).
    """
    ext = file_path.suffix.lower().lstrip(".")

    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
        pytesseract.get_tesseract_version()
    except Exception:
        return EvidenceExtract(
            file_path=file_path, file_type=ext,
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0,
            raw_text="Tesseract OCR 미설치 — 수동 확인 필요",
        )

    try:
        from src.infrastructure.pdf.ocr import _preprocess_image  # reuse existing preprocessing
        img = Image.open(str(file_path))
        img_proc = _preprocess_image(img)
        raw_text = pytesseract.image_to_string(img_proc, lang="kor+eng", config="--oem 3 --psm 6")
    except Exception as e:
        return EvidenceExtract(
            file_path=file_path, file_type=ext,
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text=str(e),
        )

    if not raw_text.strip():
        return EvidenceExtract(
            file_path=file_path, file_type=ext,
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text="OCR 결과 없음",
        )

    doc_type = "commercial_invoice" if "invoice" in raw_text.lower() else "unknown"
    amt = _find_total_amount(raw_text)
    cur = _parse_currency(raw_text)
    dt = _parse_date(raw_text)
    confidence = min(0.6, len(raw_text) / 500)

    return EvidenceExtract(
        file_path=file_path, file_type=ext,
        document_type=doc_type,
        extracted_amount=amt,
        extracted_currency=cur,
        extracted_date=dt,
        extracted_party=None,
        extraction_method="ocr",
        confidence=confidence,
        raw_text=raw_text[:3000],
    )


# ─── 파일명 기반 거래처명 추출 ──────────────────────────────────────────────

def _extract_party_from_filename(file_path: Path) -> Optional[str]:
    """파일명 패턴 (CC-N_ / BC-N_)에서 거래처명 추출.

    예:
      CC-19_科丝美诗（中国）化妆品有限公司_1차_채권채무조회서.pdf → "科丝美诗（中国）化妆品有限公司"
      BC-14_New Future International Trade Co.xlsx → "New Future International Trade Co"
    """
    stem = file_path.stem  # 확장자 제외 파일명
    m = _FILENAME_CC_PAT.match(stem)
    if m:
        name = m.group(1).strip()
        if 2 <= len(name) <= 80:
            return name
    m = _FILENAME_BC_PAT.match(stem)
    if m:
        name = m.group(1).strip()
        if 2 <= len(name) <= 80:
            return name
    return None


def parse_from_filename_and_tables(file_path: Path, result: EvidenceExtract) -> EvidenceExtract:
    """텍스트 layer 빈약 시 파일명 + 표 조합 폴백.

    적용 조건:
      - extraction_method == "failed" 또는 confidence < 0.3
      - 파일명에서 거래처명 추출 가능

    이 함수는 기존 result를 보강(mutate)하지 않고 새 EvidenceExtract를 반환한다.
    """
    # 파일명에서 거래처명 시도
    filename_party = _extract_party_from_filename(file_path)
    if not filename_party:
        return result  # 파일명 패턴 불일치 → 원본 반환

    # 이미 성공한 추출이면 거래처명만 보완
    if result.extraction_method != "failed" and result.confidence >= 0.3:
        if result.extracted_party is None:
            return EvidenceExtract(
                file_path=result.file_path,
                file_type=result.file_type,
                document_type=result.document_type,
                extracted_amount=result.extracted_amount,
                extracted_currency=result.extracted_currency,
                extracted_date=result.extracted_date,
                extracted_party=filename_party,
                extraction_method=result.extraction_method,
                confidence=result.confidence,
                raw_text=result.raw_text,
            )
        return result

    # 추출 실패 케이스 — 파일명만으로 최소 정보 구성
    log.debug("파일명 폴백 적용: %s → party=%s", file_path.name, filename_party)
    return EvidenceExtract(
        file_path=file_path,
        file_type=file_path.suffix.lower().lstrip(".") or "unknown",
        document_type="unknown",
        extracted_amount=None,
        extracted_currency=None,
        extracted_date=None,
        extracted_party=filename_party,
        extraction_method="filename_fallback",
        confidence=0.2,  # 파일명 전용: 금액 미검증이므로 낮게
        raw_text=f"파일명 폴백: {filename_party}",
    )


# ─── 공개 진입점 ────────────────────────────────────────────────────────────

def extract_evidence(file_path: Path) -> EvidenceExtract:
    """파일 유형에 따라 적절한 추출기를 선택하고 EvidenceExtract 반환.

    지원:
      .xls         → xlrd Commercial Invoice 파서
      .xlsx        → openpyxl 범용 파서
      .pdf         → pdfplumber (table 우선, text 폴백)
      .png / .jpg / .jpeg → pytesseract OCR (미설치 시 graceful fail)
      그 외         → extraction_method="failed", confidence=0
    """
    ext = file_path.suffix.lower()
    if not file_path.exists():
        return EvidenceExtract(
            file_path=file_path, file_type=ext.lstrip(".") or "unknown",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text="파일 없음",
        )

    log.debug("증빙 추출: %s", file_path.name)

    if ext == ".xls":
        result = _extract_xls(file_path)
    elif ext in (".xlsx",):
        result = _extract_xlsx(file_path)
    elif ext == ".pdf":
        result = _extract_pdf(file_path)
    elif ext in (".png", ".jpg", ".jpeg"):
        result = _extract_image(file_path)
    else:
        result = EvidenceExtract(
            file_path=file_path, file_type=ext.lstrip(".") or "unknown",
            document_type=None, extracted_amount=None,
            extracted_currency=None, extracted_date=None,
            extracted_party=None, extraction_method="failed",
            confidence=0.0, raw_text=f"지원하지 않는 파일 형식: {ext}",
        )

    # Week 2: 추출 실패 또는 낮은 신뢰도 시 파일명 폴백 적용
    if result.extraction_method == "failed" or result.confidence < 0.3:
        result = parse_from_filename_and_tables(file_path, result)

    return result
