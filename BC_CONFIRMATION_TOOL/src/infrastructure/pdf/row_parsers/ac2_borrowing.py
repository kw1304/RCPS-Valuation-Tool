"""AC2 차입금(대출) 파서 — 다은행 wrap 복구.

회신서 sec2 는 은행마다 컬럼이 물리적 줄로 다르게 wrap 된다. 핵심 불변(invariant):
각 대출은 **날짜(8자리)+이자율**을 가진 단 하나의 'detail 줄'을 가진다. 이 줄을 앵커로
삼고, 그 줄에서 약정한도액/대출금액(금액 컬럼)을 직접 읽거나, 인접한 위/아래 줄에서
복구해 붙인다.

은행별 레이아웃 (실측):
  국민  : detail 줄에 금액이 inline. 단, 한도가 위 줄에 단독으로 wrap 되기도
          (`14,500,000,000.0` 위 + detail `... 0.00 ...` + `0` 아래 = 14,500,000,000.0).
          대출종류가 위 줄에 단독으로 오기도 (`외상매출채권전자대출`).
  우리  : detail 줄에 `0.00 0` inline (한도=0, 대출금액=0). 종류는 위(`B2B PLUS 대출 기업운`)
          + 아래(`전외상`) 로 쪼개짐.
  하나  : 금액이 detail 줄 위/아래로 쪼개짐. 위 줄 = `(KRW)7,000,000, (KRW)7,000,000,`
          (한도·대출금액 2컬럼 prefix), 아래 줄 = `000 000` (suffix). → `7,000,000,000`.
  신한  : detail 줄에 `KRW KRW` 만, 실금액은 아래 줄 (`... 12,800,000,000 12,800,000,000`).
          종류는 위(`<기운>일반자금대출(일`)+아래(`시상환)`).
  산업  : detail 줄에 `KRW 0` (대출금액=0), 한도는 위 `KRW`+아래 `20000000000` 로 쪼개짐.

전략:
  1) currency prefix((KRW)/(USD)/선행 KRW/USD) 분리, prefix 만 남은 토큰 제거.
  2) 'digit,' 로 끝나는 조각 + 다음 줄 선행 숫자 조각 = 한 숫자로 재결합.
  3) detail 줄 식별 → 위/아래 줄에서 금액·종류 조각을 수집해 detail 에 귀속.
  4) 금액 분류: rate-shaped(소수점 有 & <1000) 는 금액 금지. >=1000 또는 명시적 0 만 금액.
"""
import re
from decimal import Decimal, InvalidOperation
from src.domain.ac_models import Borrowing
from src.infrastructure.pdf.row_parsers.base import (
    is_noise, _DATE_8, _ymd, _CCY_SET,
)

# contract_type 으로 허용하지 않는 헤더/합계/은행명 토큰
_BANK_NAMES = {"우리", "국민", "신한", "산업", "하나", "KEB하나", "기업", "농협",
               "수출입", "한국수출입", "아이엠뱅크", "한국증권금융", "수협", "씨티", "SC제일"}
_HEADER_TOKENS = {
    "금액", "이자", "대출", "종류", "약정한도액", "대출금액", "연이율",
    "최종이자지급일", "최종만기일", "상환방법", "담보", "보증", "및", "관련약정",
    "총", "한도액", "합계", "소계", "총계", "은행",
}
_REPAY_KW = ("상환",)
_COLLAT_KW = ("담보", "보증", "부동산", "유가증권", "신용")

# 통화 prefix: (KRW) / (USD) / 선행 KRW/USD 등
_CCY_PREFIX = re.compile(r"^\((KRW|USD|EUR|JPY|CNY|HKD|GBP|AUD|SGD|CNH|CNH)\)")
_LEAD_CCY = re.compile(r"^(KRW|USD|EUR|JPY|CNY|HKD|GBP|AUD|SGD|CNH)")
# 순수 숫자 조각(천단위 콤마·소수 허용). prefix 제거 후 검사.
_NUM_FRAG = re.compile(r"^\d[\d,]*(?:\.\d+)?$")
# AC2 이자율: 콤마 없는 소수, 정수부 1~3자리(0.00, 4.51, 4.8, 4.17000, 3.815).
# base._RATE 는 소수 3~5자리만 허용해 신한 '4.51'/하나 '4.8' 를 놓치므로 별도 정의.
# 콤마가 있으면 금액(18,720,900.00)이므로 rate 아님.
_AC2_RATE = re.compile(r"^\d{1,3}\.\d{1,5}$")
# 8자리 날짜 형태이지만 콤마 없는 큰 무콤마 정수(산업 20000000000)는 금액일 수 있어
# 별도로 다룬다.


