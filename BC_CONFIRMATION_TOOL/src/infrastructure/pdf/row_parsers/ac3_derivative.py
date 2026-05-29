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


def parse_ac3(block: str, bc_no: str, bank: str) -> list[Derivative]:
    # 의미 있는 줄만 수집 (noise·header·page-marker 제외)
    currency = None
    amounts: list[Decimal] = []
    dates = []
    text_tokens: list[str] = []
    instr_kw: str | None = None

    for raw in block.splitlines():
        s = raw.strip()
        if not s or is_noise(s) or _is_header(s) or _PAGE_RE.match(s):
            continue
        t = tokenize_row(s)
        if t.currency and currency is None:
            currency = t.currency
        amounts.extend(t.amounts)
        dates.extend(t.dates)
        text_tokens.extend(t.text_tokens)
        if instr_kw is None:
            instr_kw = _has_instrument(t.text_tokens)

    # 파생상품 키워드가 없으면(무거래 블록 등) 레코드 없음
    if instr_kw is None:
        return []

    # instrument = 키워드 (+ 인접 텍스트). 'RR:' 같은 환율 라벨 토큰은 제외.
    instr_parts = [w for w in text_tokens
                   if any(kw in w for kw in _INSTR_KW)]
    instrument = (" ".join(instr_parts) or instr_kw)[:40]

    # 날짜: 최초=거래일, 두 번째=만기
    dates_sorted = sorted(dates)
    contract_date = dates_sorted[0] if dates_sorted else None
    maturity = dates_sorted[1] if len(dates_sorted) >= 2 else None
    if contract_date is None:
        # 거래일이 없으면 신뢰 불가 — 레코드 생성하지 않음 (AUDIT: 추측 금지)
        return []

    # 금액 매핑 (위 가정 참조): 큰 금액 = KRW측 buy, 작은 외화 = sell
    amts_sorted = sorted(amounts, reverse=True)
    buy_amt = amts_sorted[0] if amts_sorted else Decimal("0")
    if len(amts_sorted) >= 2:
        sell_amt = amts_sorted[1]
        sell_ccy = currency or "USD"  # 검출된 외화
    else:
        # 금액 1개 → 분할하지 않음 (잘못 분할하느니 미할당)
        sell_amt = Decimal("0")
        sell_ccy = currency or "KRW"
    buy_ccy = "KRW"

    return [Derivative(
        bc_no=bc_no, bank=bank, instrument=instrument,
        contract_date=contract_date, maturity=maturity,
        buy_ccy=buy_ccy, buy_amt=buy_amt,
        sell_ccy=sell_ccy, sell_amt=sell_amt,
    )]
