"""AC7 보험 파서. 보험상품명·증권번호·부보금액·보험료·보험시작일·보험종료일.

실제 회신서 레이아웃 (손해보험 회신서) — wrap 된 컬럼 헤더 + wrap 된 영문 상품명:
  연간보험료 부보기간                                       <- 헤더 wrap
  보험의 종류 증권번호 부보금액                              <- 헤더 wrap
  보장성보험료                                              <- 헤더 wrap
  누적 적립금 해약환급금 연이자율 권리제한 비고               <- 헤더 wrap
  이외 시작 종료                                            <- 헤더 wrap (조각)
  및 사업비                                                 <- 헤더 wrap (조각)
  No Fault                                                 <- 상품명 wrap (선행)
  Compensation 20258450627 300,000,000 2,034,000 20251212 20261211 0 0  <- 정책행
  Insurance                                                <- 상품명 wrap (후행)
  KB업무용 20258440287 0 1,265,530 20251214 20261214 0 0     <- 정책행
한 정책 행(policy row)은 증권번호(10~13자리 순수 숫자) 보유로 식별한다.
tokenize_row 는 8~22자리 순수 숫자를 .account 에 넣으므로 policy_no = t.account.

상품명 누적기(accumulator):
  - 정책행 직전의 연속된 '순수 텍스트 줄'을 선행 상품명 조각으로 버퍼링한다.
  - 정책행을 만나면 (선행 버퍼 + 정책행 선행 텍스트)를 상품명으로 삼는다.
  - 정책행 직후의 순수 텍스트 줄(다음 정책행/헤더 전까지)은 영문 상품명의 후행
    wrap 조각으로 보고 직전 정책의 상품명에 append 한다 (예: 'Insurance').
  - header·noise 줄을 만나면 선행 버퍼를 비운다 (헤더 잔여 텍스트가 상품명에
    새지 않도록). AUDIT: 잘못된 상품명을 짓느니 깔끔하게 자른다.

부보금액·보험료 0 은 정상 값(예: KB업무용 부보 0)이므로 행을 버리지 않는다 —
증권번호가 있으면 실제 정책이다.
"""
import re
from src.domain.ac_models import Insurance
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

# 헤더 줄 식별 키워드 (이 단어를 포함하거나 조각 토큰이면 컬럼 헤더로 보고 스킵).
# 실제 회신서 헤더가 여러 줄로 wrap 되므로 조각 단어까지 폭넓게 포함한다.
_HEADER_KW = (
    "증권번호", "보험상품명", "보험의 종류", "부보금액", "보험료", "보험시작일",
    "보험종료일", "해약환급금", "보험기간", "부보기간", "보장성", "연간보험료",
    "적립금", "연이자율", "권리제한", "비고",
)
# 헤더 wrap 조각(단독 줄로 떨어진 헤더 단어들). 정확 일치로만 헤더 처리.
_HEADER_FRAGMENTS = {"이외", "시작", "종료", "및", "사업비", "누적", "적립금"}
# 증권번호: 순수 10~13자리 숫자 (콤마/하이픈 없음)
_POLICY_RE = re.compile(r"^\d{10,13}$")


def _is_header(s: str) -> bool:
    if any(k in s for k in _HEADER_KW):
        return True
    # 줄의 모든 토큰이 헤더 조각이면 헤더로 본다 (예: '이외 시작 종료', '및 사업비')
    toks = s.split()
    if toks and all(tok in _HEADER_FRAGMENTS for tok in toks):
        return True
    return False


def parse_ac7(block: str, bc_no: str, bank: str) -> list[Insurance]:
    out: list[Insurance] = []
    pending: list[str] = []   # 정책행 직전 상품명 wrap 조각 버퍼
    last: Insurance | None = None  # 직전 정책 (후행 wrap append 용)

    for raw in block.splitlines():
        s = raw.strip()
        if not s:
            continue
        if is_noise(s) or _is_header(s):
            # 헤더/noise → 선행 버퍼 비움(헤더 잔여 텍스트 누출 방지), 후행 append 중단
            pending = []
            last = None
            continue

        t = tokenize_row(s)
        is_policy = bool(t.account and _POLICY_RE.match(t.account))

        if is_policy:
            line_text = " ".join(t.text_tokens).strip()
            product = " ".join(pending + ([line_text] if line_text else [])).strip()
            pending = []
            if not product:
                product = "(미상)"
            amts = t.amounts
            rec = Insurance(
                bc_no=bc_no, bank=bank, product=product[:80],
                policy_no=t.account,
                coverage_amount=amts[0] if len(amts) >= 1 else None,
                premium=amts[1] if len(amts) >= 2 else None,
                start_date=t.dates[0] if len(t.dates) >= 1 else None,
                end_date=t.dates[1] if len(t.dates) >= 2 else None,
            )
            out.append(rec)
            last = rec
        else:
            txt = " ".join(t.text_tokens).strip()
            if not txt:
                continue
            # 숫자만 있는 줄(stray)은 상품명이 아니므로 버린다 (위에서 txt 비면 skip).
            if last is not None:
                # 직전 정책 직후의 텍스트 줄 = 영문 상품명 후행 wrap → append
                merged = (last.product + " " + txt).strip()
                last.product = merged[:80]
            else:
                # 다음 정책행을 기다리는 선행 wrap 조각
                pending.append(txt)
    return out
