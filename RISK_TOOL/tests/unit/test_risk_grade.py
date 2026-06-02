from risk.domain.thresholds import Signal
from risk.domain.risk_grade import overall_grade


def _s(level, axis="analytical", code="c"):
    return Signal(axis, code, "l", level, None, "")


def test_grade_high_on_going_concern_red():
    g = overall_grade([_s("green"), _s("red", axis="going_concern", code="debt_ratio")])
    assert g.grade == "높음"
    assert g.gc_red == 1 and g.serious_red == 1


def test_grade_high_on_serious_fraud_red():
    # 가공매출(ar_vs_revenue) 단독 → 높음
    g = overall_grade([_s("red", axis="fraud", code="ar_vs_revenue")])
    assert g.grade == "높음"
    assert g.serious_red == 1


def test_effective_tax_red_alone_not_high():
    # 유효세율 음수 단독(세금환입 등 양성) → 높음 아님(보통)
    g = overall_grade([_s("red", axis="fraud", code="effective_tax")])
    assert g.grade == "보통"
    assert g.serious_red == 0


def test_analytical_reds_moderate_until_five():
    # 분석적 적신호 4개(GC·중대부정 없음) → 보통, 5개 → 높음
    four = [_s("red", "analytical", c) for c in
            ["gross_margin", "operating_margin", "net_margin", "ocf_to_sales"]]
    assert overall_grade(four).grade == "보통"
    five = four + [_s("red", "analytical", "sga_ratio")]
    assert overall_grade(five).grade == "높음"


def test_grade_moderate_on_three_yellow():
    assert overall_grade([_s("yellow")] * 3).grade == "보통"


def test_grade_low_on_few_yellow():
    assert overall_grade([_s("yellow"), _s("yellow")]).grade == "낮음"


def test_grade_low_all_green():
    assert overall_grade([_s("green")] * 5).grade == "낮음"


def test_counts_reported():
    g = overall_grade([_s("red", "going_concern", "debt_ratio"),
                       _s("yellow"), _s("red", "analytical", "net_margin")])
    assert g.red == 2 and g.yellow == 1 and g.gc_red == 1 and g.serious_red == 1
