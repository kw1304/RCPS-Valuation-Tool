# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from datetime import date
from inputs.deal_params import RCPSParams
from inputs.dcf import DCFParams, dcf_valuation
from valuation.initial import initial_recognition


def main():
    # 샘플 딜 조건 (실제 딜 데이터로 교체하여 사용)
    params = RCPSParams(
        issue_date=date(2023, 1, 1),
        maturity_date=date(2026, 1, 1),
        face_value=5_000_000_000,       # 50억원
        dividend_rate=0.01,             # 우선배당 1%
        redemption_premium=1.08,        # 만기 원금의 108% 상환
        conversion_price=10_000,        # 전환가액 10,000원/주
        conversion_start=date(2024, 1, 1),

        # 리픽싱 조건
        refixing=True,
        refixing_floor=0.70,            # 전환가의 70% 하한
        refixing_trigger=0.90,          # 전환가의 90% 하회 시 발동

        # 평가기준일 시장 데이터
        stock_price=9_500,
        volatility=0.40,
        risk_free_rate=0.035,
        credit_spread=0.05,
        dividend_yield=0.0,

        valuation_date=date(2024, 6, 30),
    )

    print("=" * 60)
    print("RCPS 공정가치 평가 - 이항모형 (CRR)")
    print("=" * 60)

    result = initial_recognition(params, steps=500)

    print(f"\n[평가기준일]  {result['valuation_date']}")
    print(f"[모델]        {result['model']} ({result['steps']} steps)")
    print()
    print(f"  공정가치 (FV)       :  {result['fair_value']:>20,.0f} 원")
    print(f"  순채권가치 (Straight):  {result['straight_bond_value']:>20,.0f} 원")
    print(f"  전환권 가치 (내재)   :  {result['conversion_component']:>20,.0f} 원")
    print()
    print("[주요 입력값]")
    for k, v in result["key_inputs"].items():
        print(f"  {k:<22}: {v}")
    print("=" * 60)


def main_unlisted():
    """비상장 기업 RCPS 평가 예시 (DCF → 주가 → 이항모형)"""

    # Step 1: DCF로 주당 내재가치 산출
    dcf_params = DCFParams(
        fcf_projections=[
            300_000_000,   # 1년차 FCF
            500_000_000,   # 2년차
            700_000_000,   # 3년차
            900_000_000,   # 4년차
            1_100_000_000, # 5년차
        ],
        wacc=0.13,
        terminal_growth=0.02,
        net_debt=2_000_000_000,    # 순차입금 20억
        total_shares=1_000_000,    # 총주식수 100만주
    )
    dcf = dcf_valuation(dcf_params)

    print("=" * 60)
    print("비상장 RCPS 평가 - DCF + 이항모형")
    print("=" * 60)
    print(f"\n[DCF 기업가치]")
    print(f"  명시적 FCF PV  : {dcf['pv_explicit_fcf']:>20,.0f} 원")
    print(f"  터미널 밸류 PV : {dcf['pv_terminal_value']:>20,.0f} 원")
    print(f"  기업가치 (EV)  : {dcf['enterprise_value']:>20,.0f} 원")
    print(f"  자기자본가치   : {dcf['equity_value']:>20,.0f} 원")
    print(f"  주당 내재가치  : {dcf['stock_price']:>20,.0f} 원")

    # Step 2: DCF 주가를 이항모형에 입력
    params = RCPSParams(
        issue_date=date(2023, 1, 1),
        maturity_date=date(2026, 1, 1),
        face_value=5_000_000_000,
        coupon_rate=0.01,
        put_irr=0.075,
        conversion_price=10_000,
        conversion_start=date(2024, 1, 1),
        refixing=True,
        refixing_floor=0.70,
        refixing_trigger=0.90,
        stock_price=dcf["stock_price"],   # DCF 산출 주가 사용
        volatility=0.40,
        risk_free_rate=0.035,
        credit_spread=0.05,
        is_unlisted=True,
        valuation_date=date(2024, 6, 30),
    )

    result = initial_recognition(params, steps=500)
    print(f"\n[RCPS 공정가치]")
    print(f"  공정가치 (FV)        : {result['fair_value']:>20,.0f} 원")
    print(f"  순채권가치 (Straight): {result['straight_bond_value']:>20,.0f} 원")
    print(f"  전환권 가치 (내재)   : {result['conversion_component']:>20,.0f} 원")
    print("=" * 60)


if __name__ == "__main__":
    main()
