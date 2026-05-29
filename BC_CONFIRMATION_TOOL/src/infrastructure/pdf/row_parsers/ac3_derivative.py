"""AC3 파생상품 파서. 선물환(FX forward)·스왑·옵션 등.

실제 회신서 레이아웃 (은행 회신서, 선물환):
헤더: 거래종류 / 거래일 / 매입통화·매도통화 / 만기일 / 한도액 / 평가금액 / 매입금액 / 매도금액 / 환율
데이터는 컬럼이 물리적 줄로 wrap 된다:
  USD                                                      <- 통화 (단독 줄)
  선물 20240903 13,416,000,000.00 20240909 0.0000 RR: 4.410 <- 종류+거래일+금액+만기+평가+환율
  10,000,000.00                                            <- 외화 notional (단독 줄)

전략: 블록 내 noise/header/page-marker 줄을 제외한 모든 줄을 토큰화하여 합산한다.
파생상품 섹션은 통상 행이 1개뿐이라 단일 레코드를 만든다. instrument 키워드가
여러 개 나오면(드묾) 행 분할이 필요하지만, 실제 회신서에서는 1행이 대부분이다.

행 분할: 의미 있는 줄을 문서 순서대로 스캔하며 토큰을 누적한다. instrument 키워드를
만났을 때 이미 pending 파생상품이 완성형(instrument+거래일)이면 새 파생상품을 시작한다.
각 파생상품 레코드는 자신의 누적 토큰만 사용한다(BUG A: 토큰 풀링 금지).
날짜는 정렬하지 않고 문서 순서대로 부여한다(BUG B: 최초=거래일, 다음=만기).
금액은 절댓값 1000 미만(rate·소수 등)을 notional 사이징 전에 버린다(BUG C).

=== buy/sell 매핑 (통화 leg 기반) ===
wrap 된 텍스트에서 컬럼 위치만으로는 매입/매도·평가금액을 구분할 수 없다. 그러나
통화스왑·선물환의 두 notional 은 서로 다른 통화의 leg 이며, 그 금액 비율이 합리적
FX 환율 band 안에 든다는 강건한 신호가 있다(예: KRW 13,890,000,000 / USD 10,000,000
= 1389 ≈ KRW/USD 시세). 이를 이용해:
  - 외화(USD 등) 금액과 KRW 금액 중, 비율이 합리적 FX band(_FX_LO~_FX_HI) 안에 드는
    (KRW_leg, 외화_leg) 쌍을 — 가장 큰 외화 금액 우선으로 — 선택한다.
  - buy = KRW leg(buy_ccy=KRW), sell = 외화 leg(sell_ccy=USD 등). 외화 통화를 보존한다.
  - 평가금액·한도액 등 leg 에 속하지 않는 금액은 buy/sell 에서 제외한다(특히 평가금액을
    notional 로 오인하지 않는다 — AUDIT).
FX-consistent 쌍을 못 찾으면(외화 leg 부재 등) 통화 태깅된 금액 → 없으면 가장 큰 금액을
fallback 으로 buy 에 넣고 sell=0 으로 둔다(잘못 분할하느니 미할당). contract_date=최초
날짜, maturity=다른 날짜.
"""
import re
from decimal import Decimal
from src.domain.ac_models import Derivative
from src.infrastructure.pdf.row_parsers.base import (
    tokenize_row, is_noise, _CCY_SET, _CCY_NORMALIZE, _NUM, _RATE, _PAREN, _DATE_8,
    _dec,
)

# 파생상품 종류 키워드
_INSTR_KW = ("선물환", "선물", "스왑", "옵션", "FX", "forward", "swap", "option", "Forward", "Swap", "Option")
# 헤더 줄 식별 키워드
_HEADER_KW = ("거래종류", "거래일", "매입통화", "매도통화", "만기일", "한도액",
              "평가금액", "매입금액", "매도금액", "환율")
# 페이지 마커 (1/6, 2/6 …)
_PAGE_RE = re.compile(r"^\d+\s*/\s*\d+$")


def _is_header(s: str) -> bool:
    return any(k in s for k in _HEADER_KW)


