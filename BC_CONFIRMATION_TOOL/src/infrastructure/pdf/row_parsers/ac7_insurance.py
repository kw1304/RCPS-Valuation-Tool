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
# 전화번호(02-6929-2791, 02-758-7597 등)는 증권번호가 아니다 — 삼성화재 §1 행 끝에 붙는다.
_PHONE_RE = re.compile(r"^0\d{1,2}-\d{3,4}-\d{4}$")
# 콤마 유무 무관 금액 토큰 (소수 허용).
_AMT_RE = re.compile(r"^\d[\d,]*(?:\.\d+)?$")
# 부보금액(coverage) 임계치: 이 값 이상이어야 부보금액 후보로 본다.
_COVERAGE_MIN = Decimal("1000000")  # 100만원


def _amt_dec(tok: str) -> Decimal | None:
    """금액 토큰 → Decimal. `,00` 트레일링 아티팩트 정규화.

    pdfminer 가 일부 회신서(삼성화재·DB손보·KB손보)에서 소수점을 콤마로 렌더해
    `41,500,000,00`(=41,500,000.00) · `15,000,000,00` · `147,831,814,0` 처럼
    뒤에 1~2자리 콤마-그룹을 붙인다. 정상 천단위 그룹은 항상 3자리이므로,
    마지막 콤마-그룹이 1~2자리면 소수(센트) 아티팩트로 보고 버린다.
    """
    parts = tok.split(",")
    if len(parts) >= 2 and 1 <= len(parts[-1]) <= 2:
        tok = "".join(parts[:-1])
    try:
        return Decimal(tok.replace(",", ""))
    except Exception:
        return None


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
        if _PHONE_RE.match(tok):
            continue  # 전화번호는 증권번호가 아니다
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
        if _PHONE_RE.match(tok):
            continue  # 전화번호는 금액 아님
        if _AMT_RE.match(tok):
            v = _amt_dec(tok)
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


def _positional(amts: list[Decimal]):
    """컬럼 순서(부보금액 → 보장성보험료)대로 정책행 첫째=부보, 둘째=보험료.
    KB 300,000,000/2,034,000 · KB업무용 0/1,265,530 처럼 부보 0 도 보존."""
    coverage = amts[0] if len(amts) >= 1 else Decimal("0")
    premium = amts[1] if len(amts) >= 2 else Decimal("0")
    return coverage, premium


def _positional_threshold(amts: list[Decimal]):
    """삼성화재 데이터-연속줄용: 증권번호 suffix(0893·9000·2504 등 임계치 미만 정수)와
    KRW 0 placeholder 를 건너뛰고, 컬럼 순서상 첫 임계치 이상 금액=부보금액,
    바로 다음 금액=보험료.

    예) '험(Ⅱ) 0893 41,500,000,00 167,470,070 KRW 0 ...' → [893,41500000,167470070,0,...]
        → 부보=41,500,000, 보험료=167,470,070
        'Liability Policy 9000 500,000,000 83,212,000' → [9000,500000000,83212000]
        → 부보=500,000,000, 보험료=83,212,000
    """
    for i, a in enumerate(amts):
        if a >= _COVERAGE_MIN:
            premium = amts[i + 1] if i + 1 < len(amts) else Decimal("0")
            return a, premium
    return Decimal("0"), Decimal("0")


