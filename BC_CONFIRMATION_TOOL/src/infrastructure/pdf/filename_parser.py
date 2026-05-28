import re
from pathlib import Path

ONLINE_RE = re.compile(r"^전자_\[(BC-\d+)\]_[^_]+_\[[\d-]+\]_(.+?)_\[")
POSTAL_RE = re.compile(r"^(BC-\d+)_(.+)\.pdf$", re.IGNORECASE)

def parse_filename(name: str) -> dict:
    """
    Parse bank confirmation PDF filename to extract BC number, bank name, and channel.

    Args:
        name: PDF filename

    Returns:
        dict with keys:
            - bc_no: "BC-X" or None
            - bank_raw: bank name (last component for postal) or None
            - channel: "online", "postal", or None
    """
    stem = Path(name).name

    # Try online format: "전자_[BC-10]_회사명_[사업자번호]_은행명_[날짜].pdf"
    m = ONLINE_RE.match(stem)
    if m:
        return {
            "bc_no": m.group(1),
            "bank_raw": m.group(2).strip(),
            "channel": "online"
        }

    # Try postal format: "BC-25_은행명.pdf" or "BC-25_회사명_은행명.pdf"
    m = POSTAL_RE.match(stem)
    if m:
        bc = m.group(1)
        rest = m.group(2).strip()
        # "회사명_은행명" 형태일 경우 회사명 prefix 제거
        # 휴리스틱: "_" 분리 시 첫 토큰이 회사 추정 → 마지막만 남김
        parts = rest.split("_")
        bank = parts[-1] if len(parts) > 1 else rest
        return {
            "bc_no": bc,
            "bank_raw": bank.strip(),
            "channel": "postal"
        }

    # Unknown format
    return {
        "bc_no": None,
        "bank_raw": None,
        "channel": None
    }
