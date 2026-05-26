"""DCF 평가 엔진 — 단일 출처(single source of truth).

이전엔 평가가 3곳(이 파일·`dcfCalc()`·`output/exports.py`)에서 별도 계산되어
silent divergence 위험. 본 모듈로 일원화하여 프론트·Excel은 입력만 받아 호출.

K-IFRS 13.B11~13 소득접근법(Income Approach) FCFF 표준:
  EBIT × (1−t) + D&A − CapEx − ΔWC = FCFF
  EV  = Σ FCFF_t × DF_t + TV × DF_N
  Equity = EV + 비영업자산 − 순차입금 − 다른시리즈 우선주 − 비지배지분
  Stock price = Equity ÷ 총발행주식수

TV 산정 방식 (K-IFRS 13.B11 — 가용한 평가기법 충분 활용):
  - Gordon Growth (기본): TV = FCFF_N × (1+g) / (WACC − g)
  - Exit Multiple: TV = EBITDA_N × multiple (평가법인 표준 cross-check)
  - Weighted: 두 방식 가중평균
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DCFYear:
    """연도별 1차 입력 (EBIT·D&A·CapEx·ΔWC·세율)."""
    revenue: float = 0.0
    ebit: float = 0.0
    da: float = 0.0       # 감가상각비
    capex: float = 0.0    # 자본적 지출 (양수 입력)
    dnwc: float = 0.0     # 운전자본 증가 (양수=증가)
    tax: float = 25.0     # 연도별 세율(%) — 기본 25%


@dataclass
class DCFParams:
    """DCF 입력 파라미터.

    두 가지 입력 모드:
    (A) years에 연도별 1차 입력 → 엔진이 FCFF 계산 (권장, 평가법인 표준)
    (B) fcf_projections에 사전 계산된 FCFF 직접 입력 (legacy compat)
    """
    # ── 입력 모드 A: 연도별 1차 (권장)
    years: List[DCFYear] = field(default_factory=list)

    # ── 입력 모드 B: 사전 계산된 FCFF (legacy)
    fcf_projections: List[float] = field(default_factory=list)

    # ── 할인율·영구성장률
    wacc: float = 0.12
    terminal_growth: float = 0.02

    # ── Equity Bridge (K-IFRS 13.B11 평가실무)
    net_debt: float = 0.0                # 순차입금 = 이자부부채 − 현금성자산
    non_operating_assets: float = 0.0    # 비영업자산 (투자유가증권 등)
    preferred_value: float = 0.0         # 다른 시리즈 우선주 청산가치 (본인 RCPS 제외)
    nci_adjustment: float = 0.0          # 비지배지분조정

    # ── 발행주식수
    total_shares: float = 0.0

    # ── Convention
    mid_year: bool = False               # Mid-year discounting (연중 균등 발생 가정)

    # ── TV 산정 방식
    #    "gordon"    : Gordon Growth만 사용 (기본)
    #    "multiple"  : Exit Multiple만 사용
    #    "weighted"  : 두 방식 가중평균 (tv_weight_gordon로 비중)
    tv_method: str = "gordon"
    exit_multiple: float = 0.0           # EV/EBITDA multiple (한국 비상장 6~12배)
    tv_weight_gordon: float = 0.5        # weighted 모드에서 Gordon 비중


def _compute_fcff_list(params: DCFParams) -> List[float]:
    """입력 모드에 따라 FCFF 시퀀스 산출."""
    if params.years:
        return [
            y.ebit * (1 - y.tax / 100.0) + y.da - y.capex - y.dnwc
            for y in params.years
        ]
    return list(params.fcf_projections)


def _steady_state_check(params: DCFParams) -> dict:
    """정상상태(steady state) 4조건 점검.

    TV 적용 전 마지막 명시연도가 영구 성장 가능 상태인지 검증
    (McKinsey Valuation 7e Ch.10 / Damodaran DCF Valuation):
      1. CapEx ≈ D&A × (1+g)         — 유지·성장 CapEx 균형
      2. ΔWC ∝ 매출 × g              — 운전자본 변동이 매출성장 비례
      3. EBIT 마진 안정              — 마지막 3개년 마진 변동 ±2%p 이내
      4. 매출성장 ≈ g                — 명시기간 말 성장률 = TV 성장률
    """
    if not params.years or len(params.years) < 2:
        return {"applicable": False, "reason": "연도별 입력 부족"}

    last = params.years[-1]
    g = params.terminal_growth
    checks = []
    warnings_msg = []

    # 1. CapEx / D&A 비율
    capex_da_ratio = None
    if last.da > 0:
        capex_da_ratio = last.capex / last.da
        ideal = 1.0 + g
        tol = 0.30  # ±30% 허용 (실무 통상치)
        ok = abs(capex_da_ratio - ideal) <= ideal * tol
        checks.append({
            "name": "CapEx vs 감가상각비",
            "current": round(capex_da_ratio, 2),
            "ideal": round(ideal, 2),
            "ok": ok,
            "hint": "마지막 해의 CapEx가 감가상각비의 (1+성장률)배 정도여야 정상. 너무 작으면 자산이 줄어드는 가정, 너무 크면 영구 과투자.",
        })
        if not ok:
            warnings_msg.append(f"CapEx/D&A = {capex_da_ratio:.2f} (권장 ≈ {ideal:.2f}) — 영구성장 가정과 어긋남")

    # 2. ΔWC / (매출×g) 비율 — 매출성장 비례 여부
    wc_to_rev_g_ratio = None
    if last.revenue > 0 and g > 0:
        expected_dnwc = last.revenue * g * 0.10  # 운전자본 ≈ 매출의 10% (실무 평균)
        wc_to_rev_g_ratio = last.dnwc / expected_dnwc if expected_dnwc != 0 else None
        ok = (last.dnwc >= 0 and last.dnwc <= last.revenue * 0.20)
        checks.append({
            "name": "운전자본 변동",
            "current": last.dnwc,
            "ok": ok,
            "hint": "마지막 해 운전자본 변동이 매출×성장률에 비례해야 정상. 매출의 20% 초과는 비정상.",
        })
        if not ok:
            warnings_msg.append("운전자본 변동이 매출 대비 과도 — 정상상태 의심")

    # 3. EBIT 마진 안정 (마지막 3개년)
    margin_volatility_pct = None
    if len(params.years) >= 3:
        margins = []
        for y in params.years[-3:]:
            if y.revenue > 0:
                margins.append(y.ebit / y.revenue * 100)
        if len(margins) >= 2:
            margin_volatility_pct = max(margins) - min(margins)
            ok = margin_volatility_pct <= 2.0  # ±2%p 이내
            checks.append({
                "name": "EBIT 마진 안정",
                "current": round(margin_volatility_pct, 2),
                "ok": ok,
                "hint": "마지막 3개년 EBIT 마진 차이가 2%p 이내여야 정상상태. 들쭉날쭉하면 영구 가치 추정 부정확.",
            })
            if not ok:
                warnings_msg.append(f"마지막 3개년 EBIT 마진 변동 {margin_volatility_pct:.1f}%p — 정상상태 의심")

    # 4. 매출성장 ≈ g
    rev_growth_last = None
    if len(params.years) >= 2 and params.years[-2].revenue > 0:
        rev_growth_last = (last.revenue / params.years[-2].revenue) - 1.0
        diff = abs(rev_growth_last - g)
        ok = diff <= 0.03  # ±3%p 이내
        checks.append({
            "name": "매출성장 vs 영구성장률",
            "current": f"{rev_growth_last*100:.1f}%",
            "ideal": f"{g*100:.1f}%",
            "ok": ok,
            "hint": "마지막 해 매출성장률이 영구성장률(g)에 가까워야 자연스러운 안착. 차이가 3%p 넘으면 의심.",
        })
        if not ok:
            warnings_msg.append(f"마지막 해 매출성장 {rev_growth_last*100:.1f}% vs g {g*100:.1f}% — 정상상태 의심")

    return {
        "applicable": True,
        "checks": checks,
        "warnings": warnings_msg,
        "passed_count": sum(1 for c in checks if c.get("ok")),
        "total_count": len(checks),
    }


def dcf_valuation(params: DCFParams) -> dict:
    """DCF 평가 — EV → Equity → 주당 내재가치.

    Terminal Value (Gordon Growth):
      TV = FCFF_N × (1+g) / (WACC − g)

    Discounting:
      full-year: DF_t = 1/(1+WACC)^t       (t = 1, 2, ..., N)
      mid-year:  DF_t = 1/(1+WACC)^(t-0.5) (현금흐름 연중 균등 가정)
      TV는 명시기간 종료시점 기준 → mid-year면 t=N-0.5
    """
    wacc = params.wacc
    g = params.terminal_growth
    if wacc <= g:
        raise ValueError(f"WACC({wacc:.1%})가 영구성장률({g:.1%}) 이하 — TV 계산 불가")

    fcffs = _compute_fcff_list(params)
    if not fcffs:
        raise ValueError("FCFF 시퀀스가 비어 있습니다 (years 또는 fcf_projections 필수)")

    n = len(fcffs)
    pv_explicit = 0.0
    pv_each = []
    for i, fc in enumerate(fcffs):
        t = (i + 0.5) if params.mid_year else (i + 1)
        df = 1.0 / (1.0 + wacc) ** t
        pv = fc * df
        pv_each.append({"year": i + 1, "fcff": fc, "df": df, "pv": pv})
        pv_explicit += pv

    # ── Terminal Value (Gordon Growth — 항상 산출, 비교용)
    last_fcff = fcffs[-1]
    tv_gordon = last_fcff * (1 + g) / (wacc - g)
    tv_t = (n - 0.5) if params.mid_year else n
    df_tv = 1.0 / (1.0 + wacc) ** tv_t
    pv_tv_gordon = tv_gordon * df_tv

    # ── Terminal Value (Exit Multiple) — multiple 입력 시 산출
    tv_multiple = None
    pv_tv_multiple = None
    if params.years and params.exit_multiple > 0:
        last = params.years[-1]
        ebitda_n = last.ebit + last.da
        tv_multiple = ebitda_n * params.exit_multiple
        pv_tv_multiple = tv_multiple * df_tv

    # ── 채택 TV 결정
    method = (params.tv_method or "gordon").lower()
    if method == "multiple" and pv_tv_multiple is not None:
        tv = tv_multiple
        pv_tv = pv_tv_multiple
        tv_method_used = "multiple"
    elif method == "weighted" and pv_tv_multiple is not None:
        wg = max(0.0, min(1.0, params.tv_weight_gordon))
        tv = tv_gordon * wg + tv_multiple * (1.0 - wg)
        pv_tv = pv_tv_gordon * wg + pv_tv_multiple * (1.0 - wg)
        tv_method_used = f"weighted (Gordon {wg*100:.0f}% + Multiple {(1-wg)*100:.0f}%)"
    else:
        tv = tv_gordon
        pv_tv = pv_tv_gordon
        tv_method_used = "gordon"

    op_value = pv_explicit + pv_tv
    ev = op_value + params.non_operating_assets
    equity = ev - params.net_debt - params.preferred_value - params.nci_adjustment

    # ── 자기자본 음수 → 자본잠식 신호. 침묵 처리(=0 클리핑) 금지.
    # K-IFRS 13.B2 "공정가치 측정 불가 상황은 사실과 사유를 공시."
    negative_equity_warning = equity < 0
    if not negative_equity_warning:
        stock_price = equity / params.total_shares if params.total_shares > 0 else 0.0
    else:
        stock_price = 0.0

    # 정상상태 4조건 점검
    steady = _steady_state_check(params)

    # 정상상태 참고 지표 (강제 검증 X)
    capex_da_ratio = None
    if params.years and params.years[-1].da > 0:
        capex_da_ratio = params.years[-1].capex / params.years[-1].da

    return {
        "pv_explicit_fcf": pv_explicit,
        "pv_terminal_value": pv_tv,
        "terminal_value": tv,
        "tv_method_used": tv_method_used,
        # 두 방식 모두 비교용 노출
        "tv_gordon": tv_gordon,
        "pv_tv_gordon": pv_tv_gordon,
        "tv_multiple": tv_multiple,
        "pv_tv_multiple": pv_tv_multiple,
        "enterprise_value": ev,
        "operating_value": op_value,
        "equity_value": equity,
        "stock_price": stock_price,
        "wacc": wacc,
        "terminal_growth": g,
        "projection_years": n,
        "mid_year": params.mid_year,
        "tv_to_ev_ratio": (pv_tv / ev) if ev > 0 else None,
        "capex_da_ratio_last": capex_da_ratio,
        "pv_by_year": pv_each,
        "negative_equity_warning": negative_equity_warning,
        "steady_state": steady,
    }
