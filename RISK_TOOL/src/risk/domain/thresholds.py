from __future__ import annotations
from dataclasses import dataclass
from risk.domain.financial import FinancialYear
from risk.domain.materiality import Materiality
from risk.domain import indicators as ind


# ── spec 6절 임계값 표와 1:1 대조 (매직넘버 상수화) ──
# 축1 분석적검토
TH_REVENUE = (10, 30)        # 매출 증감률 ±%   (황, 적)
TH_GROSS_MARGIN = (2, 5)     # 매출총이익률 ±%p
TH_OPERATING_MARGIN = (2, 5) # 영업이익률 ±%p
TH_SGA_RATIO = (2, 5)        # 판관비율 ±%p
TH_NET_MARGIN = (2, 5)       # 순이익률 ±%p
TH_OCF_TO_SALES = (3, 6)     # 영업CF/매출 ±%p (현금창출력)
TH_TURNOVER = (20, 35)       # 회전율 하락률 -% (황, 적)
TH_ASSET_TURNOVER = (15, 30) # 총자산회전율 변동률 ±% (효율성 급변)
# 축2 부정
TH_AR_VS_REV = (10, 25)      # 매출채권증가율−매출증가율 %p
TH_INV_VS_REV = (15, 30)     # 재고증가율−매출증가율 %p
TH_ETR_LOW = (10, 5)         # 유효세율 하단 (황<10, 적<5)
TH_ETR_HIGH = (35, 50)       # 유효세율 상단 (황>35, 적>50)
# 축3 계속기업
TH_DEBT_RATIO = (200, 400)   # 부채비율 % (황, 적)
TH_CURRENT_RATIO = (100, 50) # 유동비율 % (황<100, 적<50)

_NA_NOTE = "데이터 없음 — 신호 보류"


@dataclass(frozen=True)
class Signal:
    axis: str
    code: str
    label: str
    level: str          # green/yellow/red/na
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
                                       ind.gross_margin(prev.revenue, prev.cogs),
                                       yellow=TH_GROSS_MARGIN[0], red=TH_GROSS_MARGIN[1]))
        out.append(_analytical_margin(prev, curr, pm, "operating_margin", "영업이익률",
                                       ind.operating_margin(curr.operating_income, curr.revenue),
                                       ind.operating_margin(prev.operating_income, prev.revenue),
                                       yellow=TH_OPERATING_MARGIN[0], red=TH_OPERATING_MARGIN[1]))
        out.append(_analytical_margin(prev, curr, pm, "sga_ratio", "판관비율",
                                       ind.sga_ratio(curr.sga, curr.revenue),
                                       ind.sga_ratio(prev.sga, prev.revenue),
                                       yellow=TH_SGA_RATIO[0], red=TH_SGA_RATIO[1]))
        out.append(_analytical_turnover(prev, curr, pm, "ar_turnover", "매출채권회전율",
                                        ind.turnover(curr.revenue, curr.trade_receivables),
                                        ind.turnover(prev.revenue, prev.trade_receivables),
                                        balance_attr="trade_receivables"))
        out.append(_analytical_turnover(prev, curr, pm, "inv_turnover", "재고회전율",
                                        ind.turnover(curr.cogs, curr.inventory),
                                        ind.turnover(prev.cogs, prev.inventory),
                                        balance_attr="inventory"))
        # 순이익률 변동 (±2%p황/±5%p적)
        out.append(_analytical_margin(prev, curr, pm, "net_margin", "순이익률",
                                      ind.net_margin(curr.net_income, curr.revenue),
                                      ind.net_margin(prev.net_income, prev.revenue)))
        # 영업현금흐름/매출 변동 (현금창출력, ±3%p황/±6%p적)
        out.append(_analytical_margin(prev, curr, pm, "ocf_to_sales", "영업CF/매출",
                                      ind.ocf_to_sales(curr.operating_cf, curr.revenue),
                                      ind.ocf_to_sales(prev.operating_cf, prev.revenue),
                                      yellow=3, red=6))
        # 총자산회전율 변동 (효율성 급변, ±15%/±30%)
        out.append(_analytical_asset_turnover(prev, curr, pm))
        # 매입채무회전율 변동 (-20%/-35% 하락 = 대금지급 지연/조작 의심)
        out.append(_analytical_turnover(prev, curr, pm, "payables_turnover", "매입채무회전율",
                                        ind.turnover(curr.cogs, curr.trade_payables),
                                        ind.turnover(prev.cogs, prev.trade_payables),
                                        balance_attr="trade_payables"))

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
    th = "±10%황/±30%적"
    # 핵심입력 결측 → na (계산 불가)
    if curr.revenue is None or prev.revenue is None:
        return Signal("analytical", "revenue_change", "매출 증감률", "na", None, th, note=_NA_NOTE)
    chg = ind.pct_change(curr.revenue, prev.revenue)
    if chg is None:  # 전기 매출 0 등
        return Signal("analytical", "revenue_change", "매출 증감률", "na", None, th, note=_NA_NOTE)
    delta = curr.revenue - prev.revenue
    band = _band(chg, *TH_REVENUE)
    if band != "green" and not _gate_pm(delta, pm):
        return Signal("analytical", "revenue_change", "매출 증감률", "green", chg,
                      th + " (PM게이트)", note="관찰 — 변동금액 PM 미달")
    return Signal("analytical", "revenue_change", "매출 증감률", band, chg, th)


