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
import re
from decimal import Decimal

from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

# ── OCR 금액 토큰 복원 ────────────────────────────────────────────────────────
# 스캔 보험사 회신서는 디지털 텍스트가 0이라 OCR 해야 하고, OCR 은 천단위 구분자를
# 점(.)·콤마(,) 로 뒤섞어 인식한다(예: 20,215.243,773 · 5.135.784,000 · 20.215.243.773).
# base.tokenize_row 의 _NUM 정규식은 이런 혼용/다중점 토큰을 금액으로 못 잡아 부보금액
# (참고조서 AC7 의 가장 큰 값)이 통째로 누락된다. 여기서 OCR-관대 토크나이저로 복원한다.
#
# 복원 규칙(보수적): 토큰을 [.,] 로 분할했을 때 (1) 그룹이 2개 이상이고 (2) 첫 그룹은
# 1~3자리, (3) 나머지 그룹이 전부 정확히 3자리면 천단위 그룹핑된 정수로 보고 점·콤마를
# 모두 제거해 정수로 합친다. 이 규칙은 날짜(24.11.07 → 마지막 그룹 2자리)·이자율
# (0.00 → 그룹 2자리)·일반 소수를 천단위 정수로 오인하지 않는다.
_OCR_AMT_TOK = re.compile(r"^\d[\d.,]*\d$")
_PCT_TOK = re.compile(r"%$")


def _ocr_amounts(line: str) -> list[Decimal]:
    """OCR 노이즈(점·콤마 혼용 천단위)를 견디며 줄에서 정수 원화 금액을 추출.

    천단위 그룹(첫 1~3자리 + 이후 3자리들)으로 해석되는 토큰만 정수로 복원하고,
    날짜(24.11.07)·이자율(0.00%)·페이지(1/1) 등은 제외한다."""
    out: list[Decimal] = []
    for raw in line.replace("~", " ").split():
        tok = raw.rstrip("%")
        if _PCT_TOK.search(raw):
            continue  # 이자율(0.00%) — 금액 아님
        if "/" in raw or ":" in raw:
            continue  # 페이지(1/1)·시각(13:51:56)
        if not _OCR_AMT_TOK.match(tok):
            continue
        groups = re.split(r"[.,]", tok)
        if len(groups) == 1:
            # 구분자 없는 순수 숫자. 8자리 이상은 증권번호/계좌번호(base._ACCT 와 동일
            # 기준)로 보고 금액에서 제외 — OCR 의 원화 금액은 항상 구분자를 동반한다.
            if tok.isdigit() and len(tok) <= 7:
                out.append(Decimal(tok))
            continue
        first, rest = groups[0], groups[1:]
        if not (1 <= len(first) <= 3) or not first.isdigit():
            continue
        if not all(len(g) == 3 and g.isdigit() for g in rest):
            continue  # 날짜/이자율/일반 소수 — 천단위 그룹핑 아님
        out.append(Decimal("".join(groups)))
    return out

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


# 부보금액 규모 합계행 판정 임계치(이 이상이면 합계 의심). 소액 placeholder 행은 무관.
_SUBTOTAL_MIN = Decimal("1000000")
# fallback 금액 하한 — 회신 금액(보증·부보·예금·차입)은 만원 미만이 없다. 연도(2024)·
# 증권 index·계좌 단편 같은 소액 잡음이 행의 max 로 잡혀 가짜 금액이 되는 것 방지.
_MIN_FALLBACK_AMOUNT = Decimal("10000")
# 알파벳·한글 등 '글자'(amount 구분자가 아닌 의미 텍스트) 포함 여부.
_HAS_LETTER = re.compile(r"[A-Za-z가-힣]")


def _is_ocr_subtotal_row(raw: str, t, amounts: list[Decimal]) -> bool:
    """OCR 보험사 회신서의 합계/소계 행인지 판정(이중계상 방지).

    합계행 시그니처: 증권번호(account) 없음 + 의미있는 글자(상품명/라벨) 없음 +
    대형 금액(부보금액 규모) 존재 → 순수 금액만 나열된 행 = 합계.
    글자(한글/영문 상품명·라벨)가 있거나 증권번호가 있으면 실제 정책행으로 보존한다."""
    if t.account is not None:
        return False
    if _HAS_LETTER.search(raw):
        return False
    return any(a >= _SUBTOTAL_MIN for a in amounts)


def fallback_parse(text: str, bc_no: str, bank: str) -> list[dict]:
    out: list[dict] = []
    default_ac = _institution_default_ac(bank)
    for line in text.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        # OCR-관대 토크나이저로 점·콤마 혼용 천단위 금액(부보금액 등)도 복원.
        ocr_amts = _ocr_amounts(s)
        # 두 추출기 결과를 합집합(멀티셋 합)으로. 같은 금액을 양쪽이 잡아도 한 행의
        # 대표값(harness 는 행별 max)만 쓰므로 중복은 무해하다. OCR 가 복원한 대형
        # 부보금액이 tokenize_row 에서 누락됐던 경우 여기서 살아난다.
        amounts = list(t.amounts)
        for a in ocr_amts:
            if a not in amounts:
                amounts.append(a)
        # 연도(2024)·index 등 소액 잡음 배제(만원 미만). 행에 실금액이 없으면 record 미생성.
        amounts = [a for a in amounts if a >= _MIN_FALLBACK_AMOUNT]
        if not amounts:
            continue
        # OCR 합계/소계 행 제거(이중계상 방지): 보험사 회신서 스캔은 정책행 뒤에
        # 증권번호·상품명 없는 순수 금액 행(예: '26,329,689,846 7,971,566',
        # '30,486.811,773 ...')을 합계로 남긴다. 증권번호(account)도, 의미있는 텍스트
        # 토큰도 없는데 대형 금액(부보금액 규모)만 있는 행은 합계로 보고 버린다.
        # 한글/영문 라벨(보험증권·부보 등)이 있는 행은 실데이터로 보존한다.
        if _is_ocr_subtotal_row(s, t, amounts):
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
                        "amounts": [str(a) for a in amounts],
                        "currency": t.currency},
            "needs_manual_review": True,
        })
    return out
