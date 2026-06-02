from __future__ import annotations
from dataclasses import dataclass
from risk.domain.financial import FinancialYear
from risk.domain.materiality import Materiality
from risk.domain import indicators as ind


@dataclass(frozen=True)
class Signal:
    axis: str
    code: str
    label: str
    level: str          # green/yellow/red
    value: float | None
    threshold: str
    note: str = ""


def evaluate_axes(years: list[FinancialYear], pm: Materiality) -> list[Signal]:
    """최신연도 기준 축1~3 룰베이스 신호 산출. years는 연도 오름차순."""
    out: list[Signal] = []
    if not years:
        return out
    curr = years[-1]
    prev = years[-2] if len(years) >= 2 else None

    # ── 축1 분석적검토 (PM 이중게이트) ──
    if prev is not None:
        out.append(_analytical_revenue(prev, curr, pm))
        out.append(_analytical_margin(prev, curr, pm, "gross_margin", "매출총이익률",
                                       ind.gross_margin(curr.revenue, curr.cogs),
                                       ind.gross_margin(prev.revenue, prev.cogs)))
        out.append(_analytical_margin(prev, curr, pm, "operating_margin", "영업이익률",
                                       ind.operating_margin(curr.operating_income, curr.revenue),
                                       ind.operating_margin(prev.operating_income, prev.revenue)))
        out.append(_analytical_turnover(prev, curr, pm, "ar_turnover", "매출채권회전율",
                                        ind.turnover(curr.revenue, curr.trade_receivables),
                                        ind.turnover(prev.revenue, prev.trade_receivables)))
        out.append(_analytical_turnover(prev, curr, pm, "inv_turnover", "재고회전율",
                                        ind.turnover(curr.cogs, curr.inventory),
                                        ind.turnover(prev.cogs, prev.inventory)))

    # ── 축2 부정 ──
    out.append(_fraud_accrual(curr))
    if prev is not None:
        out.append(_fraud_ar_vs_rev(prev, curr))
        out.append(_fraud_inv_vs_rev(prev, curr))
    out.append(_fraud_tax(curr))

    # ── 축3 계속기업 ──
    out.append(_gc_debt_ratio(curr))
    out.append(_gc_capital_impairment(curr))
    out.append(_gc_interest_coverage(years))
    out.append(_gc_current_ratio(curr))
    out.append(_gc_operating_cf(years))

    return out


# ---- 축1 helpers ----

def _gate_pm(delta_amount: float | None, pm: Materiality) -> bool:
    return delta_amount is not None and abs(delta_amount) > pm.pm


def _analytical_revenue(prev, curr, pm) -> Signal:
    chg = ind.pct_change(curr.revenue, prev.revenue)
    delta = None if (curr.revenue is None or prev.revenue is None) else curr.revenue - prev.revenue
    band = _band(chg, 10, 30)
    if band != "green" and not _gate_pm(delta, pm):
        return Signal("analytical", "revenue_change", "매출 증감률", "green", chg,
                      "±10%황/±30%적 (PM게이트)", note="관찰 — 변동금액 PM 미달")
    return Signal("analytical", "revenue_change", "매출 증감률", band, chg, "±10%황/±30%적")


def _analytical_margin(prev, curr, pm, code, label, curr_v, prev_v) -> Signal:
    diff = None if (curr_v is None or prev_v is None) else curr_v - prev_v  # %p
    band = _band(diff, 2, 5)
    # 마진 변동의 금액환산 = diff%p × 매출 / 100
    delta_amt = None if (diff is None or curr.revenue is None) else diff / 100.0 * curr.revenue
    if band != "green" and not _gate_pm(delta_amt, pm):
        return Signal("analytical", code, label, "green", diff, "±2%p황/±5%p적 (PM게이트)",
                      note="관찰 — 변동금액 PM 미달")
    return Signal("analytical", code, label, band, diff, "±2%p황/±5%p적")


def _analytical_turnover(prev, curr, pm, code, label, curr_v, prev_v) -> Signal:
    drop = ind.pct_change(curr_v, prev_v)  # 회전율 변화율(%)
    band = "green"
    if drop is not None and drop < 0:
        band = _band(drop, 20, 35, two_sided=True)  # 하락폭
    # 금액게이트: 회전율 하락은 잔액 증가로 환산 곤란 → 잔액 자체 PM 비교
    bal = curr.trade_receivables if code == "ar_turnover" else curr.inventory
    if band != "green" and not _gate_pm(bal, pm):
        return Signal("analytical", code, label, "green", drop, "-20%황/-35%적 (PM게이트)",
                      note="관찰 — 관련잔액 PM 미달")
    return Signal("analytical", code, label, band, drop, "-20%황/-35%적")


# ---- 축2 helpers ----

