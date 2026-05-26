"""DCF 평가 엔진 — 단일 출처(single source of truth).

이전엔 평가가 3곳(이 파일·`dcfCalc()`·`output/exports.py`)에서 별도 계산되어
silent divergence 위험. 본 모듈로 일원화하여 프론트·Excel은 입력만 받아 호출.

K-IFRS 13.B11~13 소득접근법(Income Approach) FCFF 표준:
  EBIT × (1−t) + D&A − CapEx − ΔWC = FCFF
  EV  = Σ FCFF_t × DF_t + TV × DF_N
  Equity = EV + 비영업자산 − 순차입금 − 다른시리즈 우선주 − 비지배지분
  Stock price = Equity ÷ 총발행주식수
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


def _compute_fcff_list(params: DCFParams) -> List[float]:
    """입력 모드에 따라 FCFF 시퀀스 산출."""
    if params.years:
        return [
            y.ebit * (1 - y.tax / 100.0) + y.da - y.capex - y.dnwc
            for y in params.years
        ]
    return list(params.fcf_projections)


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

    # Terminal Value
    last_fcff = fcffs[-1]
    tv = last_fcff * (1 + g) / (wacc - g)
    tv_t = (n - 0.5) if params.mid_year else n
    pv_tv = tv / (1.0 + wacc) ** tv_t

    op_value = pv_explicit + pv_tv
    ev = op_value + params.non_operating_assets
    equity = ev - params.net_debt - params.preferred_value - params.nci_adjustment
    equity = max(equity, 0.0)
    stock_price = equity / params.total_shares if params.total_shares > 0 else 0.0

    # 정상상태 참고 지표 (선택적 정보 — 강제 검증 X)
    capex_da_ratio = None
    if params.years and params.years[-1].da > 0:
        capex_da_ratio = params.years[-1].capex / params.years[-1].da

    return {
        "pv_explicit_fcf": pv_explicit,
        "pv_terminal_value": pv_tv,
        "terminal_value": tv,
        "enterprise_value": ev,
        "operating_value": op_value,
        "equity_value": equity,
        "stock_price": stock_price,
        "wacc": wacc,
        "terminal_growth": g,
        "projection_years": n,
        "mid_year": params.mid_year,
        "tv_to_ev_ratio": (pv_tv / ev) if ev > 0 else None,
        "capex_da_ratio_last": capex_da_ratio,  # 정상상태 참고 (≈ 1+g 권장)
        "pv_by_year": pv_each,
    }
