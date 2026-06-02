from __future__ import annotations
from dataclasses import dataclass
from risk.domain.thresholds import Signal


@dataclass(frozen=True)
class RiskGrade:
    grade: str   # 높음/보통/낮음
    red: int
    yellow: int


def overall_grade(signals: list[Signal]) -> RiskGrade:
    red = sum(1 for s in signals if s.level == "red")
    yellow = sum(1 for s in signals if s.level == "yellow")
    if red >= 1 or yellow >= 3:
        grade = "높음"
    elif yellow >= 1:
        grade = "보통"
    else:
        grade = "낮음"
    return RiskGrade(grade=grade, red=red, yellow=yellow)
