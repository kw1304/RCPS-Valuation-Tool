"""AC7 보험 파서. 보험상품명·증권번호·부보금액·보험료·보험시작일·보험종료일.

범용 손해보험 회신서 레이아웃 — wrap 된 컬럼 헤더 + wrap 된 영문 상품명 + 보험사마다
다른 증권번호 표기(순수 숫자 / 영숫자 / 영숫자-하이픈)와 통화 표기(KRW / WON)를 모두 처리.

헤더(여러 줄 wrap):
  연간보험료 부보기간
  보험의 종류 증권번호 부보금액 보장성보험료 누적 적립금 해약환급금 연이자율 권리제한 비고
  이외 시작 종료
  및 사업비

정책행 예시 (보험사별):
  KB손보   : Compensation 20258450627 300,000,000 2,034,000 20251212 20261211 0 0
  한화손보 : 한화 운전자상해 LA2025378274 KRW KRW 122,508 KRW 0 ... KRW 0 KRW 1,390 1.5 N
             (부보금액은 다음 줄로 wrap → '보험 2504 3000 525,410,000')
  메리츠   : 상품명 6ADKD-1971 KRW 0 KRW 238491 KRW -11 ... KRW 238480 KRW 14163 0 0
  현대해상 : Products/Comp F20240786542 WON WON 9692417 WON 0 ... WON 9692417 WON 0 0
             ('leted Operat 1412800000' 으로 부보금액이 wrap)

증권번호 식별 (범용):
  - 영숫자 토큰 [A-Z0-9][A-Z0-9\\-]{6,18} 이고 숫자를 1개 이상 포함하면 증권번호로 본다.
    (예: LA2025378274, 6ADKD-1971, F20240786542, 20258450627)
  - 단, 8자리 순수 숫자(YYYYMMDD 날짜)는 증권번호가 아니다.
  - 헤더/noise 줄은 제외한다.

부보금액·보험료 추출 (범용):
  - 헤더 컬럼 순서상 부보금액(coverage) → 보장성보험료(premium).
  - 금액은 콤마 유무 무관 (300,000,000 / 9692417 / 1412800000).
  - 부보금액은 정책행에 없고 다음 줄로 wrap 될 수 있다 → 정책행 뒤의 '숫자만 있는'
    연속 줄에서 가장 큰 금액을 끌어와 부보금액 후보로 합친다.
  - coverage = (정책행 + wrap 줄) 금액 중 보험금액 임계치 이상인 최대값.
    임계치 이상이 없으면 0(예: KB업무용 부보 0, 메리츠 부보 0)으로 둔다.
  - premium = coverage 로 쓰인 금액을 제외한 양수 금액 중 첫 번째(가장 큰 값).

상품명 누적기(accumulator):
  - 정책행 직전 연속 텍스트 줄을 선행 상품명 조각으로 버퍼링.
  - 정책행 직후 텍스트 줄은 영문 상품명 후행 wrap 으로 직전 정책에 append.
  - header·noise 줄을 만나면 선행 버퍼를 비운다.

부보금액·보험료 0 은 정상 값이므로 행을 버리지 않는다 — 증권번호가 있으면 실제 정책이다.
"""
import re
from decimal import Decimal
from src.domain.ac_models import Insurance
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise, _dec

# 헤더 줄 식별 키워드.
_HEADER_KW = (
    "증권번호", "보험상품명", "보험의 종류", "부보금액", "보험료", "보험시작일",
    "보험종료일", "해약환급금", "보험기간", "부보기간", "보장성", "연간보험료",
    "적립금", "연이자율", "권리제한", "비고",
)
_HEADER_FRAGMENTS = {"이외", "시작", "종료", "및", "사업비", "누적", "적립금"}

# 증권번호: 영숫자(+하이픈) 7~19자, 숫자 1개 이상 포함. 8자리 순수 숫자(날짜)는 제외.
_POLICY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{6,18}$")
_HAS_DIGIT = re.compile(r"\d")
_DATE8_RE = re.compile(r"^\d{8}$")
# 콤마 유무 무관 금액 토큰 (소수 허용).
_AMT_RE = re.compile(r"^\d[\d,]*(?:\.\d+)?$")
# 부보금액(coverage) 임계치: 이 값 이상이어야 부보금액 후보로 본다.
_COVERAGE_MIN = Decimal("1000000")  # 100만원


def _is_header(s: str) -> bool:
    if any(k in s for k in _HEADER_KW):
        return True
    toks = s.split()
    if toks and all(tok in _HEADER_FRAGMENTS for tok in toks):
        return True
    return False


_PURE_NUM_RE = re.compile(r"^\d+$")


def _find_policy_token(s: str) -> str | None:
    """줄에서 증권번호 토큰을 찾는다. 없으면 None.

    영숫자(문자/하이픈 포함) 토큰은 명확한 증권번호다.
    순수 숫자 토큰(예: KB 20258450627)은 같은 줄에 날짜 또는 통화가 함께 있을 때만
    증권번호로 본다 — 이렇게 하면 부보금액 wrap 줄의 대형 숫자('leted Operat 1412800000')를
    새 정책으로 오인하지 않는다(범용).
    """
    toks = s.split()
    has_date = any(_DATE8_RE.match(tk) for tk in toks)
    has_ccy = tokenize_row(s).currency is not None
    for tok in toks:
        if _DATE8_RE.match(tok):
            continue  # 8자리 순수 숫자는 날짜
        if _POLICY_RE.match(tok) and _HAS_DIGIT.search(tok):
            if _PURE_NUM_RE.match(tok):
                # 순수 숫자 증권번호: 데이터 행(날짜/통화 동반)일 때만 채택.
                if has_date or has_ccy:
                    return tok
                continue
            return tok
    return None


