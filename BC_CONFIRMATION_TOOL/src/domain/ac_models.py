from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")
    bc_no: str
    bank: str


class FinancialAsset(_Base):              # AC1
    asset_type: Literal["deposit", "stock", "bond", "fund", "other"]
    category: Literal["bank", "securities"] = "bank"   # 은행 예금 vs 증권사 자산
    product: str                              # 금융상품 종류
    account_no: str | None = None             # 계좌번호
    currency: str = "KRW"                     # 통화
    quantity: Decimal | None = None           # 수량 (주식·채권)
    face_amount: Decimal | None = None        # 액면금액 (채권)
    balance: Decimal                          # 금액 (잔액)
    # 은행 예금 전용
    interest_rate: Decimal | None = None      # 이자율
    last_interest_date: date | None = None    # 최종이자지급일
    maturity: date | None = None              # 만기일
    withdrawal_limit: str | None = None       # 인출제한 등
    # 증권사 자산 전용
    deposit_money: Decimal | None = None      # 예수금
    margin_deposit: Decimal | None = None     # 신용설정 보증금
    receivable: Decimal | None = None         # 미수금액
    collateral_restriction: str | None = None # 담보제공·처분제한
    # 공통
    company_account: str | None = None        # 회사 계정과목명
    open_date: date | None = None             # (legacy)


class SecurityDetail(_Base):              # AC1 ③ 유가증권 종목별 상세
    account_no: str
    ticker_name: str                      # 종목명 (예: 코스맥스, 코스맥스엔비티)
    quantity: Decimal | None = None       # 수량
    face_value: Decimal | None = None     # 액면금액
    base_price: Decimal | None = None     # 기준가
    valuation: Decimal | None = None      # 평가액
    maturity: date | None = None
    collateral_qty: Decimal | None = None # 담보·질권 설정 수량
    collateral_type: str | None = None    # 질권설정·담보제공 등


class Borrowing(_Base):                   # AC2
    contract_type: str                    # 대출종류
    limit_ccy: str = "KRW"                # 한도통화
    limit_amt: Decimal = Decimal("0")     # 한도금액
    balance_ccy: str = "KRW"              # 잔액통화
    balance: Decimal = Decimal("0")       # 대출금액(잔액)
    contract_date: date | None = None     # 대출일
    maturity: date | None = None          # 최종만기일
    rate: Decimal | None = None           # 연이자율
    last_interest_date: date | None = None  # 최종이자지급일
    repayment: str | None = None          # 상환방법
    collateral: str | None = None         # 담보·보증


class Derivative(_Base):                  # AC3
    instrument: str
    contract_date: date
    buy_ccy: str
    buy_amt: Decimal
    sell_ccy: str
    sell_amt: Decimal
    maturity: date | None = None


class Guarantee(_Base):                   # AC4
    guarantee_type: str
    limit_amt: Decimal
    limit_ccy: str = "KRW"
    balance: Decimal
    balance_ccy: str = "KRW"
    maturity: date | None = None


class Collateral(_Base):                  # AC5
    collateral_type: str
    creditor: str | None = None
    issuer: str | None = None
    book_amount: Decimal
    appraised_amount: Decimal | None = None
    priority: int | None = None


class BillCheck(_Base):                   # AC6
    kind: str
    count: int = 0
    balance: Decimal = Decimal("0")


class Insurance(_Base):                   # AC7
    product: str
    policy_no: str | None = None
    coverage_amount: Decimal | None = None
    premium: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None


class GeneralDeal(_Base):                 # AC8
    asset_type: str
    account_no: str | None = None
    deal_date: date | None = None
    deal_type: str | None = None
    outstanding: Decimal | None = None
    period: str | None = None