def _analytical_margin(prev, curr, pm, code, label, curr_v, prev_v, yellow=2, red=5) -> Signal:
    th = f"±{yellow}%p황/±{red}%p적"
    # 핵심입력(당기/전기 비율) 결측 → na
    if curr_v is None or prev_v is None:
        return Signal("analytical", code, label, "na", None, th, note=_NA_NOTE)
    diff = curr_v - prev_v  # %p
    band = _band(diff, yellow, red)
    # 마진 변동의 금액환산 = diff%p × 매출 / 100
    delta_amt = None if curr.revenue is None else diff / 100.0 * curr.revenue
    if band != "green" and not _gate_pm(delta_amt, pm):
        return Signal("analytical", code, label, "green", diff, th + " (PM게이트)",
                      note="관찰 — 변동금액 PM 미달")
    return Signal("analytical", code, label, band, diff, th)


def _analytical_turnover(prev, curr, pm, code, label, curr_v, prev_v,
                         balance_attr="trade_receivables") -> Signal:
    th = f"-{TH_TURNOVER[0]}%황/-{TH_TURNOVER[1]}%적"
    # 회전율 자체 계산 불가(잔액 0/음수/결측) → na
    if curr_v is None or prev_v is None:
        return Signal("analytical", code, label, "na", None, th, note=_NA_NOTE)
    drop = ind.pct_change(curr_v, prev_v)  # 회전율 변화율(%)
    band = "green"
    if drop is not None and drop < 0:
        band = _band(drop, *TH_TURNOVER, two_sided=True)  # 하락폭
    # 금액게이트: Δ잔액(전기대비 변동금액) > PM 일 때만 발화. 관련 잔액은 balance_attr로 지정.
    curr_bal = getattr(curr, balance_attr)
    prev_bal = getattr(prev, balance_attr)
    delta_bal = None if (curr_bal is None or prev_bal is None) else curr_bal - prev_bal
    if band != "green" and not _gate_pm(delta_bal, pm):
        return Signal("analytical", code, label, "green", drop, th + " (PM게이트)",
                      note="관찰 — Δ잔액 PM 미달")
    return Signal("analytical", code, label, band, drop, th)


def _analytical_asset_turnover(prev, curr, pm) -> Signal:
    """총자산회전율 변동 (효율성 급변). 양방향 ±15%황/±30%적, PM게이트 Δ자산."""
    code, label = "asset_turnover", "총자산회전율"
    th = f"±{TH_ASSET_TURNOVER[0]}%황/±{TH_ASSET_TURNOVER[1]}%적"
    at_c = ind.asset_turnover(curr.revenue, curr.total_assets)
    at_p = ind.asset_turnover(prev.revenue, prev.total_assets)
    if at_c is None or at_p is None:
        return Signal("analytical", code, label, "na", None, th, note=_NA_NOTE)
    chg = ind.pct_change(at_c, at_p)  # 회전율 변화율(%)
    band = _band(chg, *TH_ASSET_TURNOVER, two_sided=True)
    # 금액게이트: Δ총자산 > PM
    delta_assets = (None if (curr.total_assets is None or prev.total_assets is None)
                    else curr.total_assets - prev.total_assets)
    if band != "green" and not _gate_pm(delta_assets, pm):
        return Signal("analytical", code, label, "green", chg, th + " (PM게이트)",
                      note="관찰 — Δ자산 PM 미달")
    return Signal("analytical", code, label, band, chg, th)


# ---- 축2 helpers ----

def _fraud_accrual(curr) -> Signal:
    ni, ocf = curr.net_income, curr.operating_cf
    th = "흑자&영업CF<0 → 적"
    # 둘 중 하나라도 결측이면 흑자&음수CF 판정 불가 → na
    if ni is None or ocf is None:
        return Signal("fraud", "accrual_quality", "순이익 흑자 & 영업CF 음수", "na", ocf, th, note=_NA_NOTE)
    level = "red" if (ni > 0 and ocf < 0) else "green"
    return Signal("fraud", "accrual_quality", "순이익 흑자 & 영업CF 음수", level, ocf, th)


def _fraud_ar_vs_rev(prev, curr) -> Signal:
    th = f">{TH_AR_VS_REV[0]}%p황/>{TH_AR_VS_REV[1]}%p적"
    ar = ind.pct_change(curr.trade_receivables, prev.trade_receivables)
    rev = ind.pct_change(curr.revenue, prev.revenue)
    if ar is None or rev is None:
        return Signal("fraud", "ar_vs_revenue", "매출채권증가율−매출증가율", "na", None, th, note=_NA_NOTE)
    gap = ar - rev
    return Signal("fraud", "ar_vs_revenue", "매출채권증가율−매출증가율",
                  _band(gap, *TH_AR_VS_REV, two_sided=False), gap, th)


