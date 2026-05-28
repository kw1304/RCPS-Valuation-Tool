from decimal import Decimal
from datetime import date
from src.domain.ac_models import FinancialAsset, Borrowing, Guarantee, Collateral, Insurance, Derivative, BillCheck, GeneralDeal


def test_financial_asset_round_trip():
    fa = FinancialAsset(
        bc_no="BC-1", bank="국민은행", asset_type="deposit",
        product="보통예금", account_no="0936-01-01", currency="KRW",
        balance=Decimal("1234567"),
    )
    assert fa.model_dump(mode='json')["balance"] == "1234567"


def test_borrowing_optional_fields():
    b = Borrowing(
        bc_no="BC-2", bank="기업은행", contract_type="일반자금대출",
        limit_amt=Decimal("1000000000"), limit_ccy="KRW",
        balance=Decimal("500000000"), balance_ccy="KRW",
        contract_date=date(2025, 6, 10),
    )
    assert b.maturity is None
