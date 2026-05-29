"""우편/unknown 양식 best-effort 파서. 모든 레코드 needs_manual_review=True.

억지 자동화로 틀린 숫자를 넣지 않는다 — 감사인 직접 확인용 후보만 추출.

라우팅 원칙
----------
기관종류(파일명에서 normalize 된 `bank`)가 **기본 AC**를 정한다.
줄(LINE) 키워드는 그 안에서 세부 보정만 한다(대출→AC2, 담보→AC5, 어음→AC6).
- 보험사(화재/해상/손해보험/손보/생명/보험/공제) → 기본 AC7
- 자산운용/투자운용/금융투자 → 기본 AC1 (유가증권)
- 카드/캐피탈/렌탈/리스 → 기본 AC8 (기타/일반거래)
- 은행/증권/저축은행 → 기본 AC1, 줄 키워드로 AC2 등 보정
- 그 외(금융 접미사 없음, 예: 카일이삼제스퍼) → AC1 강제 금지, AC8(기타)로
"""
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

# 줄(LINE) 키워드 → AC 세부 보정. 기관종류 기본값을 덮어쓸 수 있는 강한 신호만.
_LINE_KEYWORDS = {
    "AC2": ["대출", "차입", "loan", "borrowing"],
    "AC5": ["담보", "근저당", "collateral"],
    "AC6": ["어음", "수표", "당좌"],
    "AC4": ["지급보증", "보증", "guarantee", "L/C"],
    "AC7": ["보험", "insurance", "부보", "보험증권", "화재", "해상", "손해", "생명", "공제"],
    "AC1": ["예금", "deposit", "잔액", "balance", "유가증권", "주식", "펀드"],
}

# 기관종류 토큰 → 기본 AC. 긴 토큰(화재해상보험 등)이 짧은 토큰을 포함하므로
# 가장 구체적인 분류부터 검사한다.
_INSURER_TOKENS = ("화재해상보험", "손해보험", "보증보험", "화재", "해상", "손해",
                   "손보", "생명보험", "생명", "보험", "공제")
_ASSET_MGMT_TOKENS = ("자산운용", "투자운용", "금융투자")
_GENERAL_TOKENS = ("카드", "캐피탈", "렌탈", "리스")
_BANK_SEC_TOKENS = ("저축은행", "상호금융", "은행", "증권", "신탁")


def _institution_default_ac(bank: str) -> str:
    """기관명(normalize)에서 기본 AC를 결정.

    금융 접미사가 전혀 없으면(비금융/unknown) AC1 강제 금지 → AC8(기타)."""
    b = bank or ""
    if any(tok in b for tok in _INSURER_TOKENS):
        return "AC7"
    if any(tok in b for tok in _ASSET_MGMT_TOKENS):
        return "AC1"
    if any(tok in b for tok in _GENERAL_TOKENS):
        return "AC8"
    if any(tok in b for tok in _BANK_SEC_TOKENS):
        return "AC1"
    # 금융 접미사 없음 → 비금융/미상. 예금(AC1)으로 오분류하지 않는다.
    return "AC8"


def fallback_parse(text: str, bc_no: str, bank: str) -> list[dict]:
    out: list[dict] = []
    default_ac = _institution_default_ac(bank)
    for line in text.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        ac = default_ac
        # 줄 키워드로 세부 보정. 단, 비금융 기본(AC8)은 AC1로 끌어올리지 않는다.
        for cand, kws in _LINE_KEYWORDS.items():
            if cand == "AC1" and default_ac == "AC8":
                continue
            if any(k in s for k in kws):
                ac = cand
                break
        out.append({
            "ac_section": ac,
            "payload": {"bc_no": bc_no, "bank": bank, "raw": s[:120],
                        "amounts": [str(a) for a in t.amounts],
                        "currency": t.currency},
            "needs_manual_review": True,
        })
    return out