def _won_amounts(s: str) -> list[Decimal]:
    """줄에서 금액 토큰(콤마 유무 무관)을 등장 순서대로 추출. 컬럼 정렬 보존을 위해
    0 도 포함한다(부보금액 0 등 placeholder). 음수/괄호/8자리 날짜(YYYYMMDD)는 제외."""
    out: list[Decimal] = []
    for tok in s.split():
        if _DATE8_RE.match(tok):
            continue  # 8자리 순수 숫자는 보험시작/종료일 → 금액 아님
        if _AMT_RE.match(tok):
            v = _dec(tok)
            if v is not None and v >= 0:
                out.append(v)
    return out


def _is_numeric_continuation(s: str) -> bool:
    """줄의 토큰이 전부 숫자/금액 조각이면(부보금액 wrap 후보) True.
    영문/한글 텍스트 wrap('Insurance', 'leted Operat ...')은 False."""
    toks = s.split()
    if not toks:
        return False
    return all(_AMT_RE.match(tok) for tok in toks)


def _extract_amounts(policy_line_amts: list[Decimal], wrap_amts: list[Decimal]):
    """부보금액(coverage)·보험료(premium) 추출 (범용).

    헤더 컬럼 순서: 부보금액(coverage) → 보장성보험료(premium).
    - 기본(positional): coverage = 정책행 첫 금액, premium = 정책행 둘째 금액.
      (KB 300,000,000/2,034,000 · KB업무용 0/1,265,530 처럼 부보금액 0 도 그대로 보존.)
    - wrap override: 부보금액이 정책행에 없고 다음 줄(숫자 wrap)로 떨어진 보험사(한화)는
      wrap 줄의 임계치 이상 대형 금액이 부보금액이다. wrap 의 최대 금액이 임계치 이상이고
      현재 positional coverage 보다 크면 그것을 부보금액으로 채택한다.
    """
    coverage = policy_line_amts[0] if len(policy_line_amts) >= 1 else Decimal("0")
    premium = policy_line_amts[1] if len(policy_line_amts) >= 2 else Decimal("0")

    if wrap_amts:
        wrap_big = max((a for a in wrap_amts if a >= _COVERAGE_MIN), default=Decimal("0"))
        if wrap_big > coverage:
            # 부보금액이 wrap 된 경우: 기존 positional coverage 는 실은 보험료 컬럼이었다.
            if premium == Decimal("0") and coverage > Decimal("0"):
                premium = coverage
            coverage = wrap_big
    return coverage, premium


def parse_ac7(block: str, bc_no: str, bank: str) -> list[Insurance]:
    out: list[Insurance] = []
    pending: list[str] = []     # 정책행 직전 상품명 wrap 조각 버퍼
    last: Insurance | None = None  # 직전 정책 (후행 wrap append 용)
    last_policy_amts: list[Decimal] = []  # 직전 정책행의 금액(wrap 부보금액 합산용)

    for raw in block.splitlines():
        s = raw.strip()
        if not s:
            continue
        if is_noise(s) or _is_header(s):
            pending = []
            last = None
            last_policy_amts = []
            continue

        policy_tok = _find_policy_token(s)

        if policy_tok:
            # 증권번호 토큰 제거 후 나머지에서 상품명/금액/날짜/통화 파싱
            rest = " ".join(tok for tok in s.split() if tok != policy_tok)
            t = tokenize_row(rest)
            line_text = " ".join(t.text_tokens).strip()
            product = " ".join(pending + ([line_text] if line_text else [])).strip()
            pending = []
            if not product:
                product = "(미상)"
            policy_amts = _won_amounts(rest)
            coverage, premium = _extract_amounts(policy_amts, [])
            rec = Insurance(
                bc_no=bc_no, bank=bank, product=product[:80],
                policy_no=policy_tok,
                coverage_amount=coverage,
                premium=premium,
                start_date=t.dates[0] if len(t.dates) >= 1 else None,
                end_date=t.dates[1] if len(t.dates) >= 2 else None,
            )
            out.append(rec)
            last = rec
            last_policy_amts = policy_amts
        else:
            # 정책행이 아닌 줄.
            if last is not None and _is_numeric_continuation(s):
                # 직전 정책의 부보금액 wrap (예: '보험 2504 3000 525,410,000', 'leted Operat 1412800000')
                # → 숫자만 있는 줄: 대형 금액을 부보금액 후보로 재계산.
                wrap_amts = _won_amounts(s)
                coverage, premium = _extract_amounts(last_policy_amts, wrap_amts)
                last.coverage_amount = coverage
                last.premium = premium
                continue
            txt = " ".join(tokenize_row(s).text_tokens).strip()
            if not txt:
                continue
            if last is not None:
                # 직전 정책 직후 텍스트 줄 = 영문 상품명 후행 wrap → append.
                # 단, 'leted Operat 1412800000' 처럼 숫자가 섞인 wrap 은 부보금액도 합산.
                wrap_amts = _won_amounts(s)
                if wrap_amts:
                    coverage, premium = _extract_amounts(last_policy_amts, wrap_amts)
                    last.coverage_amount = coverage
                    last.premium = premium
                merged = (last.product + " " + txt).strip()
                last.product = merged[:80]
            else:
                pending.append(txt)
    return out
