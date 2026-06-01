import re
from pathlib import Path

ONLINE_RE = re.compile(r"^전자_\[(BC-\d+)\]_[^_]+_\[[\d-]+\]_(.+?)_\[")
POSTAL_RE = re.compile(r"^(BC-\d+)_(.+)\.pdf$", re.IGNORECASE)

# 파일명 토큰 중 금융기관명을 식별하는 접미사. '회사_은행_지점' 에서 은행 토큰을 고른다.
_FIN_SUFFIX_TOK = ("은행", "증권", "보험", "캐피탈", "캐피털", "카드", "저축은행",
                   "금융투자", "생명", "화재", "신탁", "자산운용", "투자운용", "공제")

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
        # "회사명_은행명[_지점]" 형태에서 은행명을 고른다. 과거 parts[-1] 은 지점명이 별도
        # 토큰이면 지점을 은행으로 오인('회사_신한은행_강남지점'→'강남지점'). 금융 접미사
        # 토큰부터 끝까지(은행명+지점) 채택해 회사 prefix 만 제거(normalize 가 지점 처리).
        parts = rest.split("_")
        if len(parts) > 1:
            idx = next((i for i, p in enumerate(parts)
                        if any(suf in p for suf in _FIN_SUFFIX_TOK)), None)
            bank = " ".join(parts[idx:]) if idx is not None else parts[-1]
        else:
            bank = rest
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