def _fraud_inv_vs_rev(prev, curr) -> Signal:
    th = f">{TH_INV_VS_REV[0]}%p황/>{TH_INV_VS_REV[1]}%p적"
    inv = ind.pct_change(curr.inventory, prev.inventory)
    rev = ind.pct_change(curr.revenue, prev.revenue)
    if inv is None or rev is None:
        return Signal("fraud", "inv_vs_revenue", "재고증가율−매출증가율", "na", None, th, note=_NA_NOTE)
    gap = inv - rev
    return Signal("fraud", "inv_vs_revenue", "재고증가율−매출증가율",
                  _band(gap, *TH_INV_VS_REV, two_sided=False), gap, th)


def _fraud_tax(curr) -> Signal:
    th = "<10/>35황, <5/>50/적자기업 법인세수익 적"
    etr = ind.effective_tax_rate(curr.tax_expense, curr.pretax_income)
    level = "green"
    # 세전이익 양수인데 법인세가 (-) → 비정상 → red
    if (curr.pretax_income is not None and curr.pretax_income > 0
            and curr.tax_expense is not None and curr.tax_expense < 0):
        level = "red"
    elif etr is not None:
        if etr < TH_ETR_LOW[1] or etr > TH_ETR_HIGH[1]:
            level = "red"
        elif etr < TH_ETR_LOW[0] or etr > TH_ETR_HIGH[0]:
            level = "yellow"
    return Signal("fraud", "effective_tax", "유효세율", level, etr, th)


# ---- 축3 helpers ----

def _gc_debt_ratio(curr) -> Signal:
    th = f">{TH_DEBT_RATIO[0]}%황/>{TH_DEBT_RATIO[1]}%적"
    # 자본<=0(잠식)은 capital_impairment가 별도 처리; 부채/자본 결측은 na
    if curr.total_liabilities is None or curr.total_equity is None:
        return Signal("going_concern", "debt_ratio", "부채비율", "na", None, th, note=_NA_NOTE)
    dr = ind.debt_ratio(curr.total_liabilities, curr.total_equity)
    # dr None ⇒ 자본 0/음수(잠식) 등 분모 비정상 → green 오인 방지, na로 보류
    # (자본잠식 적신호는 capital_impairment가 별도 표시)
    if dr is None:
        return Signal("going_concern", "debt_ratio", "부채비율", "na", None, th, note=_NA_NOTE)
    level = _band_low_high(dr, yellow=TH_DEBT_RATIO[0], red=TH_DEBT_RATIO[1])
    return Signal("going_concern", "debt_ratio", "부채비율", level, dr, th)


def _gc_capital_impairment(curr) -> Signal:
    eq = curr.total_equity
    th = "자본<=0 적"
    if eq is None:
        return Signal("going_concern", "capital_impairment", "자본잠식", "na", None, th, note=_NA_NOTE)
    level = "red" if eq <= 0 else "green"   # 0 포함 완전자본잠식
    return Signal("going_concern", "capital_impairment", "자본잠식", level, eq, th)


def _gc_interest_coverage(years) -> Signal:
    curr = years[-1]
    th = "<1황/3년연속<1·<0적"
    ic = ind.interest_coverage(curr.operating_income, curr.finance_costs)
    if ic is None:
        return Signal("going_concern", "interest_coverage", "이자보상배율", "na", None, th, note=_NA_NOTE)
    # 3년 연속 <1 → red (한계기업)
    last3 = years[-3:]
    cov3 = [ind.interest_coverage(y.operating_income, y.finance_costs) for y in last3]
    zombie = len(last3) == 3 and all(c is not None and c < 1 for c in cov3)
    level = "green"
    if zombie or ic < 0:
        level = "red"
    elif ic < 1:
        level = "yellow"
    return Signal("going_concern", "interest_coverage", "이자보상배율", level, ic, th)


def _gc_current_ratio(curr) -> Signal:
    th = f"<{TH_CURRENT_RATIO[0]}%황/<{TH_CURRENT_RATIO[1]}%적"
    if curr.current_assets is None or curr.current_liabilities is None:
        return Signal("going_concern", "current_ratio", "유동비율", "na", None, th, note=_NA_NOTE)
    cr = ind.current_ratio(curr.current_assets, curr.current_liabilities)
    return Signal("going_concern", "current_ratio", "유동비율",
                  _band_low(cr, yellow=TH_CURRENT_RATIO[0], red=TH_CURRENT_RATIO[1]), cr, th)


def _gc_operating_cf(years) -> Signal:
    th = "음수1회황/인접2년연속음수적"
    latest = years[-1].operating_cf
    prior = years[-2].operating_cf if len(years) >= 2 else None
    # 최신연도 결측이면 판정 불가 → na
    if latest is None:
        return Signal("going_concern", "operating_cf", "영업현금흐름", "na", None, th, note=_NA_NOTE)
    level = "green"
    if latest < 0 and prior is not None and prior < 0:
        level = "red"          # 인접 2년 연속 음수
    elif latest < 0:
        level = "yellow"       # 최신만 음수 (직전 결측 포함 → 연속 판정 불가)
    return Signal("going_concern", "operating_cf", "영업현금흐름", level, latest, th)


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
