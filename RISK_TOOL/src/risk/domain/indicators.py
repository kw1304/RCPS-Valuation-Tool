from __future__ import annotations


def safe_div(num: float | None, den: float | None) -> float | None:
    """분모 0/음수/None → None. 음수 분모는 비율 무의미라 None."""
    if num is None or den is None or den <= 0:
        return None
    return num / den


def pct_change(curr: float | None, base: float | None) -> float | None:
    """전기대비 증감률(%). base 0/None → None."""
    if curr is None or base is None or base == 0:
        return None
    return (curr - base) / abs(base) * 100.0


def gross_margin(revenue: float | None, cogs: float | None) -> float | None:
    if revenue is None or cogs is None or revenue <= 0:
        return None
    return (revenue - cogs) / revenue * 100.0


def operating_margin(operating_income: float | None, revenue: float | None) -> float | None:
    r = safe_div(operating_income, revenue)
    return r * 100.0 if r is not None else None


def sga_ratio(sga: float | None, revenue: float | None) -> float | None:
    r = safe_div(sga, revenue)
    return r * 100.0 if r is not None else None


def turnover(flow: float | None, balance: float | None) -> float | None:
    """회전율 = 흐름(매출 등) / 잔액. 잔액 0/음수 → None."""
    return safe_div(flow, balance)


def effective_tax_rate(tax_expense: float | None, pretax_income: float | None) -> float | None:
    """유효세율(%). 세전이익 양수일 때만."""
    if tax_expense is None or pretax_income is None or pretax_income <= 0:
        return None
    return tax_expense / pretax_income * 100.0


def debt_ratio(liabilities: float | None, equity: float | None) -> float | None:
    """부채비율(%) = 부채/자본. 자본 0/음수(잠식) → None (신호는 자본잠식 룰이 별도 처리)."""
    r = safe_div(liabilities, equity)
    return r * 100.0 if r is not None else None


def interest_coverage(operating_income: float | None, finance_costs: float | None) -> float | None:
    """이자보상배율 = 영업이익 / 금융원가."""
    return safe_div(operating_income, finance_costs)


def current_ratio(current_assets: float | None, current_liabilities: float | None) -> float | None:
    r = safe_div(current_assets, current_liabilities)
    return r * 100.0 if r is not None else None
