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
    product: str
    account_no: str | None = None
    currency: str = "KRW"
    quantity: Decimal | None = None
    face_amount: Decimal | None = None
    balance: Decimal
    interest_rate: Decimal | None = None
    open_date: date | None = None
    maturity: date | None = None


class Borrowing(_Base):                   # AC2
    contract_type: str
    limit_amt: Decimal
    limit_ccy: str = "KRW"
    balance: Decimal
    balance_ccy: str = "KRW"
    contract_date: date
    maturity: date | None = None
    rate: str | None = None


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