def _fx_tagged_amounts(row: str) -> list[tuple[str, Decimal]]:
    """줄을 문서 순서대로 스캔하여 '외화(비-KRW) 통화 태그 직후의 금액'을 수집한다.

    예: 'USD 1,300,000 KRW USD 10,000,000' → [('USD', 1300000), ('USD', 10000000)].
    KRW 직후 금액이나 통화 태그 없는 bare 금액(평가금액 wrap line 등)은 포함하지 않는다.
    tokenize_row 와 동일한 토큰 분류 규칙을 쓰되 (통화→금액) 인접만 기록한다.
    """
    out: list[tuple[str, Decimal]] = []
    pending_ccy: str | None = None
    for tok in row.split():
        if tok in _CCY_SET:
            pending_ccy = _CCY_NORMALIZE.get(tok, tok)
        elif _DATE_8.match(tok):
            pending_ccy = None
        elif _RATE.match(tok):
            pending_ccy = None
        elif _PAREN.match(tok):
            continue
        elif _NUM.match(tok):
            v = _dec(tok)
            if v is not None and pending_ccy is not None and pending_ccy != "KRW":
                out.append((pending_ccy, v))
            # 통화 태그는 한 금액에만 적용(다음 금액은 새 태그가 필요)
            pending_ccy = None
        else:
            # 텍스트 토큰(RECEIVE 등)은 직전 통화 태그를 소비하지 않고 통과
            continue
    return out


def _has_instrument(toks: list[str]) -> str | None:
    for tok in toks:
        for kw in _INSTR_KW:
            if kw in tok:
                return kw
    return None


# notional 최소 단위: 절댓값 1000 미만 금액은 deal notional 이 아니다(rate·소수 leak).
_MIN_NOTIONAL = Decimal("1000")

# 합리적 KRW/외화 FX 환율 band. KRW/USD≈1300, KRW/EUR≈1500, KRW/JPY≈9, KRW/CNY≈190 …
# 통화스왑·선물환의 두 leg(KRW vs 외화) 금액 비율이 이 band 안에 들면 notional 쌍으로 본다.
# 평가금액/한도액은 이 비율을 만족하지 않으므로 자연히 배제된다.
_FX_LO = Decimal("5")        # JPY 등 저단가 통화 하한
_FX_HI = Decimal("3000")     # 고단가 통화 상한 (여유 폭)


class _PendingDeriv:
    """문서 순서대로 누적되는 하나의 파생상품 후보."""
    __slots__ = ("instr_parts", "instr_kw", "currency", "amounts", "dates",
                 "fx_amounts")

    def __init__(self) -> None:
        self.instr_parts: list[str] = []
        self.instr_kw: str | None = None
        self.currency: str | None = None
        self.amounts: list[Decimal] = []
        # 외화(비-KRW) 통화 태그 직후에 등장한 금액들: [(ccy, amount), ...]
        self.fx_amounts: list[tuple[str, Decimal]] = []
        self.dates: list = []

    def is_complete(self) -> bool:
        """새 파생상품을 시작해도 될 만큼 완성형인가(instrument + 거래일)."""
        return self.instr_kw is not None and bool(self.dates)


def _pick_fx_consistent_legs(
    notionals: list[Decimal],
    fx_legs: list[tuple[str, Decimal]],
) -> tuple[Decimal, str, Decimal] | None:
    """(KRW_leg, 외화_ccy, 외화_leg) 을 반환. FX-consistent 쌍이 없으면 None.

    외화 leg 후보(통화 태깅된 금액)와 KRW leg 후보(전체 notional) 중, 금액 비율이
    합리적 FX band 안에 드는 쌍을 찾는다. 평가금액·한도액은 이 비율을 만족하지 않아
    자연히 배제된다. 여러 쌍이 가능하면 외화 금액이 가장 큰(=실제 거래 notional 일
    가능성이 높은) 쌍을 우선한다.
    """
    best: tuple[Decimal, str, Decimal] | None = None
    best_fx = Decimal("-1")
    # 외화 금액 큰 순서로 검토 → 가장 큰 외화 notional 우선
    for fx_ccy, fx_amt in sorted(fx_legs, key=lambda x: x[1], reverse=True):
        if fx_amt <= 0:
            continue
        for krw_amt in notionals:
            if krw_amt <= 0 or krw_amt == fx_amt:
                continue
            ratio = krw_amt / fx_amt
            if _FX_LO <= ratio <= _FX_HI and fx_amt > best_fx:
                best = (krw_amt, fx_ccy, fx_amt)
                best_fx = fx_amt
                break  # 이 외화 leg 에 대한 최적 KRW leg 확정
    return best


