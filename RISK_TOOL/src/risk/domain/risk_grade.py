from __future__ import annotations
from dataclasses import dataclass
from risk.domain.thresholds import Signal

# 단독으로 '높음'을 정당화하는 중대 부정징후 (ISA 240 핵심)
#  accrual_quality : 흑자인데 영업CF 음수 → 발생주의 조작
#  ar_vs_revenue   : 매출채권증가율 >> 매출증가율 → 가공매출
#  inv_vs_revenue  : 재고증가율 >> 매출증가율 → 과대재고
# (effective_tax 음수는 세금환입 등 양성요인 흔해 단독 트리거에서 제외 — 적신호 합산엔 포함)
_SERIOUS_FRAUD = {"accrual_quality", "ar_vs_revenue", "inv_vs_revenue"}


@dataclass(frozen=True)
class RiskGrade:
    grade: str          # 높음/보통/낮음
    red: int
    yellow: int
    gc_red: int = 0     # 계속기업축 적신호 수
    serious_red: int = 0  # 높음 트리거(GC + 중대부정) 적신호 수


def overall_grade(signals: list[Signal]) -> RiskGrade:
    """축·심각도 가중 종합등급.

    분석적검토(축1)는 지표 10개라 전기대비 변동만으로 적·황이 흔하다. 단일 적신호로
    '높음'을 매기면 변동 큰 정상기업(예: 실적 회복기)까지 높음이 되어 변별력을 잃는다.
    → **계속기업(GC) 의문**과 **중대 부정징후**(발생주의 조작·가공매출·과대재고)는
      단독으로 감사 최우선 위험이므로 1개라도 '높음'. 분석적 변동만 많은 경우(GC·중대부정
      없음)는 적신호가 5개 이상으로 광범위할 때만 '높음', 그 외엔 '보통'.
    """
    red = sum(1 for s in signals if s.level == "red")
    yellow = sum(1 for s in signals if s.level == "yellow")
    gc_red = sum(1 for s in signals
                 if s.level == "red" and s.axis == "going_concern")
    serious_red = sum(1 for s in signals if s.level == "red"
                      and (s.axis == "going_concern" or s.code in _SERIOUS_FRAUD))

    if serious_red >= 1 or red >= 5:
        grade = "높음"
    elif red >= 1 or yellow >= 3:
        grade = "보통"
    else:
        grade = "낮음"
    return RiskGrade(grade=grade, red=red, yellow=yellow,
                     gc_red=gc_red, serious_red=serious_red)
