from __future__ import annotations
from risk.domain.financial import FinancialYear

# 재무상태표 항등식 허용오차 (반올림·일부계정 누락 감안)
_BS_TOL = 0.01
# 매출/자산 배율 상한(초과 시 단위 스케일 오류 의심)
_REV_ASSET_MAX = 30.0

_CRITICAL = {
    "revenue": "매출액",
    "total_assets": "자산총계",
    "total_equity": "자본총계",
    "operating_cf": "영업현금흐름",
}


def check_quality(years: list[FinancialYear]) -> list[str]:
    """추출 재무의 정합성 점검 → 경고 메시지 리스트(빈 리스트면 이상 없음).

    감사인이 신호를 신뢰하기 전에 추출 자체의 오류(스케일·계정 오인식·결측)를
    드러낸다. 조용히 잘못된 신호를 내지 않기 위한 방어선.
    """
    warns: list[str] = []
    if not years:
        return warns
    l = years[-1]

    # 1) 재무상태표 항등식: 자산 = 부채 + 자본
    if l.total_assets and l.total_liabilities is not None and l.total_equity is not None:
        diff = l.total_assets - (l.total_liabilities + l.total_equity)
        rel = abs(diff) / abs(l.total_assets)
        if rel > _BS_TOL:
            warns.append(
                f"재무상태표 항등식 불일치 — 자산({l.total_assets/1e8:,.0f}억) ≠ "
                f"부채+자본({(l.total_liabilities + l.total_equity)/1e8:,.0f}억), "
                f"{rel*100:.1f}% 차이. 계정 오인식·스케일 오류 가능 → 값 검토 권장.")

    # 2) 스케일 sanity: 매출이 자산의 30배 초과면 단위 오류 의심
    if l.total_assets and l.revenue and l.revenue > l.total_assets * _REV_ASSET_MAX:
        warns.append(
            f"매출({l.revenue/1e8:,.0f}억)이 자산({l.total_assets/1e8:,.0f}억)의 "
            f"{l.revenue/l.total_assets:.0f}배 — 단위 스케일 오류 가능 → 검토 권장.")

    # 3) 핵심계정 결측
    miss = [kn for k, kn in _CRITICAL.items() if getattr(l, k) is None]
    if miss:
        warns.append(
            "핵심계정 결측: " + ", ".join(miss) +
            " — 일부 신호가 보류(na)됩니다. DART 자동인식 한계일 수 있어 수기보정 권장.")

    return warns
