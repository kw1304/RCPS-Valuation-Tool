"""회신서 텍스트 → 양식 패밀리 식별.

번호 섹션 헤더("N. ...다음과 같습니다")의 첫 헤더 문구로 양식 구분.
헤더 0개(우편 OCR) → "unknown".
"""
import re
from typing import Literal

FormFamily = Literal["bank", "securities", "insurance", "surety", "unknown"]

_HEADER = re.compile(r"^\s*(\d{1,2})\.\s*(.{6,90}?)(?:습니다|입니다)")


def _section_headers(text: str) -> list[tuple[int, str]]:
    out = []
    for ln in text.splitlines():
        m = _HEADER.match(ln.strip())
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
    return out


def identify_form(text: str) -> FormFamily:
    headers = _section_headers(text)
    if not headers:
        return "unknown"
    first = headers[0][1]
    if "의무" in first and "보증" in first:
        return "surety"
    if "보험거래" in first:
        return "insurance"
    if "보유하고 있는" in first:
        return "securities"
    if "금융상품" in first:
        return "bank"
    return "unknown"