def _extract_amounts(policy_line_amts: list[Decimal], wrap_amts: list[Decimal]):
    """부보금액(coverage)·보험료(premium) 추출 — 한화/현대 wrap-override 레이아웃.

    헤더 컬럼 순서: 부보금액(coverage) → 보장성보험료(premium).
    - 기본(positional): coverage = 정책행 첫 금액, premium = 정책행 둘째 금액.
    - wrap override: 부보금액이 정책행에 없고 다음 줄(숫자 wrap)로 떨어진 보험사(한화·현대)는
      wrap 줄의 임계치 이상 대형 금액이 부보금액이다. wrap 의 최대 금액이 임계치 이상이고
      현재 positional coverage 보다 크면 그것을 부보금액으로 채택한다.
    """
    coverage, premium = _positional(policy_line_amts)

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
    pending_amts: list[Decimal] = []  # 정책행 직전 줄에 wrap 된 금액(부보금액)
    last: Insurance | None = None  # 직전 정책 (후행 wrap append 용)
    last_policy_amts: list[Decimal] = []  # 직전 정책행의 금액(wrap 부보금액 합산용)
    prev_content_li = -1        # 직전 비공백 content 줄 index
    last_policy_li = -2         # 직전 정책행 줄 index

    lines = block.splitlines()
    for li, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        if is_noise(s) or _is_header(s):
            pending = []
            pending_amts = []
            last = None
            last_policy_amts = []
            prev_content_li = li
            continue

        prev = prev_content_li   # 이 줄 처리 전 직전 content 줄 index
        prev_content_li = li

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
            # 부보금액이 정책행 직전 줄로 wrap 된 경우(KB바이오 재산종합보험: '재산종합보험 147,831,814,0'
            # 이 정책번호 줄 위에 위치): 정책행 부보금액이 임계치 미만이면 pending 의 대형 금액을 채택.
            if coverage < _COVERAGE_MIN and pending_amts:
                pend_big = max((a for a in pending_amts if a >= _COVERAGE_MIN), default=Decimal("0"))
                if pend_big > coverage:
                    if premium == Decimal("0") and coverage > Decimal("0"):
                        premium = coverage
                    coverage = pend_big
            pending_amts = []
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
            last_policy_li = li
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
            # 삼성화재형 데이터-연속줄: 증권번호 줄(L5)에 날짜·실금액이 없고, 다음 줄(L6)에
            # 날짜+부보금액+보험료가 모두 실린다. 직전 정책에 날짜가 아직 없고 이 줄에 날짜가
            # 있으면 데이터-연속줄로 보고 컬럼 순서대로(임계치 기준) 부보/보험료·날짜를 채운다.
            if (
                last is not None
                and last.end_date is None
                and not last_policy_amts
            ):
                ct = tokenize_row(s)
                if ct.dates:
                    cont_amts = _won_amounts(s)
                    coverage, premium = _positional_threshold(cont_amts)
                    last.coverage_amount = coverage
                    last.premium = premium
                    last.start_date = ct.dates[0] if len(ct.dates) >= 1 else None
                    last.end_date = ct.dates[1] if len(ct.dates) >= 2 else None
                    txt = " ".join(ct.text_tokens).strip()
                    if txt:
                        last.product = (last.product + " " + txt).strip()[:80]
                    continue
            txt = " ".join(tokenize_row(s).text_tokens).strip()
            wrap_amts = _won_amounts(s)
            # 다음(비어있지 않은) 줄에 새 증권번호가 있는지 확인.
            next_is_policy = False
            for nxt in lines[li + 1:]:
                ns = nxt.strip()
                if not ns:
                    continue
                next_is_policy = _find_policy_token(ns) is not None
                break

            # 이 amounts-줄을 어느 정책에 귀속시키나?
            #  - 직전 정책행 바로 다음 줄이면(현대 'leted Operat 1412800000', 한화 '보험 ... 525,410,000')
            #    → 직전 정책의 부보금액 wrap (post-wrap). 다음 줄이 새 정책이어도 마찬가지.
            #  - 직전 정책행과 떨어져 있고(중간에 텍스트 wrap) 다음 줄이 새 정책이면
            #    (KB바이오 '재산종합보험 147,831,814,0' → 다음 줄 20250496393)
            #    → 다음 정책의 선행 wrap (pre-wrap) → pending 버퍼링.
            is_post_wrap = (last is not None) and (prev == last_policy_li)
            route_to_next = next_is_policy and not is_post_wrap

            if not txt and not wrap_amts:
                continue
            if last is not None and not route_to_next:
                # 직전 정책 후행 wrap → 상품명/부보금액 append.
                if wrap_amts:
                    # 삼성화재형: 정책행 금액이 전부 placeholder(임계치 미만)이고 실데이터가
                    # 후행 wrap 줄('Liability Policy 9000 500,000,000 83,212,000')에 부보+보험료로
                    # 함께 실린 경우 → 컬럼 순서(임계치)대로 부보/보험료 둘 다 채운다.
                    policy_has_real = any(a >= _COVERAGE_MIN for a in last_policy_amts)
                    wrap_has_real = any(a >= _COVERAGE_MIN for a in wrap_amts)
                    if not policy_has_real and wrap_has_real:
                        coverage, premium = _positional_threshold(wrap_amts)
                    else:
                        coverage, premium = _extract_amounts(last_policy_amts, wrap_amts)
                    last.coverage_amount = coverage
                    last.premium = premium
                if txt:
                    merged = (last.product + " " + txt).strip()
                    last.product = merged[:80]
            else:
                if txt:
                    pending.append(txt)
                if wrap_amts:
                    pending_amts.extend(wrap_amts)
    return out
