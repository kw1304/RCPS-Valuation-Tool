"""AC5 담보제공자산 파서. direction: provided(제공)/received(제공받음).

회신서 §9(제3자/회사 담보·보증 현황)은 부동산 담보 표가 여러 물리 줄로 wrap 된다:
  경기도 성남시 분당구 삼평동 622                              ← 주소(소재지) 조각, 금액 없음
  집합건물상가(독립적) 에프동101호 ... (KRW)2,634,000,000 (KRW)12,000,000,000 3   ← 실데이터
  386.15                                                       ← 면적(㎡) 조각, 금액 없음

핵심 불변(invariant): **진짜 담보 record 는 천단위 콤마로 그룹된 원화 금액(>=1,000,000)을
최소 1개 가진다**. 주소 번지(622)·설정순위(3/6)·면적(386.15)은 콤마 그룹이 아니거나 100만
미만이라 금액으로 보지 않는다. 따라서:
  - 금액 토큰: '(KRW)2,634,000,000' (KRW prefix) / '20,171,880,000.00' (국민, prefix 無) 둘 다 인식
  - 천단위 콤마 그룹 + 정수부 환산 >= 1,000,000 인 값만 금액
  - 그런 금액이 0개인 줄(주소·면적 조각)은 record 미생성 → 조각 garbage 제거
  - book_amount = 첫 금액(감정금액/채권최고액), appraised_amount = 둘째 금액(설정금액) if 有
  - collateral_type = 담보 종류 토큰(집합건물상가/상장주식/공장/토지/건물/예금/유가증권/근저당/
    질권/보증인 등). 주소어(경기도/서울/부산/충청북도…) 로 시작하는 줄은 금액이 없어 어차피
    rule 로 걸러지지만, 안전을 위해 type 후보에서도 주소·숫자 토큰을 배제한다.

§5(타 법인 위한 담보)는 단순(예: '부동산근저당 1,200,000,000 900,000,000')할 수 있는데,
1.2억은 100만 임계를 넘으므로 동일 로직으로 그대로 record 가 생성된다.
"""
import re
from decimal import Decimal, InvalidOperation
from src.domain.ac_models import Collateral
from src.infrastructure.pdf.row_parsers.base import is_noise

# 금액 임계: 이보다 작으면 번지(622)·순위(3)·면적(386.15)로 보고 금액 취급 안 함.
_MIN_AMOUNT = Decimal("1000000")

# 통화 코드 집합.
_CCY_CODES = "KRW|USD|EUR|JPY|CNY|HKD|GBP|AUD|SGD|CNH"

# 통화 prefix: (KRW) / (USD) … 또는 선행 KRW. 금액 토큰 앞에 붙어 옴.
_CCY_PREFIX = re.compile(rf"^\(({_CCY_CODES})\)")
_LEAD_CCY = re.compile(rf"^({_CCY_CODES})(?=\d)")
# 통화 suffix: 144000000KRW / 2,400,000,000(USD) … 금액 토큰 뒤에 붙어 옴.
_TRAIL_CCY = re.compile(rf"(?<=\d)(\(({_CCY_CODES})\)|({_CCY_CODES}))$")

# 천단위 콤마로 그룹된 원화 금액. '2,634,000,000' 또는 '20,171,880,000.00'.
_GROUPED_AMOUNT = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
# 콤마 없는 평문 정수 금액. '1800000000' / '36607800000.00'.
# 100만 임계(_MIN_AMOUNT)와 결합해 번지(622)·순위(3)·면적(386.15)·연도 등 단편 배제.
_PLAIN_AMOUNT = re.compile(r"^\d+(?:\.\d+)?$")

# 담보 종류로 쓰면 안 되는 주소(소재지) 시작어. 이런 토큰으로 시작하는 줄은 소재지 조각.
_ADDR_PREFIX = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충청", "충북", "충남", "전라", "전북", "전남",
    "경상", "경북", "경남", "제주",
)

# 헤더/합계 토큰 — 종류로 채택 금지.
_HEADER_TOKENS = {
    "구분", "담보보증의", "내용", "소유자", "감정금액", "설정금액",
    "설정순위", "선순위", "담보", "보증", "합계", "소계", "총계",
}


def _strip_ccy(tok: str) -> str:
    """토큰의 통화 prefix/suffix 제거.

    prefix: '(KRW)2,634,000,000' / 'KRW36607800000'
    suffix: '144000000KRW' / '2,400,000,000(USD)'
    """
    m = _CCY_PREFIX.match(tok)
    if m:
        tok = tok[m.end():]
    else:
        m = _LEAD_CCY.match(tok)
        if m:
            tok = tok[m.end():]
    m = _TRAIL_CCY.search(tok)
    if m:
        tok = tok[:m.start()]
    return tok


def _is_amount(bare: str) -> bool:
    """콤마 그룹(a) 또는 콤마 없는 평문 정수(b) → 금액 후보 형식."""
    return bool(_GROUPED_AMOUNT.match(bare) or _PLAIN_AMOUNT.match(bare))


