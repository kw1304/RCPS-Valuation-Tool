from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class FinancialYear:
    """단일 사업연도 재무 스냅샷. 금액 원 단위, 결측은 None."""
    year: int
    revenue: float | None = None
    cogs: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    pretax_income: float | None = None
    tax_expense: float | None = None
    finance_costs: float | None = None
    operating_cf: float | None = None
    total_assets: float | None = None
    current_assets: float | None = None
    total_liabilities: float | None = None
    current_liabilities: float | None = None
    total_equity: float | None = None
    trade_receivables: float | None = None
    inventory: float | None = None
    trade_payables: float | None = None

    @property
    def gross_profit(self) -> float | None:
        if self.revenue is None or self.cogs is None:
            return None
        return self.revenue - self.cogs

    @property
    def sga(self) -> float | None:
        gp = self.gross_profit
        if gp is None or self.operating_income is None:
            return None
        return gp - self.operating_income
