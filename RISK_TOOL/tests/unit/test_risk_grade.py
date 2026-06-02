from risk.domain.thresholds import Signal
from risk.domain.risk_grade import overall_grade


def _s(level):
    return Signal("x", "c", "l", level, None, "")


def test_grade_high_on_one_red():
    assert overall_grade([_s("green"), _s("red")]).grade == "높음"


def test_grade_high_on_three_yellow():
    assert overall_grade([_s("yellow")] * 3).grade == "높음"


def test_grade_moderate_on_one_yellow():
    g = overall_grade([_s("green"), _s("yellow")])
    assert g.grade == "보통"
    assert g.red == 0 and g.yellow == 1


def test_grade_low_all_green():
    assert overall_grade([_s("green")] * 5).grade == "낮음"