def _fraud_accrual(curr) -> Signal:
    ni, ocf = curr.net_income, curr.operating_cf
    level = "green"
    if ni is not None and ocf is not None and ni > 0 and ocf < 0:
        level = "red"
    return Signal("fraud", "accrual_quality", "순이익 흑자 & 영업CF 음수", level,
                  ocf, "흑자&영업CF<0 → 적")


def _fraud_ar_vs_rev(prev, curr) -> Signal:
    ar = ind.pct_change(curr.trade_receivables, prev.trade_receivables)
    rev = ind.pct_change(curr.revenue, prev.revenue)
    gap = None if (ar is None or rev is None) else ar - rev
    return Signal("fraud", "ar_vs_revenue", "매출채권증가율−매출증가율", _band(gap, 10, 25, two_sided=False),
                  gap, ">10%p황/>25%p적")


def _fraud_inv_vs_rev(prev, curr) -> Signal:
    inv = ind.pct_change(curr.inventory, prev.inventory)
    rev = ind.pct_change(curr.revenue, prev.revenue)
    gap = None if (inv is None or rev is None) else inv - rev
    return Signal("fraud", "inv_vs_revenue", "재고증가율−매출증가율", _band(gap, 15, 30, two_sided=False),
                  gap, ">15%p황/>30%p적")


def _fraud_tax(curr) -> Signal:
    etr = ind.effective_tax_rate(curr.tax_expense, curr.pretax_income)
    level = "green"
    if curr.tax_expense is not None and curr.tax_expense < 0:
        level = "red"
    elif etr is not None:
        if etr < 5 or etr > 50:
            level = "red"
        elif etr < 10 or etr > 35:
            level = "yellow"
    return Signal("fraud", "effective_tax", "유효세율", level, etr,
                  "<10/>35황, <5/>50/음수적")


# ---- 축3 helpers ----

def _gc_debt_ratio(curr) -> Signal:
    dr = ind.debt_ratio(curr.total_liabilities, curr.total_equity)
    level = _band_low_high(dr, yellow=200, red=400)
    return Signal("going_concern", "debt_ratio", "부채비율", level, dr, ">200%황/>400%적")


def _gc_capital_impairment(curr) -> Signal:
    eq = curr.total_equity
    level = "green"
    if eq is not None and eq < 0:
        level = "red"          # 완전자본잠식
    return Signal("going_concern", "capital_impairment", "자본잠식", level, eq,
                  "자본<0 적")


def _gc_interest_coverage(years) -> Signal:
    curr = years[-1]
    ic = ind.interest_coverage(curr.operating_income, curr.finance_costs)
    # 3년 연속 <1 → red (한계기업)
    last3 = years[-3:]
    cov3 = [ind.interest_coverage(y.operating_income, y.finance_costs) for y in last3]
    zombie = len(last3) == 3 and all(c is not None and c < 1 for c in cov3)
    level = "green"
    if zombie or (ic is not None and ic < 0):
        level = "red"
    elif ic is not None and ic < 1:
        level = "yellow"
    return Signal("going_concern", "interest_coverage", "이자보상배율", level, ic,
                  "<1황/3년연속<1·<0적")


def _gc_current_ratio(curr) -> Signal:
    cr = ind.current_ratio(curr.current_assets, curr.current_liabilities)
    return Signal("going_concern", "current_ratio", "유동비율",
                  _band_low(cr, yellow=100, red=50), cr, "<100%황/<50%적")


def _gc_operating_cf(years) -> Signal:
    ocfs = [y.operating_cf for y in years if y.operating_cf is not None]
    level = "green"
    if ocfs:
        if len(ocfs) >= 2 and all(o < 0 for o in ocfs[-2:]):
            level = "red"
        elif ocfs[-1] < 0:
            level = "yellow"
    return Signal("going_concern", "operating_cf", "영업현금흐름",
                  level, ocfs[-1] if ocfs else None, "음수1회황/연속음수적")


# ---- band helpers (모듈 하단 1회 정의) ----

def _band(value, yellow, red, *, two_sided=True):
    """value 절대크기로 green/yellow/red. two_sided면 ±."""
    if value is None:
        return "green"
    v = abs(value) if two_sided else value
    if v >= red:
        return "red"
    if v >= yellow:
        return "yellow"
    return "green"


def _band_low(value, yellow, red):
    """작을수록 위험 (이자보상배율·유동비율 등). value<=red→red, <=yellow→yellow."""
    if value is None:
        return "green"
    if value <= red:
        return "red"
    if value <= yellow:
        return "yellow"
    return "green"


def _band_low_high(value, yellow, red):
    """클수록 위험."""
    if value is None:
        return "green"
    if value >= red:
        return "red"
    if value >= yellow:
        return "yellow"
    return "green"