def _build(p: "_PendingDeriv", bc_no: str, bank: str) -> Derivative | None:
    if p.instr_kw is None:
        return None
    instrument = (" ".join(p.instr_parts) or p.instr_kw)[:40]

    # 날짜: 문서 순서대로 — 최초=거래일, 다음=만기 (정렬 금지, BUG B)
    contract_date = p.dates[0] if p.dates else None
    maturity = p.dates[1] if len(p.dates) >= 2 else None
    if contract_date is None:
        # 거래일이 없으면 신뢰 불가 — 레코드 생성하지 않음 (AUDIT: 추측 금지)
        return None

    # rate·소수 leak 제거: notional 사이징 전에 1000 미만 금액 버림 (BUG C)
    notionals = [a for a in p.amounts if abs(a) >= _MIN_NOTIONAL]
    fx_legs = [(c, a) for (c, a) in p.fx_amounts if abs(a) >= _MIN_NOTIONAL]

    leg = _pick_fx_consistent_legs(notionals, fx_legs)
    if leg is not None:
        # FX-consistent 쌍: KRW leg = buy, 외화 leg = sell (외화 통화 보존)
        krw_amt, fx_ccy, fx_amt = leg
        buy_ccy, buy_amt = "KRW", krw_amt
        sell_ccy, sell_amt = fx_ccy, fx_amt
    else:
        # fallback: FX-consistent 쌍을 못 찾음 → 기존 가정 유지(통화 leg 보존을 위해
        # 통화 태깅이 명확하지 않은 wrap 레이아웃). 큰 금액=KRW측 buy, 작은 금액=외화 sell.
        # (평가금액 컬럼이 없는 단순 선물환/스왑 회신서. 통화 태깅된 외화 금액 정보가
        # 없으므로 잘못 분할하느니 기존 규칙을 따른다.)
        amts_sorted = sorted(notionals, reverse=True)
        buy_ccy = "KRW"
        buy_amt = amts_sorted[0] if amts_sorted else Decimal("0")
        if len(amts_sorted) >= 2:
            sell_amt = amts_sorted[1]
            sell_ccy = p.currency or "USD"  # 검출된 외화
        else:
            # 금액 1개(또는 0) → 분할하지 않음 (잘못 분할하느니 미할당)
            sell_amt = Decimal("0")
            sell_ccy = p.currency or "KRW"

    return Derivative(
        bc_no=bc_no, bank=bank, instrument=instrument,
        contract_date=contract_date, maturity=maturity,
        buy_ccy=buy_ccy, buy_amt=buy_amt,
        sell_ccy=sell_ccy, sell_amt=sell_amt,
    )


def parse_ac3(block: str, bc_no: str, bank: str) -> list[Derivative]:
    # 의미 있는 줄을 문서 순서대로 스캔하며 파생상품 단위로 분할 (BUG A)
    pendings: list[_PendingDeriv] = []
    cur: _PendingDeriv | None = None

    for raw in block.splitlines():
        s = raw.strip()
        if not s or is_noise(s) or _is_header(s) or _PAGE_RE.match(s):
            continue
        t = tokenize_row(s)
        line_kw = _has_instrument(t.text_tokens)

        # 새 instrument 키워드 + 직전 파생상품이 완성형이면 새 파생상품 시작
        if line_kw is not None and cur is not None and cur.is_complete():
            cur = None
        if cur is None:
            cur = _PendingDeriv()
            pendings.append(cur)

        if t.currency and cur.currency is None:
            cur.currency = t.currency
        cur.amounts.extend(t.amounts)
        cur.fx_amounts.extend(_fx_tagged_amounts(s))
        cur.dates.extend(t.dates)
        cur.instr_parts.extend(
            w for w in t.text_tokens if any(kw in w for kw in _INSTR_KW)
        )
        if cur.instr_kw is None:
            cur.instr_kw = line_kw

    out = [d for d in (_build(p, bc_no, bank) for p in pendings) if d is not None]
    return out