def _strip_ccy(tok: str):
    """토큰에서 통화 prefix 분리 → (currency|None, 나머지)."""
    m = _CCY_PREFIX.match(tok)
    if m:
        return m.group(1), tok[m.end():]
    m = _LEAD_CCY.match(tok)
    if m and tok[m.end():m.end() + 1] in ("", *"0123456789"):
        # 'KRW12,800,000,000' 또는 'KRW' 단독
        return m.group(1), tok[m.end():]
    return None, tok


def _is_rate_shaped(val: Decimal) -> bool:
    """소수점이 있고 절대값 < 1000 → 이자율로 본다(금액 금지)."""
    return abs(val) < Decimal("1000") and val != val.to_integral_value()


def _to_dec(s: str):
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _detail_idx(toks: list[str]) -> bool:
    """이 줄이 detail 줄인가 = 8자리 날짜 AND 이자율(콤마없는 소수) 토큰을 모두 가진다.

    base._RATE(소수 3~5자리)는 신한 '4.51'·하나 '4.8' 를 놓치므로 _AC2_RATE 로 판정.
    8자리 날짜(20250627)는 _AC2_RATE 에 안 걸린다(소수점 없음)."""
    has_date = any(_DATE_8.match(t) for t in toks)
    has_rate = any(_AC2_RATE.match(t) and "," not in t for t in toks)
    return has_date and has_rate


class _Frag:
    """줄 단위 전처리 결과."""
    def __init__(self, raw: str):
        self.raw = raw
        self.currency = None
        self.tokens: list[str] = []   # 통화 prefix 제거 후 토큰
        self._build()

    def _build(self):
        for tok in self.raw.split():
            ccy, rest = _strip_ccy(tok)
            if ccy and self.currency is None:
                self.currency = ccy
            if rest:
                self.tokens.append(rest)
            # rest 가 빈 문자열이면(=통화 prefix 만 있던 토큰) 토큰 제거


def _is_wellformed_amount(t: str) -> bool:
    """천단위 콤마 그룹이 정상인 '완성' 숫자인가.
    정상: '7,000,000,000', '1,000,000,000.00', '20000000000'(무콤마), '0'.
    불완성: '21,870,00'(끝 그룹 2자리), '7,000,000,'(끝 콤마) → wrap 조각.
    """
    s = t
    if s.endswith(","):
        return False
    intpart = s.split(".")[0]
    if "," not in intpart:
        return intpart.isdigit()
    groups = intpart.split(",")
    if any(not g.isdigit() for g in groups):
        return False
    if len(groups[0]) < 1 or len(groups[0]) > 3:
        return False
    return all(len(g) == 3 for g in groups[1:])


def _num_frag_tokens(frag: "_Frag") -> list[str]:
    """줄에서 숫자(조각 포함) 토큰만 순서대로. 텍스트/날짜는 제외."""
    return [t for t in frag.tokens if _NUM_FRAG.match(t)]


