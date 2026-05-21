from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DCFParams:
    """
    비상장 기업 DCF 평가 파라미터

    사용 흐름:
      1. FCF 예측치, WACC, 영구성장률 입력
      2. dcf_valuation() 호출 → 기업가치(EV) 및 주당 내재가치 산출
      3. 산출된 stock_price를 RCPSParams.stock_price에 입력
    """

    # ── FCF 예측 (명시적 예측기간, 연도별 잉여현금흐름)
    # 예) [500_000_000, 700_000_000, 900_000_000, 1_100_000_000, 1_300_000_000]
    fcf_projections: List[float]

    # ── 할인율
    wacc: float           # 가중평균자본비용 (예: 0.12 = 12%)

    # ── 영구성장률 (터미널 밸류)
    # 일반적으로 GDP 성장률 수준: 0.01~0.03
    # wacc 보다 반드시 낮아야 함
    terminal_growth: float = 0.02

    # ── 자본구조 (EV → 주가 변환에 필요)
    # 순차입금 = 이자부부채 합계 - 현금성자산
    net_debt: float = 0.0
    total_shares: float = 0.0     # 총발행주식수 (보통주 + 우선주 전환 후 기준)

    # ── 비영업자산 (선택)
    non_operating_assets: float = 0.0   # 투자부동산, 관계기업 지분 등


def dcf_valuation(params: DCFParams) -> dict:
    """
    DCF 기업가치 평가 → 주당 내재가치 산출

    Terminal Value는 Gordon Growth Model 적용:
      TV = FCF_마지막연도 × (1+g) / (WACC - g)

    Returns:
        pv_explicit    : 명시적 예측기간 FCF 현재가치 합
        pv_terminal    : 터미널 밸류 현재가치
        enterprise_value: EV = pv_explicit + pv_terminal + 비영업자산
        equity_value   : EV - 순차입금
        stock_price    : 주당 내재가치 (equity_value / 총주식수)
    """
    wacc = params.wacc
    g = params.terminal_growth

    if wacc <= g:
        raise ValueError(f"WACC({wacc:.1%})가 영구성장률({g:.1%}) 이하입니다. 터미널 밸류 계산 불가.")

    # 명시적 예측기간 FCF 현재가치
    pv_explicit = sum(
        fcf / (1 + wacc) ** (t + 1)
        for t, fcf in enumerate(params.fcf_projections)
    )

    # 터미널 밸류 (마지막 예측연도 말 기준)
    n = len(params.fcf_projections)
    terminal_fcf = params.fcf_projections[-1] * (1 + g)
    terminal_value = terminal_fcf / (wacc - g)
    pv_terminal = terminal_value / (1 + wacc) ** n

    ev = pv_explicit + pv_terminal + params.non_operating_assets
    equity_value = ev - params.net_debt
    stock_price = equity_value / params.total_shares if params.total_shares > 0 else 0.0

    return {
        "pv_explicit_fcf": pv_explicit,
        "pv_terminal_value": pv_terminal,
        "terminal_value": terminal_value,
        "enterprise_value": ev,
        "equity_value": max(equity_value, 0.0),
        "stock_price": max(stock_price, 0.0),
        "wacc": wacc,
        "terminal_growth": g,
        "projection_years": n,
    }