def _to_dec(s: str):
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _won_amounts(line: str) -> list[Decimal]:
    """줄에서 원화 금액(>= 100만)만 순서대로 추출.

    인식 형식: (a) 천단위 콤마 그룹 '2,634,000,000', (b) 콤마 없는 평문 정수
    '1800000000', (c) 통화 접두/접미가 붙은 '(KRW)…'/'KRW…'/'…KRW'.
    번지(622)·설정순위(3/6)·면적(386.15)은 100만 임계 미만 → 제외(단편 garbage 방지).
    """
    # 1차 수집: (값, 콤마그룹여부, 소수여부) 순서 보존.
    cand: list[tuple[Decimal, bool, bool]] = []
    has_grouped = False
    for tok in line.split():
        bare = _strip_ccy(tok)
        if not _is_amount(bare):
            continue
        v = _to_dec(bare)
        if v is None or v < _MIN_AMOUNT:
            continue
        grouped = bool(_GROUPED_AMOUNT.match(bare))
        has_grouped = has_grouped or grouped
        cand.append((v, grouped, "." in bare))
    # 콤마그룹 금액이 한 줄에 있으면, 무콤마·무소수 큰 정수(20215243773 등)는 약정/계좌
    # ref 이지 금액이 아니다 → 제외. 콤마그룹이 전혀 없으면(국민식 무콤마 표) 전부 금액.
    out: list[Decimal] = []
    for v, grouped, has_dec in cand:
        if has_grouped and not grouped and not has_dec:
            continue
        out.append(v)
    return out


def _is_amount_token(tok: str) -> bool:
    """금액 컬럼 토큰 = 금액 형식이면서 100만 임계 이상.

    평문 정수까지 허용하므로, 종류 탐색이 면적(386.15)·순위(3) 같은 소액 숫자에서
    멈추지 않도록 임계를 함께 본다.
    """
    bare = _strip_ccy(tok)
    if not _is_amount(bare):
        return False
    v = _to_dec(bare)
    return v is not None and v >= _MIN_AMOUNT


def _looks_numeric(tok: str) -> bool:
    """순수 숫자/콤마/소수/하이픈 토큰(번지·순위·면적·금액·'-') → 종류 아님."""
    t = tok.replace(",", "").replace(".", "").replace("-", "")
    return t == "" or t.isdigit()


def _collateral_type(line: str) -> str:
    """담보 종류 토큰 추출 = 줄의 첫 '실텍스트' 토큰.

    주소어/숫자/통화금액/헤더 토큰은 건너뛴다. 보통 데이터 줄의 첫 토큰이 종류
    (집합건물상가(독립적), 상장주식, 공장, 보증인 …)다.
    """
    toks = line.split()
    for tok in toks:
        if _is_amount_token(tok):
            break  # 금액 컬럼 도달 — 그 앞에서 종류를 못 찾았으면 포기
        if _looks_numeric(tok):
            continue
        if tok.startswith(_ADDR_PREFIX):
            continue
        if tok in _HEADER_TOKENS:
            continue
        # 통화 코드 단독
        if tok in ("KRW", "USD", "EUR", "JPY", "CNY", "HKD", "GBP", "AUD", "SGD", "CNH"):
            continue
        return tok[:40]
    # 못 찾으면 첫 비숫자 토큰(최후)
    for tok in toks:
        if not _looks_numeric(tok) and not _is_amount_token(tok):
            return tok[:40]
    return (toks[0] if toks else "")[:40]


def _is_stock(ctype: str) -> bool:
    """주식/상장주식 등 유가증권성 담보 종류인가 (선순위설정금액 비적용 대상)."""
    return "주식" in (ctype or "")


def parse_ac5(block: str, bc_no: str, bank: str, direction: str = "provided") -> list[Collateral]:
    out: list[Collateral] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        amounts = _won_amounts(s)
        if not amounts:
            # 금액 없는 줄 = 주소·면적·순위 조각 → record 미생성(조각 garbage 제거)
            continue
        ctype = _collateral_type(s)
        # 부동산 담보: book(감정/채권최고액) + appraised(설정금액) + 선순위설정금액 3개 컬럼.
        # 순위(rank) 정수(2/3)는 100만 임계 미만이라 _won_amounts 에서 이미 제외되므로,
        # 임계 이상 금액이 3개면 세 번째가 선순위설정금액이다.
        senior = amounts[2] if len(amounts) >= 3 else None
        # 주식/상장주식 담보는 선순위설정금액을 잡지 않는다. 참고조서 선순위 설정금액
        # 컬럼은 부동산 담보(집합건물상가 등)에만 채워지며, 주식의 후순위 행 뒤
        # (KRW)59,400,000,000 등은 동일 발행주식의 선순위(순위1) 설정금액으로 이미
        # 설정금액 컬럼에 공시된 값이라 선순위 컬럼에 중복 기재하지 않는다. 잡으면
        # 같은 금액이 설정·선순위 두 곳에서 이중계상돼 AC5 가 과대해진다.
        if _is_stock(ctype):
            senior = None
        out.append(Collateral(
            bc_no=bc_no, bank=bank, collateral_type=ctype,
            book_amount=amounts[0],
            appraised_amount=amounts[1] if len(amounts) >= 2 else None,
            senior_lien=senior,
            direction=direction,
        ))
    return out