def _classify_amounts(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    """복구된 금액 후보 → (한도, 대출금액). rate-shaped 는 이미 제외돼 들어옴.
    2개면 첫째=한도, 둘째=대출금액. 1개면 한도=그값, 대출금액=0 (한도 컬럼 우선).
    0개면 (0,0)."""
    if not values:
        return Decimal("0"), Decimal("0")
    if len(values) >= 2:
        return values[0], values[1]
    return values[0], Decimal("0")


def parse_ac2(block: str, bc_no: str, bank: str) -> list[Borrowing]:
    raw_lines = [l.strip() for l in block.splitlines() if l.strip()]
    frags = [_Frag(l) for l in raw_lines]

    out: list[Borrowing] = []
    n = len(frags)
    for i, f in enumerate(frags):
        toks = f.tokens
        if not _detail_idx(toks):
            continue
        if is_noise(f.raw):
            continue

        prev = frags[i - 1] if i - 1 >= 0 else None
        nxt = frags[i + 1] if i + 1 < n else None

        # ---- 1. detail 줄에서 inline 금액/날짜/이자율/텍스트 추출 ----
        # 컬럼 순서: [약정한도액] [대출금액] [대출일] [최종만기일] [연이율] [최종이자지급일] ...
        # 따라서 '첫 날짜 이전'의 숫자만 금액 후보, '첫 날짜 이후'의 콤마없는 소수는 이자율.
        currency = f.currency
        dates, rate = [], None
        inline_nums: list[Decimal] = []   # 첫 날짜 이전의 금액 후보(0 포함, 순서 유지)
        # inline_nums 와 1:1 정렬된 '원시' 금액 토큰(불완성 wrap 판정용).
        # 명시적 0(rate 0.00 등)에는 raw 토큰이 없어 "0" 을 채워 정렬 유지.
        inline_amt_frags: list[str] = []
        detail_text: list[str] = []       # 첫 날짜 이전의 텍스트 = 대출종류 후보
        post_text: list[str] = []         # 첫 날짜 이후의 텍스트 = 상환방법/담보·보증
        seen_date = False
        for t in toks:
            if _DATE_8.match(t):
                d = _ymd(t)
                if d:
                    dates.append(d)
                seen_date = True
                continue
            # 콤마 없는 소수 = 이자율 후보. 첫 날짜 이후의 비-0 값을 rate 로 채택.
            if _AC2_RATE.match(t) and "," not in t:
                v = _to_dec(t)
                if seen_date:
                    if rate is None:
                        rate = v
                else:
                    # 날짜 이전의 소수: 0.00 은 대출금액 0, 그 외 rate-shaped 소수는 버림.
                    if v == 0:
                        inline_nums.append(Decimal("0"))
                        inline_amt_frags.append("0")
                continue
            if t in _CCY_SET:
                if currency is None:
                    currency = t
                continue
            v = _to_dec(t) if _NUM_FRAG.match(t) else None
            if v is not None:
                if seen_date:
                    # 날짜 이후의 정수(예 신한 404510514, 하나 00000000) = 약정/계좌 ref.
                    # 금액 아님 → 텍스트로도 안 넣고 버린다.
                    continue
                if _is_rate_shaped(v):
                    if v == 0:
                        inline_nums.append(Decimal("0"))
                        inline_amt_frags.append("0")
                    continue
                inline_nums.append(v)
                inline_amt_frags.append(t)
            else:
                # 첫 날짜 이전 텍스트 = 종류, 이후 텍스트 = 상환방법/담보.
                if seen_date:
                    post_text.append(t)
                else:
                    detail_text.append(t)

        # ---- 1b. detail 줄 inline 금액이 줄바꿈으로 잘린 wrap 조각인지 ----
        # 좌표 재구성 후 하나/산업식 레이아웃은 금액 prefix 가 detail 줄에 inline
        # 으로 들어오되 마지막 자리 그룹이 다음 줄로 잘린다
        # (예 detail '(KRW)7,000,000,' + 아래 '000' = 7,000,000,000).
        # inline 금액 조각이 '완성되지 않은'(끝 콤마 또는 끝 그룹 != 3자리) 형태이고,
        # 아래 줄에 선행 숫자 조각이 있으면 위치별로 결합해 완성한다.
        if inline_amt_frags and any(not _is_wellformed_amount(t) for t in inline_amt_frags):
            below = _num_frag_tokens(nxt) if (nxt is not None and not _has_dates(nxt)) else []
            if below:
                completed: list[Decimal] = []
                m = min(len(inline_amt_frags), len(below))
                for k in range(len(inline_amt_frags)):
                    pre = inline_amt_frags[k]
                    if not _is_wellformed_amount(pre) and k < m:
                        cand = pre + below[k]
                        cv = _to_dec(cand)
                        if _is_wellformed_amount(cand) and cv is not None:
                            completed.append(cv)
                            continue
                    completed.append(inline_nums[k])
                inline_nums = completed

        # ---- 2. 금액 컬럼 복구: detail 줄 우선, 부족하면 위/아래 줄에서 ----
        # detail 줄에 실금액(>=1000)이 충분하면 그대로 사용.
        big_inline = [v for v in inline_nums if v >= 1000]
        # inline 에 명시적 0 이 몇 개인지(우리/산업 대출금액 0)
        zero_inline = [v for v in inline_nums if v == 0]

        amounts: list[Decimal] = []
        if len(big_inline) >= 1:
            # 국민: 한도+대출금액 둘 다 inline 이거나, 한도만 위 줄 wrap.
            amounts = inline_nums[:]  # 0 포함 순서 유지
        else:
            # 금액이 detail 줄에 없음(하나/신한/산업) → 위/아래 줄에서 복구.
            recovered = _recover_wrapped_amounts(prev, nxt)
            if recovered:
                amounts = recovered
            else:
                amounts = inline_nums[:]

        # rate-shaped 제거(혹시 남았으면) + None 제거, 순서 유지
        clean: list[Decimal] = []
        for v in amounts:
            if v is None:
                continue
            if v != 0 and v < 1000 and _is_rate_shaped(v):
                continue
            clean.append(v)
        limit, balance = _classify_amounts(clean)

        # 한도/대출금액 둘 다 0 인데 inline 에 명시적 0 이 있었으면 0 유지(우리).
        # (이미 0 이므로 추가 작업 불필요)

        # ---- 3. contract_type 복구 ----
        contract_type = _build_type(detail_text, prev, nxt)

        # ---- 4. 상환방법/담보 (첫 날짜 이후 텍스트에서) ----
        repayment = next((w for w in post_text if any(k in w for k in _REPAY_KW)), None)
        collateral_toks = [w for w in post_text if any(k in w for k in _COLLAT_KW)
                           and not any(k in w for k in _REPAY_KW)]
        collateral = " ".join(collateral_toks) if collateral_toks else None

        contract_date = dates[0] if len(dates) >= 1 else None
        maturity = dates[1] if len(dates) >= 2 else None
        last_int = dates[2] if len(dates) >= 3 else None

        out.append(Borrowing(
            bc_no=bc_no, bank=bank,
            contract_type=(contract_type or "")[:60],
            limit_ccy=currency or "KRW", limit_amt=limit,
            balance_ccy=currency or "KRW", balance=balance,
            contract_date=contract_date, maturity=maturity,
            rate=rate, last_interest_date=last_int,
            repayment=repayment, collateral=collateral,
        ))
    return out


def _recover_wrapped_amounts(prev: "_Frag | None", nxt: "_Frag | None") -> list[Decimal]:
    """detail 줄 위/아래에서 약정한도액·대출금액을 복구한다.

    케이스:
      하나: 위='7,000,000,'(+'7,000,000,')  아래='000'(+'000')  → 7,000,000,000 (x2 컬럼)
      신한: 위=종류텍스트 only            아래='12,800,000,000 12,800,000,000'
      산업: 위='(없음, KRW prefix 만)'      아래='20000000000'
    """
    above = _num_frag_tokens(prev) if (prev is not None and not _has_dates(prev)) else []
    below = _num_frag_tokens(nxt) if (nxt is not None and not _has_dates(nxt)) else []

    # (b) 아래 줄에 그대로 완성 금액(>=1000)이 있다 (신한 '12,800,000,000 12,800,000,000',
    #     산업 '20000000000'). 우선 채택.
    below_ok = [v for t in below if _is_wellformed_amount(t)
                for v in [_to_dec(t)] if v is not None and v >= 1000]
    if below_ok:
        return below_ok

    # (c) 위 줄에 완성 금액 (국민형 wrap 한도).
    above_ok = [v for t in above if _is_wellformed_amount(t)
                for v in [_to_dec(t)] if v is not None and v >= 1000]
    if above_ok:
        return above_ok

    # (a) 하나 패턴: 위·아래 모두 '불완성' 숫자 조각 → 위[k] + 아래[k] 위치별 결합.
    #     위='7,000,000,'/'21,870,00', 아래='000'/'0,000'.
    if above and below:
        m = min(len(above), len(below))
        joined = []
        for k in range(m):
            cand = above[k] + below[k]
            if _is_wellformed_amount(cand):
                v = _to_dec(cand)
                if v is not None and v >= 1000:
                    joined.append(v)
        if joined:
            return joined

    return []


def _has_dates(frag: "_Frag | None") -> bool:
    if frag is None:
        return False
    return any(_DATE_8.match(t) for t in frag.tokens)


def _clean_type_token(t: str) -> str | None:
    """type 후보 토큰 정제: 헤더/은행명/숫자/날짜/통화 거르고 유효하면 반환."""
    if not t:
        return None
    # 순수 숫자/콤마/소수/날짜 토큰(금액·날짜·ref)은 제거. 단 'B2B'·'<기운>' 처럼
    # 글자가 섞인 상품명 토큰은 유지(B2B 의 '2' 때문에 통째로 버리면 안 됨).
    if _NUM_FRAG.match(t) or _DATE_8.match(t):
        return None
    if any(ch.isdigit() for ch in t) and not any(ch.isalpha() or ('가' <= ch <= '힣') for ch in t):
        return None
    if t in _HEADER_TOKENS or t in _BANK_NAMES:
        return None
    if t.endswith("은행"):
        return None
    if t in _CCY_SET:
        return None
    # '대출/여신/한도' 로 끝나는 토큰은 진짜 상품명 → 상환/담보어 포함돼도 종류로 인정
    #   (예 '기업운전일반분할상환대출' 은 '상환' 을 포함하지만 종류임)
    is_product = t.endswith("대출") or t.endswith("여신") or "대출" in t
    if not is_product:
        if any(k in t for k in _REPAY_KW):
            return None
        # 담보·보증·부동산·유가증권·보증인 등은 종류 아님(별도 collateral 컬럼)
        if any(k in t for k in _COLLAT_KW) or "보증인" in t:
            return None
    # 참조/항목참조 등 약정 ref 안내어는 종류 아님
    if "참조" in t or "항목" in t:
        return None
    return t


# type 소스로 쓰면 안 되는 footer/안내 줄 마커
_TYPE_STOP = ("확인자", "소속", "성명", "참조", "면책", "유의", "조회기준")


def _type_tokens_from(frag: "_Frag | None") -> list[str]:
    if frag is None:
        return []
    if _has_dates(frag):
        return []   # detail/다른 대출 줄은 type 소스로 쓰지 않음
    if is_noise(frag.raw) or any(k in frag.raw for k in _TYPE_STOP):
        return []   # 확인자/안내 footer 는 종류가 아님
    out = []
    for t in frag.tokens:
        ct = _clean_type_token(t)
        if ct:
            out.append(ct)
    return out


def _build_type(detail_text: list[str], prev: "_Frag | None", nxt: "_Frag | None") -> str:
    """대출종류 재조립: 위 줄(종류 머리) + detail 줄 텍스트 + 아래 줄(종류 꼬리).

    국민: detail 텍스트에 종류 inline. 우리: 위+아래. 신한: 위+아래. 하나/산업: detail inline.
    """
    head = _type_tokens_from(prev)
    mid = [t for t in (_clean_type_token(x) for x in detail_text) if t]
    tail = _type_tokens_from(nxt)
    parts = head + mid + tail
    if not parts:
        # 최후: detail_text 의 첫 비-상환/비-담보 토큰
        for x in detail_text:
            if not any(k in x for k in _REPAY_KW) and not any(k in x for k in _COLLAT_KW):
                return x
        return detail_text[0] if detail_text else ""
    # 한국어 종류는 보통 공백 없이 이어지지만 'B2B PLUS 대출 기업운전외상' 처럼
    # 공백 분절이 의미를 가짐 → 공백으로 join.
    return " ".join(parts)
