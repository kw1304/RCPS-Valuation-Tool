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

=== buy/sell 매핑 가정 (중요) ===
wrap 된 텍스트에서 매입/매도 통화·금액 컬럼을 신뢰성 있게 분리할 수 없다(컬럼 헤더가
매입통화·매도통화·매입금액·매도금액을 명시하지만 데이터 줄에서 어느 금액이 어느 컬럼인지
물리적 위치만으로는 모호). AUDIT 도구이므로 잘못된 매입/매도 분할을 지어내지 않는다.
인코딩한 가정:
  - buy_ccy = "KRW" (default), buy_amt = KRW측 큰 notional (예: 13,416,000,000)
  - sell_ccy = 검출된 외화(예: USD), sell_amt = 작은 외화 notional (예: 10,000,000)
이 가정으로 confident 매핑이 안 되면(금액 1개뿐 등) 가장 큰 금액을 buy_amt 에 넣고
sell_amt=0 으로 둔다(잘못 분할하느니 미할당). contract_date=최초 날짜, maturity=다른 날짜.
"""
import re
from decimal import Decimal
from src.domain.ac_models import Derivative
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

# 파생상품 종류 키워드
_INSTR_KW = ("선물환", "선물", "스왑", "옵션", "FX", "forward", "swap", "option", "Forward", "Swap", "Option")
# 헤더 줄 식별 키워드
_HEADER_KW = ("거래종류", "거래일", "매입통화", "매도통화", "만기일", "한도액",
              "평가금액", "매입금액", "매도금액", "환율")
# 페이지 마커 (1/6, 2/6 …)
_PAGE_RE = re.compile(r"^\d+\s*/\s*\d+$")


def _is_header(s: str) -> bool:
    return any(k in s for k in _HEADER_KW)


def _has_instrument(toks: list[str]) -> str | None:
    for tok in toks:
        for kw in _INSTR_KW:
            if kw in tok:
                return kw
    return None


# notional 최소 단위: 절댓값 1000 미만 금액은 deal notional 이 아니다(rate·소수 leak).
_MIN_NOTIONAL = Decimal("1000")


class _PendingDeriv:
    """문서 순서대로 누적되는 하나의 파생상품 후보."""
    __slots__ = ("instr_parts", "instr_kw", "currency", "amounts", "dates")

    def __init__(self) -> None:
        self.instr_parts: list[str] = []
        self.instr_kw: str | None = None
        self.currency: str | None = None
        self.amounts: list[Decimal] = []
        self.dates: list = []

    def is_complete(self) -> bool:
        """새 파생상품을 시작해도 될 만큼 완성형인가(instrument + 거래일)."""
        return self.instr_kw is not None and bool(self.dates)


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

    # 금액 매핑 (위 가정 참조): 큰 금액 = KRW측 buy, 작은 외화 = sell
    amts_sorted = sorted(notionals, reverse=True)
    buy_amt = amts_sorted[0] if amts_sorted else Decimal("0")
    if len(amts_sorted) >= 2:
        sell_amt = amts_sorted[1]
        sell_ccy = p.currency or "USD"  # 검출된 외화
    else:
        # 금액 1개(또는 0) → 분할하지 않음 (잘못 분할하느니 미할당)
        sell_amt = Decimal("0")
        sell_ccy = p.currency or "KRW"
    buy_ccy = "KRW"

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
        cur.dates.extend(t.dates)
        cur.instr_parts.extend(
            w for w in t.text_tokens if any(kw in w for kw in _INSTR_KW)
        )
        if cur.instr_kw is None:
            cur.instr_kw = line_kw

    out = [d for d in (_build(p, bc_no, bank) for p in pendings) if d is not None]
    return out
