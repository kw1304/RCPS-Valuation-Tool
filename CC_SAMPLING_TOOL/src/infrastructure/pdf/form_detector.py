"""PDF 양식 분류 — FormProfile 반환.

삼덕회계법인 조회서 표준 양식 2종 + 이메일 자유 양식 + OCR 필요 케이스 분류.

form_id:
  "samduk_kr_standard"  — 한국어 표준양식 (채권채무조회서 + 당사[/귀사[ 구조)
  "samduk_en_standard"  — 영문 표준양식  (Confirmation of Accounts / TO : ...)
  "email_freeform"      — 이메일 자유 형식 (From:/Subject: 등 이메일 헤더 포함)
  "ocr_required"        — 이미지 PDF (텍스트 < 100자)
  "unknown"             — 분류 불가
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FormProfile:
    form_id: str           # 양식 종류
    confidence: float      # 0.0~1.0 — 분류 신뢰도
    hints: list[str] = field(default_factory=list)  # 분류 근거 힌트 목록


# ── 분류용 패턴 ────────────────────────────────────────────────────────────────
_KR_KEYWORDS = [
    ("채권채무조회서",             2.0),
    (r"당사\[",                   1.5),  # "당사[..." — 리터럴 [ 이스케이프
    (r"귀사\[",                   1.5),  # "귀사[..." — 리터럴 [ 이스케이프
    ("확인통지",                   1.0),
    (r"받을\s*금액",               0.8),
    (r"지급할\s*금액",             0.8),
    ("계정과목",                   0.5),
    ("감사인명",                   0.5),
    ("발송금액",                   0.8),
    ("일치여부",                   0.8),
]

_EN_KEYWORDS = [
    ("Confirmation of Accounts", 2.0),
    (r"TO\s*:",                  1.5),
    ("Receivable",               0.5),
    ("Payable",                  0.5),
    ("Accounting Firm",          0.8),
    ("Our Amount",               0.8),
    ("Your Amount",              0.8),
    (r"as per\s+\d{4}",         0.5),
]

_EMAIL_KEYWORDS = [
    (r"^From\s*:",      2.0),
    (r"^To\s*:",        1.0),
    (r"^Subject\s*:",   1.5),
    (r"^Date\s*:",      0.5),
]

_THRESHOLD_KR = 4.0   # 이 점수 이상 → samduk_kr_standard
_THRESHOLD_EN = 3.5   # 이 점수 이상 → samduk_en_standard
_THRESHOLD_EMAIL = 2.5


def detect_form(
    text: str,
    tables: Optional[list] = None,
    file_meta: Optional[dict] = None,
) -> FormProfile:
    """텍스트 + 표 + 파일 메타 → FormProfile.

    Args:
        text:       ExtractResult.full_text
        tables:     pdfplumber extract_tables() 결과 (선택)
        file_meta:  {"filename": "...", "size_bytes": ...} (선택)
    """
    # ── OCR 필요 판정 ──────────────────────────────────────────────────────
    if len(text.strip()) < 100:
        hints = [f"텍스트 길이={len(text.strip())} < 100"]
        # 파일이 있지만 텍스트가 없는 경우 → 이미지 PDF
        return FormProfile(
            form_id="ocr_required",
            confidence=0.95,
            hints=hints,
        )

    hints_kr: list[str] = []
    hints_en: list[str] = []
    hints_email: list[str] = []

    score_kr = 0.0
    score_en = 0.0
    score_email = 0.0

    # ── 한국어 표준 채점 ───────────────────────────────────────────────────
    for pattern, weight in _KR_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            score_kr += weight
            hints_kr.append(pattern)

    # ── 영문 표준 채점 ─────────────────────────────────────────────────────
    for pattern, weight in _EN_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            score_en += weight
            hints_en.append(pattern)

    # ── 이메일 자유 양식 채점 ──────────────────────────────────────────────
    for pattern, weight in _EMAIL_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            score_email += weight
            hints_email.append(pattern)

    # ── 표 기반 보정 ───────────────────────────────────────────────────────
    if tables:
        for table in tables:
            if not table:
                continue
            header_joined = " ".join(
                str(c or "") for row in table[:1] for c in row
            ).lower()
            if "계정과목" in header_joined and "일치여부" in header_joined:
                score_kr += 1.5
                hints_kr.append("표헤더: 계정과목+일치여부")
            elif "account" in header_joined and "amount" in header_joined:
                score_en += 1.0
                hints_en.append("표헤더: account+amount")

    # ── 파일명 힌트 보정 ───────────────────────────────────────────────────
    if file_meta:
        fname = (file_meta.get("filename") or "").lower()
        if any(kw in fname for kw in ["cc-", "채권", "채무", "조회서"]):
            score_kr += 0.5
            hints_kr.append(f"파일명 힌트: {fname[:40]}")

    # ── 최종 분류 ──────────────────────────────────────────────────────────
    max_score = max(score_kr, score_en, score_email)

    if score_kr >= _THRESHOLD_KR and score_kr >= score_en:
        conf = min(1.0, score_kr / 8.0)
        return FormProfile(form_id="samduk_kr_standard", confidence=round(conf, 3), hints=hints_kr)

    if score_en >= _THRESHOLD_EN and score_en > score_kr:
        conf = min(1.0, score_en / 7.0)
        return FormProfile(form_id="samduk_en_standard", confidence=round(conf, 3), hints=hints_en)

    if score_email >= _THRESHOLD_EMAIL and score_email > score_kr and score_email > score_en:
        conf = min(1.0, score_email / 5.0)
        return FormProfile(form_id="email_freeform", confidence=round(conf, 3), hints=hints_email)

    # 점수는 있지만 임계값 미달 → 가장 높은 쪽으로 낮은 신뢰도 반환
    if max_score > 0:
        if score_kr >= score_en and score_kr >= score_email:
            conf = min(0.5, score_kr / 8.0)
            return FormProfile(form_id="samduk_kr_standard", confidence=round(conf, 3), hints=hints_kr)
        if score_en >= score_email:
            conf = min(0.5, score_en / 7.0)
            return FormProfile(form_id="samduk_en_standard", confidence=round(conf, 3), hints=hints_en)

    return FormProfile(form_id="unknown", confidence=0.0, hints=[])
