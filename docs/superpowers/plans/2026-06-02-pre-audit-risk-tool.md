# 감사전 리스크 확인 툴 (RISK_TOOL) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 감사계획 단계에서 DART 자동수집 재무·공시 + 뉴스 리서치로 대상기업 중요왜곡위험을 4축 룰베이스 신호등으로 스크리닝하고 ISA 315 위험평가 조서를 생성하는 독립 FastAPI 툴.

**Architecture:** 클린아키텍처(domain/application/infrastructure/interface). domain은 외부의존 0의 순수 룰베이스 로직(테스트 핵심). infrastructure는 DART(기존 코드 이식+계정맵 확장)·뉴스(WebSearch)·LLM(Claude)·Excel. application이 수집→평가→코멘트 순서 조립. WAT 임베드 셸로 UI 통일.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, requests, openpyxl, anthropic SDK, pytest. Spec: `docs/superpowers/specs/2026-06-02-pre-audit-risk-tool-design.md`.

---

## File Structure

```
RISK_TOOL/
  requirements.txt
  .gitignore
  run_server.py
  src/risk/
    __init__.py
    domain/
      __init__.py
      financial.py          # FinancialYear dataclass (infra↔domain 인터페이스)
      materiality.py        # 수행중요성(PM) 산정
      indicators.py         # 비율·증감 계산 (순수 함수)
      thresholds.py         # 임계값 상수 + 신호등 판정 → Signal 리스트
      risk_grade.py         # 종합 위험등급 집계
    application/
      __init__.py
      assess_risk_uc.py     # 오케스트레이션
    infrastructure/
      __init__.py
      dart/
        __init__.py
        client.py           # corp조회·공시 list (CC client 이식)
        risk_extractor.py   # 재무 전계정 5개년 추출 (fetch_financials 패턴 확장)
      news/
        __init__.py
        researcher.py       # WebSearch 키워드 리서치 (포트 + 실제 구현은 app에서 주입)
      llm/
        __init__.py
        commenter.py        # Claude API 코멘트·뉴스요약
      excel/
        __init__.py
        workpaper.py        # ISA 315 위험평가 W/P
    interface/
      __init__.py
      api/
        __init__.py
        app.py              # FastAPI 라우트
        frontend/
          index.html        # WAT 셸 대시보드
  tests/
    __init__.py
    unit/
      __init__.py
      test_materiality.py
      test_indicators.py
      test_thresholds.py
      test_risk_grade.py
    integration/
      __init__.py
      fixtures/
        listed_5y.json      # 상장사 fetch 결과 fixture
      test_assess_uc.py
```

**FinancialYear 인터페이스 (domain 입력 계약 — 모든 금액 원 단위, 결측은 None):**

```python
@dataclass(frozen=True)
class FinancialYear:
    year: int
    revenue: float | None            # 매출액
    cogs: float | None               # 매출원가
    operating_income: float | None   # 영업이익
    net_income: float | None         # 당기순이익
    pretax_income: float | None      # 세전이익
    tax_expense: float | None        # 법인세비용
    finance_costs: float | None      # 금융원가(이자비용 proxy)
    operating_cf: float | None       # 영업활동현금흐름
    total_assets: float | None
    current_assets: float | None
    total_liabilities: float | None
    current_liabilities: float | None
    total_equity: float | None
    trade_receivables: float | None  # 매출채권(및기타유동채권 proxy)
    inventory: float | None          # 재고자산
```

파생: `gross_profit = revenue - cogs`, `sga = gross_profit - operating_income` (판관비 태그 모호 → 도출).

---

## Phase 0 — 스캐폴드 & 데이터 계약

### Task 0: 프로젝트 스캐폴드

**Files:**
- Create: `RISK_TOOL/requirements.txt`, `RISK_TOOL/.gitignore`
- Create: 모든 `__init__.py` (위 트리)

- [ ] **Step 1: requirements.txt 작성**

```
fastapi>=0.110
uvicorn[standard]>=0.29
requests>=2.31
openpyxl>=3.1
anthropic>=0.39
pytest>=8.0
```

- [ ] **Step 2: .gitignore 작성**

```
__pycache__/
*.pyc
.env
.venv/
*.xlsx
```

- [ ] **Step 3: 빈 패키지 초기화**

각 디렉터리에 빈 `__init__.py` 생성 (위 File Structure 트리 전체).

- [ ] **Step 4: Commit**

```bash
git add RISK_TOOL/
git commit -m "chore(risk): RISK_TOOL 스캐폴드 + requirements"
```

### Task 1: FinancialYear 데이터 계약

**Files:**
- Create: `RISK_TOOL/src/risk/domain/financial.py`
- Test: `RISK_TOOL/tests/unit/test_indicators.py` (다음 태스크에서 사용)

- [ ] **Step 1: financial.py 작성**

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class FinancialYear:
    """단일 사업연도 재무 스냅샷. 금액 원 단위, 결측은 None."""
    year: int
    revenue: float | None = None
    cogs: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    pretax_income: float | None = None
    tax_expense: float | None = None
    finance_costs: float | None = None
    operating_cf: float | None = None
    total_assets: float | None = None
    current_assets: float | None = None
    total_liabilities: float | None = None
    current_liabilities: float | None = None
    total_equity: float | None = None
    trade_receivables: float | None = None
    inventory: float | None = None

    @property
    def gross_profit(self) -> float | None:
        if self.revenue is None or self.cogs is None:
            return None
        return self.revenue - self.cogs

    @property
    def sga(self) -> float | None:
        gp = self.gross_profit
        if gp is None or self.operating_income is None:
            return None
        return gp - self.operating_income
```

- [ ] **Step 2: Commit**

```bash
git add RISK_TOOL/src/risk/domain/financial.py
git commit -m "feat(risk): FinancialYear 데이터 계약 (domain 입력)"
```

---

## Phase 1 — Domain (룰베이스 핵심, 완전 TDD)

### Task 2: 수행중요성(PM) 산정

**Files:**
- Create: `RISK_TOOL/src/risk/domain/materiality.py`
- Test: `RISK_TOOL/tests/unit/test_materiality.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from risk.domain.financial import FinancialYear
from risk.domain.materiality import performance_materiality


def test_pm_uses_smallest_benchmark():
    # 매출 100억, 자산 50억, 세전이익 2억 → 세전이익 5%=1천만, 매출0.5%=5천만, 자산0.5%=2.5천만
    # 가장 작은(보수적) = 세전이익 5% = 1천만, PM = ×0.75 = 750만
    fy = FinancialYear(year=2025, revenue=10_000_000_000,
                       total_assets=5_000_000_000, pretax_income=200_000_000)
    pm = performance_materiality(fy)
    assert pm.materiality == 10_000_000
    assert pm.pm == 7_500_000
    assert pm.benchmark == "pretax_income"


def test_pm_skips_none_and_nonpositive():
    # 세전이익 결측·자산 결측 → 매출 0.5%만 적용
    fy = FinancialYear(year=2025, revenue=20_000_000_000)
    pm = performance_materiality(fy)
    assert pm.materiality == 100_000_000
    assert pm.benchmark == "revenue"


def test_pm_raises_when_no_base():
    fy = FinancialYear(year=2025)
    import pytest
    with pytest.raises(ValueError):
        performance_materiality(fy)
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_materiality.py -v`
Expected: FAIL (ModuleNotFoundError: risk.domain.materiality)

- [ ] **Step 3: materiality.py 구현**

```python
from __future__ import annotations
from dataclasses import dataclass
from risk.domain.financial import FinancialYear

_PM_RATIO = 0.75  # 수행중요성 = 중요성 × 75%


@dataclass(frozen=True)
class Materiality:
    materiality: float
    pm: float
    benchmark: str


def performance_materiality(fy: FinancialYear) -> Materiality:
    """benchmark 후보 중 가장 작은(보수적) 중요성 채택. PM = 중요성 × 0.75."""
    cands: list[tuple[str, float]] = []
    if fy.pretax_income is not None and fy.pretax_income > 0:
        cands.append(("pretax_income", fy.pretax_income * 0.05))
    if fy.revenue is not None and fy.revenue > 0:
        cands.append(("revenue", fy.revenue * 0.005))
    if fy.total_assets is not None and fy.total_assets > 0:
        cands.append(("total_assets", fy.total_assets * 0.005))
    if not cands:
        raise ValueError("중요성 산정 benchmark 없음 (매출·자산·세전이익 모두 결측/비양수)")
    benchmark, materiality = min(cands, key=lambda c: c[1])
    return Materiality(materiality=materiality, pm=materiality * _PM_RATIO,
                       benchmark=benchmark)
```

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_materiality.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/domain/materiality.py RISK_TOOL/tests/unit/test_materiality.py
git commit -m "feat(risk): 수행중요성(PM) 산정 — 최소 benchmark 보수 채택"
```

### Task 3: 지표 계산 (indicators)

**Files:**
- Create: `RISK_TOOL/src/risk/domain/indicators.py`
- Test: `RISK_TOOL/tests/unit/test_indicators.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
import pytest
from risk.domain import indicators as ind


def test_pct_change_basic():
    assert ind.pct_change(110, 100) == pytest.approx(10.0)
    assert ind.pct_change(50, 100) == pytest.approx(-50.0)


def test_pct_change_none_or_zero_base():
    assert ind.pct_change(100, None) is None
    assert ind.pct_change(None, 100) is None
    assert ind.pct_change(100, 0) is None


def test_ratio_safe_div():
    assert ind.safe_div(10, 2) == pytest.approx(5.0)
    assert ind.safe_div(10, 0) is None
    assert ind.safe_div(10, -0.0) is None
    assert ind.safe_div(None, 2) is None


def test_gross_margin():
    assert ind.gross_margin(revenue=100, cogs=60) == pytest.approx(40.0)  # %
    assert ind.gross_margin(revenue=0, cogs=0) is None


def test_receivables_turnover():
    # 매출 1000 / 매출채권 200 = 5.0회
    assert ind.turnover(flow=1000, balance=200) == pytest.approx(5.0)
    assert ind.turnover(flow=1000, balance=0) is None


def test_debt_ratio():
    assert ind.debt_ratio(liabilities=300, equity=100) == pytest.approx(300.0)  # %
    assert ind.debt_ratio(liabilities=300, equity=0) is None  # 자본잠식 분모 → None
    assert ind.debt_ratio(liabilities=300, equity=-50) is None


def test_interest_coverage():
    assert ind.interest_coverage(operating_income=300, finance_costs=100) == pytest.approx(3.0)
    assert ind.interest_coverage(operating_income=300, finance_costs=0) is None


def test_current_ratio():
    assert ind.current_ratio(current_assets=150, current_liabilities=100) == pytest.approx(150.0)
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_indicators.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: indicators.py 구현**

```python
from __future__ import annotations


def safe_div(num: float | None, den: float | None) -> float | None:
    """분모 0/음수/None → None. 음수 분모는 비율 무의미라 None."""
    if num is None or den is None or den <= 0:
        return None
    return num / den


def pct_change(curr: float | None, base: float | None) -> float | None:
    """전기대비 증감률(%). base 0/None → None."""
    if curr is None or base is None or base == 0:
        return None
    return (curr - base) / abs(base) * 100.0


def gross_margin(revenue: float | None, cogs: float | None) -> float | None:
    if revenue is None or cogs is None or revenue <= 0:
        return None
    return (revenue - cogs) / revenue * 100.0


def operating_margin(operating_income: float | None, revenue: float | None) -> float | None:
    r = safe_div(operating_income, revenue)
    return r * 100.0 if r is not None else None


def sga_ratio(sga: float | None, revenue: float | None) -> float | None:
    r = safe_div(sga, revenue)
    return r * 100.0 if r is not None else None


def turnover(flow: float | None, balance: float | None) -> float | None:
    """회전율 = 흐름(매출 등) / 잔액. 잔액 0/음수 → None."""
    return safe_div(flow, balance)


def effective_tax_rate(tax_expense: float | None, pretax_income: float | None) -> float | None:
    """유효세율(%). 세전이익 양수일 때만."""
    if tax_expense is None or pretax_income is None or pretax_income <= 0:
        return None
    return tax_expense / pretax_income * 100.0


def debt_ratio(liabilities: float | None, equity: float | None) -> float | None:
    """부채비율(%) = 부채/자본. 자본 0/음수(잠식) → None (신호는 자본잠식 룰이 별도 처리)."""
    r = safe_div(liabilities, equity)
    return r * 100.0 if r is not None else None


def interest_coverage(operating_income: float | None, finance_costs: float | None) -> float | None:
    """이자보상배율 = 영업이익 / 금융원가."""
    return safe_div(operating_income, finance_costs)


def current_ratio(current_assets: float | None, current_liabilities: float | None) -> float | None:
    r = safe_div(current_assets, current_liabilities)
    return r * 100.0 if r is not None else None
```

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_indicators.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/domain/indicators.py RISK_TOOL/tests/unit/test_indicators.py
git commit -m "feat(risk): 재무지표 계산 (분모가드·None전파)"
```

### Task 4: 신호등 판정 (thresholds) — 축1~3

**Files:**
- Create: `RISK_TOOL/src/risk/domain/thresholds.py`
- Test: `RISK_TOOL/tests/unit/test_thresholds.py`

신호 모델:

```python
@dataclass(frozen=True)
class Signal:
    axis: str        # "analytical" | "fraud" | "going_concern"
    code: str        # "revenue_change" 등
    label: str       # 한글 지표명
    level: str       # "green" | "yellow" | "red"
    value: float | None
    threshold: str   # 적용 임계 설명
    note: str = ""   # 'observation'(PM 미달 등) 표기
```

- [ ] **Step 1: 실패 테스트 작성**

```python
import pytest
from risk.domain.financial import FinancialYear
from risk.domain.materiality import Materiality
from risk.domain.thresholds import evaluate_axes


def _mk(year, **kw):
    return FinancialYear(year=year, **kw)


def _pm(value):
    return Materiality(materiality=value / 0.75, pm=value, benchmark="revenue")


def test_revenue_change_red_with_pm_gate():
    # 매출 +40% (적 임계 30 초과), 변동금액 4억 > PM 1천만 → red
    prev = _mk(2024, revenue=1_000_000_000)
    curr = _mk(2025, revenue=1_400_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    rev = next(s for s in sigs if s.code == "revenue_change")
    assert rev.level == "red"


def test_revenue_change_observation_when_below_pm():
    # 매출 +40%지만 변동금액 4백만 < PM 1천만 → 신호 아님(observation, green)
    prev = _mk(2024, revenue=10_000_000)
    curr = _mk(2025, revenue=14_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    rev = next(s for s in sigs if s.code == "revenue_change")
    assert rev.level == "green"
    assert "관찰" in rev.note


def test_capital_impairment_red():
    # 자본총계 음수 → 완전자본잠식 red
    prev = _mk(2024, total_equity=100_000_000)
    curr = _mk(2025, total_equity=-50_000_000, total_liabilities=300_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    cap = next(s for s in sigs if s.code == "capital_impairment")
    assert cap.level == "red"


def test_accrual_red_profit_but_negative_ocf():
    prev = _mk(2024)
    curr = _mk(2025, net_income=500_000_000, operating_cf=-100_000_000)
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    acc = next(s for s in sigs if s.code == "accrual_quality")
    assert acc.level == "red"


def test_interest_coverage_zombie_red():
    # 3년 연속 이자보상배율<1 → red
    ys = [
        _mk(2023, operating_income=50, finance_costs=100),
        _mk(2024, operating_income=40, finance_costs=100),
        _mk(2025, operating_income=30, finance_costs=100),
    ]
    sigs = evaluate_axes(ys, _pm(10_000_000))
    ic = next(s for s in sigs if s.code == "interest_coverage")
    assert ic.level == "red"


def test_debt_ratio_yellow():
    prev = _mk(2024)
    curr = _mk(2025, total_liabilities=250, total_equity=100)  # 250%
    sigs = evaluate_axes([prev, curr], _pm(10_000_000))
    dr = next(s for s in sigs if s.code == "debt_ratio")
    assert dr.level == "yellow"
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_thresholds.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: thresholds.py 구현**

```python
from __future__ import annotations
from dataclasses import dataclass
from risk.domain.financial import FinancialYear
from risk.domain.materiality import Materiality
from risk.domain import indicators as ind


@dataclass(frozen=True)
class Signal:
    axis: str
    code: str
    label: str
    level: str          # green/yellow/red
    value: float | None
    threshold: str
    note: str = ""


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
    """작을수록 위험 (이자보상배율·유동비율 등). value<=yellow→yellow, <=red→red."""
    if value is None:
        return "green"
    if value <= red:
        return "red"
    if value <= yellow:
        return "yellow"
    return "green"


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
                                       ind.gross_margin(prev.revenue, prev.cogs)))
        out.append(_analytical_margin(prev, curr, pm, "operating_margin", "영업이익률",
                                       ind.operating_margin(curr.operating_income, curr.revenue),
                                       ind.operating_margin(prev.operating_income, prev.revenue)))
        out.append(_analytical_turnover(prev, curr, pm, "ar_turnover", "매출채권회전율",
                                        ind.turnover(curr.revenue, curr.trade_receivables),
                                        ind.turnover(prev.revenue, prev.trade_receivables)))
        out.append(_analytical_turnover(prev, curr, pm, "inv_turnover", "재고회전율",
                                        ind.turnover(curr.cogs, curr.inventory),
                                        ind.turnover(prev.cogs, prev.inventory)))

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
    chg = ind.pct_change(curr.revenue, prev.revenue)
    delta = None if (curr.revenue is None or prev.revenue is None) else curr.revenue - prev.revenue
    band = _band(chg, 10, 30)
    if band != "green" and not _gate_pm(delta, pm):
        return Signal("analytical", "revenue_change", "매출 증감률", "green", chg,
                      "±10%황/±30%적 (PM게이트)", note="관찰 — 변동금액 PM 미달")
    return Signal("analytical", "revenue_change", "매출 증감률", band, chg, "±10%황/±30%적")


def _analytical_margin(prev, curr, pm, code, label, curr_v, prev_v) -> Signal:
    diff = None if (curr_v is None or prev_v is None) else curr_v - prev_v  # %p
    band = _band(diff, 2, 5)
    # 마진 변동의 금액환산 = diff%p × 매출 / 100
    delta_amt = None if (diff is None or curr.revenue is None) else diff / 100.0 * curr.revenue
    if band != "green" and not _gate_pm(delta_amt, pm):
        return Signal("analytical", code, label, "green", diff, "±2%p황/±5%p적 (PM게이트)",
                      note="관찰 — 변동금액 PM 미달")
    return Signal("analytical", code, label, band, diff, "±2%p황/±5%p적")


def _analytical_turnover(prev, curr, pm, code, label, curr_v, prev_v) -> Signal:
    drop = ind.pct_change(curr_v, prev_v)  # 회전율 변화율(%)
    band = "green"
    if drop is not None and drop < 0:
        band = _band(drop, 20, 35, two_sided=True)  # 하락폭
    # 금액게이트: 회전율 하락은 잔액 증가로 환산 곤란 → 잔액 자체 PM 비교
    bal = curr.trade_receivables if code == "ar_turnover" else curr.inventory
    if band != "green" and not _gate_pm(bal, pm):
        return Signal("analytical", code, label, "green", drop, "-20%황/-35%적 (PM게이트)",
                      note="관찰 — 관련잔액 PM 미달")
    return Signal("analytical", code, label, band, drop, "-20%황/-35%적")


# ---- 축2 helpers ----

def _fraud_accrual(curr) -> Signal:
    ni, ocf = curr.net_income, curr.operating_cf
    level = "green"
    if ni is not None and ocf is not None and ni > 0 and ocf < 0:
        level = "red"
    return Signal("fraud", "accrual_quality", "순이익 흑자 & 영업CF 음수", level,
                  ocf, "흑자&영업CF<0 → 적")


def _fraud_ar_vs_rev(prev, curr) -> Signal:
    ar = ind.pct_change(curr.trade_receivables, prev.trade_receivables)
    rev = ind.pct_change(curr.revenue, prev.revenue)
    gap = None if (ar is None or rev is None) else ar - rev
    return Signal("fraud", "ar_vs_revenue", "매출채권증가율−매출증가율", _band(gap, 10, 25, two_sided=False),
                  gap, ">10%p황/>25%p적")


def _fraud_inv_vs_rev(prev, curr) -> Signal:
    inv = ind.pct_change(curr.inventory, prev.inventory)
    rev = ind.pct_change(curr.revenue, prev.revenue)
    gap = None if (inv is None or rev is None) else inv - rev
    return Signal("fraud", "inv_vs_revenue", "재고증가율−매출증가율", _band(gap, 15, 30, two_sided=False),
                  gap, ">15%p황/>30%p적")


def _fraud_tax(curr) -> Signal:
    etr = ind.effective_tax_rate(curr.tax_expense, curr.pretax_income)
    level = "green"
    if curr.tax_expense is not None and curr.tax_expense < 0:
        level = "red"
    elif etr is not None:
        if etr < 5 or etr > 50:
            level = "red"
        elif etr < 10 or etr > 35:
            level = "yellow"
    return Signal("fraud", "effective_tax", "유효세율", level, etr,
                  "<10/>35황, <5/>50/음수적")


# ---- 축3 helpers ----

def _gc_debt_ratio(curr) -> Signal:
    dr = ind.debt_ratio(curr.total_liabilities, curr.total_equity)
    level = _band_low_high(dr, yellow=200, red=400)
    return Signal("going_concern", "debt_ratio", "부채비율", level, dr, ">200%황/>400%적")


def _band_low_high(value, yellow, red):
    """클수록 위험."""
    if value is None:
        return "green"
    if value >= red:
        return "red"
    if value >= yellow:
        return "yellow"
    return "green"


def _gc_capital_impairment(curr) -> Signal:
    eq = curr.total_equity
    level = "green"
    if eq is not None:
        if eq < 0:
            level = "red"          # 완전자본잠식
        elif curr.total_assets is not None and eq < 0.5 * (curr.total_assets - curr.total_liabilities or eq):
            level = "yellow"
    return Signal("going_concern", "capital_impairment", "자본잠식", level, eq,
                  "자본<0 적")


def _gc_interest_coverage(years) -> Signal:
    curr = years[-1]
    ic = ind.interest_coverage(curr.operating_income, curr.finance_costs)
    # 3년 연속 <1 → red (한계기업)
    last3 = years[-3:]
    cov3 = [ind.interest_coverage(y.operating_income, y.finance_costs) for y in last3]
    zombie = len(last3) == 3 and all(c is not None and c < 1 for c in cov3)
    level = "green"
    if zombie or (ic is not None and ic < 0):
        level = "red"
    elif ic is not None and ic < 1:
        level = "yellow"
    return Signal("going_concern", "interest_coverage", "이자보상배율", level, ic,
                  "<1황/3년연속<1·<0적")


def _gc_current_ratio(curr) -> Signal:
    cr = ind.current_ratio(curr.current_assets, curr.current_liabilities)
    return Signal("going_concern", "current_ratio", "유동비율",
                  _band_low(cr, yellow=100, red=50), cr, "<100%황/<50%적")


def _gc_operating_cf(years) -> Signal:
    ocfs = [y.operating_cf for y in years if y.operating_cf is not None]
    level = "green"
    if ocfs:
        if len(ocfs) >= 2 and all(o < 0 for o in ocfs[-2:]):
            level = "red"
        elif ocfs[-1] < 0:
            level = "yellow"
    return Signal("going_concern", "operating_cf", "영업현금흐름",
                  level, ocfs[-1] if ocfs else None, "음수1회황/연속음수적")


def _band_low(value, yellow, red):
    if value is None:
        return "green"
    if value <= red:
        return "red"
    if value <= yellow:
        return "yellow"
    return "green"
```

> 주의: `_band_low`가 두 번 정의됨 — 구현 시 helper들을 **모듈 하단에 1회만** 두고 중복 제거. (`_band`, `_band_low`, `_band_low_high`, `_gate_pm` 4개 헬퍼는 유일.)

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_thresholds.py -v`
Expected: PASS (6 passed). 중복 `_band_low` 정의 제거 후.

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/domain/thresholds.py RISK_TOOL/tests/unit/test_thresholds.py
git commit -m "feat(risk): 축1~3 룰베이스 신호등 판정 (PM 이중게이트·한계기업)"
```

### Task 5: 종합 위험등급 (risk_grade)

**Files:**
- Create: `RISK_TOOL/src/risk/domain/risk_grade.py`
- Test: `RISK_TOOL/tests/unit/test_risk_grade.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_risk_grade.py -v`
Expected: FAIL

- [ ] **Step 3: risk_grade.py 구현**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_risk_grade.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/domain/risk_grade.py RISK_TOOL/tests/unit/test_risk_grade.py
git commit -m "feat(risk): 종합 위험등급 집계 (적≥1·황≥3→높음)"
```

---

## Phase 2 — Infrastructure: DART 전계정 추출

### Task 6: DART client 이식 (corp조회·공시)

**Files:**
- Create: `RISK_TOOL/src/risk/infrastructure/dart/client.py`
- Source: `CC_SAMPLING_TOOL_V2/src/infrastructure/dart/client.py` (corpCode·list.json 부분)

- [ ] **Step 1: client.py 이식**

CC client에서 다음만 가져옴 (RP 추출 등 CC 전용 로직 제외):
- `DartError`, `_BASE`, `_CACHE_DIR`(→ `~/.risk_tool/dart_cache`)
- corpCode.xml 로드 + `find_corp_code(name) -> {corp_code, corp_name, stock_code}` (rcps `dart_financials`의 `load_corp_codes`/`find_corp_code`/`_normalize_name` 구현이 더 깔끔 → 그쪽을 복사)
- `list_disclosures(corp_code, days=365) -> list[dict]`: `list.json` 호출, 최근 1년 공시 (rcept_dt, report_nm, rcept_no) 반환

```python
def list_disclosures(self, corp_code: str, bgn_de: str, end_de: str) -> list[dict]:
    """주요사항보고서 등 공시 리스트. pblntf_ty 미지정(전체) 후 report_nm 키워드 필터는 호출측."""
    params = {"crtfc_key": self.api_key, "corp_code": corp_code,
              "bgn_de": bgn_de, "end_de": end_de, "page_count": "100"}
    resp = requests.get(f"{_BASE}/list.json", params=params, timeout=self.timeout)
    if resp.status_code != 200:
        return []
    body = resp.json()
    if body.get("status") != "000":
        return []
    return [{"rcept_dt": it.get("rcept_dt"), "report_nm": it.get("report_nm"),
             "rcept_no": it.get("rcept_no")} for it in (body.get("list") or [])]
```

- [ ] **Step 2: 임포트 스모크 테스트**

Run: `cd RISK_TOOL && python -c "from risk.infrastructure.dart.client import DartClient; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add RISK_TOOL/src/risk/infrastructure/dart/client.py
git commit -m "feat(risk): DART client 이식 (corp조회·공시 list)"
```

### Task 7: 재무 전계정 추출 (risk_extractor)

**Files:**
- Create: `RISK_TOOL/src/risk/infrastructure/dart/risk_extractor.py`
- Source 패턴: `rcps_valuation/inputs/dart_financials.py` (`fetch_financials` 구조 + 감사보고서 fallback)

핵심: `fnlttSinglAcntAll.json`은 row마다 `account_id`·`sj_div`(BS/IS/CIS/CF)·`thstrm_amount`(당기)·`frmtrm_amount`(전기)·`bfefrmtrm_amount`(전전기) 제공. 아래 account_id 맵으로 `FinancialYear` 채움.

```python
# sj_div 무관, account_id 표준태그 → FinancialYear 필드
_ACCOUNT_MAP = {
    "ifrs-full_Revenue": "revenue",
    "ifrs-full_CostOfSales": "cogs",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_ProfitLossBeforeTax": "pretax_income",
    "ifrs-full_IncomeTaxExpenseContinuingOperations": "tax_expense",
    "ifrs-full_FinanceCosts": "finance_costs",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "operating_cf",
    "ifrs-full_Assets": "total_assets",
    "ifrs-full_CurrentAssets": "current_assets",
    "ifrs-full_Liabilities": "total_liabilities",
    "ifrs-full_CurrentLiabilities": "current_liabilities",
    "ifrs-full_Equity": "total_equity",
    "ifrs-full_TradeAndOtherCurrentReceivables": "trade_receivables",
    "ifrs-full_Inventories": "inventory",
}
```

- [ ] **Step 1: 추출 단위테스트 (fixture row → FinancialYear)**

```python
# tests/unit/test_risk_extractor.py
from risk.infrastructure.dart.risk_extractor import rows_to_years


def test_rows_to_years_maps_accounts():
    rows = [
        {"account_id": "ifrs-full_Revenue", "bsns_year": "2025",
         "thstrm_amount": "1,000", "frmtrm_amount": "900"},
        {"account_id": "ifrs-full_Equity", "bsns_year": "2025",
         "thstrm_amount": "-50", "frmtrm_amount": "100"},
    ]
    years = rows_to_years(rows)
    y2025 = next(y for y in years if y.year == 2025)
    y2024 = next(y for y in years if y.year == 2024)
    assert y2025.revenue == 1000
    assert y2025.total_equity == -50
    assert y2024.revenue == 900
    assert y2024.total_equity == 100
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_risk_extractor.py -v`
Expected: FAIL

- [ ] **Step 3: rows_to_years + RiskExtractor 구현**

```python
from __future__ import annotations
import os, re
from risk.domain.financial import FinancialYear

_ACCOUNT_MAP = { ... }  # 위 맵


def _num(s):
    t = re.sub(r"[,\s]", "", str(s or ""))
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def rows_to_years(rows: list[dict]) -> list[FinancialYear]:
    """fnlttSinglAcntAll rows → FinancialYear 리스트(당기·전기). bsns_year 기준."""
    acc: dict[int, dict] = {}
    for r in rows:
        field = _ACCOUNT_MAP.get((r.get("account_id") or "").strip())
        if not field:
            continue
        by = int(re.sub(r"\D", "", str(r.get("bsns_year") or "0")) or 0)
        if not by:
            continue
        cur = _num(r.get("thstrm_amount"))
        prv = _num(r.get("frmtrm_amount"))
        if cur is not None:
            acc.setdefault(by, {})[field] = cur
        if prv is not None:
            acc.setdefault(by - 1, {})[field] = prv
    return [FinancialYear(year=y, **fields) for y, fields in sorted(acc.items())]
```

`RiskExtractor` 클래스는 rcps `fetch_financials` 흐름 복제 — 단 `_extract_periods` 대신 `rows_to_years` 사용, fs_div는 CFS 우선(연결 위험 신호 보수적):

```python
class RiskExtractor:
    def __init__(self, client):  # client: DartClient (corp조회 재활용)
        self.client = client

    def fetch(self, corp_code: str, end_year: int, max_years: int = 5) -> list[FinancialYear]:
        """end_year·end_year-2 두 사업연도 호출 → 당기·전기 병합 → 최근 max_years.
        CFS(연결) 우선, 없으면 OFS(별도). 둘 다 status≠000이면 빈 리스트 (호출측 수기입력)."""
        merged: dict[int, FinancialYear] = {}
        for yr in (end_year, end_year - 2, end_year - 4):
            rows = self._fetch_all(corp_code, yr)
            for fy in rows_to_years(rows):
                merged.setdefault(fy.year, fy)
        years = [merged[y] for y in sorted(merged)][-max_years:]
        return years

    def _fetch_all(self, corp_code, bsns_year):
        for fs_div in ("CFS", "OFS"):
            body = self.client.fnlttSinglAcntAll(corp_code, bsns_year, fs_div)
            if body:
                return body
        return []
```

> `DartClient.fnlttSinglAcntAll(corp_code, bsns_year, fs_div) -> list[dict]|None`을 Task 6 client에 추가 (rcps `_fetch_year` 동일 로직, reprt_code 11011).
> 비상장 외감 fallback(감사보고서 document.xml 파싱)은 rcps `_fetch_from_audit_reports`를 포팅하되 **계정맵을 _ACCOUNT_MAP 전체로 확장** — 표 파싱이라 BS/CF 계정 인식 품질 변동. 실패 시 빈 리스트 반환(조용히 0 금지).

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_risk_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/infrastructure/dart/risk_extractor.py RISK_TOOL/tests/unit/test_risk_extractor.py
git commit -m "feat(risk): DART 재무 전계정 추출 (CFS우선·감사보고서 fallback)"
```

---

## Phase 3 — Infrastructure: 뉴스 & LLM

### Task 8: 뉴스 리서처 포트 + 키워드

**Files:**
- Create: `RISK_TOOL/src/risk/infrastructure/news/researcher.py`

WebSearch는 도구 호출(런타임)이라 인프라는 **포트 + 키워드셋 + 결과 정규화**만. 실제 검색 실행은 application이 콜백 주입(테스트 mock 가능).

```python
from __future__ import annotations
from dataclasses import dataclass

RISK_KEYWORDS = [
    "소송", "횡령", "배임", "분식회계", "적자전환", "자본잠식", "감자", "부도",
    "영업정지", "대표이사 변경", "회생", "워크아웃", "관리종목", "상장폐지",
    "세무조사", "리콜",
]


@dataclass(frozen=True)
class NewsHit:
    title: str
    date: str
    summary: str
    url: str
    keyword: str


class NewsResearcher:
    def __init__(self, search_fn):
        """search_fn(query:str) -> list[{title,url,snippet,date}]. application이 주입."""
        self.search_fn = search_fn

    def research(self, company: str, industry: str = "") -> list[NewsHit]:
        hits: list[NewsHit] = []
        for kw in RISK_KEYWORDS:
            q = f"{company} {kw}" + (f" {industry}" if industry else "")
            try:
                results = self.search_fn(q) or []
            except Exception:
                continue
            for r in results[:2]:
                hits.append(NewsHit(title=r.get("title", ""), date=r.get("date", ""),
                                    summary=r.get("snippet", ""), url=r.get("url", ""),
                                    keyword=kw))
        return hits
```

- [ ] **Step 1: mock 테스트**

```python
# tests/unit/test_news.py
from risk.infrastructure.news.researcher import NewsResearcher


def test_research_collects_hits():
    def fake(q):
        return [{"title": q, "url": "http://x", "snippet": "s", "date": "2026-01"}]
    r = NewsResearcher(fake)
    hits = r.research("ABC회사")
    assert len(hits) >= 16  # 키워드당 최소 1
    assert all(h.url == "http://x" for h in hits)
```

- [ ] **Step 2: 실패→구현→통과**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_news.py -v`
Expected: 최종 PASS

- [ ] **Step 3: Commit**

```bash
git add RISK_TOOL/src/risk/infrastructure/news/researcher.py RISK_TOOL/tests/unit/test_news.py
git commit -m "feat(risk): 뉴스 리서처 포트 (키워드셋·search_fn 주입)"
```

### Task 9: LLM commenter

**Files:**
- Create: `RISK_TOOL/src/risk/infrastructure/llm/commenter.py`

```python
from __future__ import annotations
import os
from risk.domain.thresholds import Signal

_MODEL = "claude-opus-4-8"
_SYS = ("당신은 K-IFRS·회계감사기준 전문가입니다. 룰베이스로 산출된 위험신호를 보고 "
        "왜 위험한지·후속 확인사항·관련 경영진주장(실재성/완전성/평가/권리의무)을 "
        "감사조서용으로 간결히 서술하세요. 신호 등급은 절대 바꾸지 마세요. "
        "한국 회계용어(장부가 등) 사용.")


class Commenter:
    def __init__(self, client=None):
        self.client = client  # anthropic.Anthropic | None

    def comment_signals(self, company: str, signals: list[Signal]) -> dict[str, str]:
        """신호 code → 코멘트. client 없으면 빈 dict (degrade)."""
        flagged = [s for s in signals if s.level in ("yellow", "red")]
        if not self.client or not flagged:
            return {}
        lines = [f"- [{s.level}] {s.label}: 값 {s.value} (기준 {s.threshold})" for s in flagged]
        msg = self.client.messages.create(
            model=_MODEL, max_tokens=1500, system=_SYS,
            messages=[{"role": "user",
                       "content": f"회사: {company}\n신호:\n" + "\n".join(lines) +
                                  "\n각 신호별 한 줄 코멘트를 'code: 코멘트' 형식으로."}])
        text = msg.content[0].text
        out = {}
        for s in flagged:
            for ln in text.splitlines():
                if s.label in ln:
                    out[s.code] = ln.split(":", 1)[-1].strip()
        return out
```

- [ ] **Step 1: mock 테스트 (client None → 빈 dict)**

```python
# tests/unit/test_commenter.py
from risk.domain.thresholds import Signal
from risk.infrastructure.llm.commenter import Commenter


def test_no_client_returns_empty():
    c = Commenter(client=None)
    assert c.comment_signals("X", [Signal("a", "c", "l", "red", 1, "t")]) == {}
```

- [ ] **Step 2: 실패→구현→통과**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_commenter.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add RISK_TOOL/src/risk/infrastructure/llm/commenter.py RISK_TOOL/tests/unit/test_commenter.py
git commit -m "feat(risk): LLM commenter (신호보조·client없으면 degrade)"
```

---

## Phase 4 — Application

### Task 10: assess_risk_uc 오케스트레이션

**Files:**
- Create: `RISK_TOOL/src/risk/application/assess_risk_uc.py`
- Test: `RISK_TOOL/tests/integration/test_assess_uc.py` + `fixtures/listed_5y.json`

- [ ] **Step 1: fixture + 통합테스트 작성**

`fixtures/listed_5y.json`: 5개년 FinancialYear 직렬화 (위험신호 1개 red 유발 — 예: 최신년 자본잠식). 테스트는 extractor/news/llm을 stub으로 주입.

```python
import json, pathlib
from risk.domain.financial import FinancialYear
from risk.application.assess_risk_uc import AssessRiskUseCase, RiskResult


def _years():
    raw = json.loads((pathlib.Path(__file__).parent / "fixtures/listed_5y.json").read_text("utf-8"))
    return [FinancialYear(**y) for y in raw]


def test_assess_produces_grade_and_signals():
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: _years()})(),
        corp_resolver=lambda name: {"corp_code": "0001", "corp_name": name, "stock_code": "0"},
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
    )
    res = uc.run("테스트회사", end_year=2025)
    assert isinstance(res, RiskResult)
    assert res.grade.grade in ("높음", "보통", "낮음")
    assert len(res.signals) > 0
    assert res.materiality.pm > 0


def test_assess_handles_no_financials():
    uc = AssessRiskUseCase(
        extractor=type("E", (), {"fetch": lambda self, c, y: []})(),
        corp_resolver=lambda name: {"corp_code": "0001", "corp_name": name, "stock_code": "0"},
        news=type("N", (), {"research": lambda self, c, i="": []})(),
        commenter=type("C", (), {"comment_signals": lambda self, c, s: {}})(),
    )
    res = uc.run("없는회사", end_year=2025)
    assert res.error and "수기입력" in res.error
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/integration/test_assess_uc.py -v`
Expected: FAIL

- [ ] **Step 3: assess_risk_uc.py 구현**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from risk.domain.financial import FinancialYear
from risk.domain.materiality import performance_materiality, Materiality
from risk.domain.thresholds import evaluate_axes, Signal
from risk.domain.risk_grade import overall_grade, RiskGrade


@dataclass
class RiskResult:
    company: str
    years: list[FinancialYear]
    materiality: Materiality | None
    signals: list[Signal] = field(default_factory=list)
    grade: RiskGrade | None = None
    comments: dict[str, str] = field(default_factory=dict)
    news: list = field(default_factory=list)
    error: str = ""


class AssessRiskUseCase:
    def __init__(self, extractor, corp_resolver, news, commenter):
        self.extractor = extractor
        self.corp_resolver = corp_resolver  # name -> {corp_code,...}|None
        self.news = news
        self.commenter = commenter

    def run(self, company: str, end_year: int) -> RiskResult:
        corp = self.corp_resolver(company)
        if not corp:
            return RiskResult(company, [], None,
                              error="DART에서 회사를 찾지 못했습니다. 회사명 확인 또는 수기입력.")
        years = self.extractor.fetch(corp["corp_code"], end_year)
        if not years:
            return RiskResult(company, [], None,
                              error="DART 재무자료 없음 — 과거실적 수기입력 필요.")
        try:
            pm = performance_materiality(years[-1])
        except ValueError as e:
            return RiskResult(company, years, None, error=str(e))
        signals = evaluate_axes(years, pm)
        grade = overall_grade(signals)
        comments = self.commenter.comment_signals(company, signals)
        news = self.news.research(company)
        return RiskResult(company, years, pm, signals, grade, comments, news)
```

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/integration/test_assess_uc.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/application/assess_risk_uc.py RISK_TOOL/tests/integration/
git commit -m "feat(risk): assess_risk 유스케이스 (수집→평가→코멘트·degrade)"
```

---

## Phase 5 — Excel 조서

### Task 11: ISA 315 위험평가 W/P

**Files:**
- Create: `RISK_TOOL/src/risk/infrastructure/excel/workpaper.py`
- Test: `RISK_TOOL/tests/unit/test_workpaper.py`

시트: 표지 / 재무요약 / 위험평가매트릭스 / 4축신호상세 / 외부리스크 / 후속절차.

- [ ] **Step 1: 생성 스모크 테스트 (파일 열림·시트 존재)**

```python
# tests/unit/test_workpaper.py
import openpyxl
from risk.application.assess_risk_uc import RiskResult
from risk.domain.financial import FinancialYear
from risk.domain.materiality import Materiality
from risk.domain.risk_grade import RiskGrade
from risk.infrastructure.excel.workpaper import build_workpaper


def test_workpaper_sheets(tmp_path):
    res = RiskResult("테스트", [FinancialYear(2025, revenue=1000)],
                     Materiality(5, 3.75, "revenue"),
                     signals=[], grade=RiskGrade("낮음", 0, 0))
    p = tmp_path / "wp.xlsx"
    build_workpaper(res, str(p))
    wb = openpyxl.load_workbook(p)
    assert "표지" in wb.sheetnames
    assert "위험평가매트릭스" in wb.sheetnames
```

- [ ] **Step 2: 실패 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_workpaper.py -v`
Expected: FAIL

- [ ] **Step 3: workpaper.py 구현**

```python
from __future__ import annotations
import openpyxl
from openpyxl.styles import Font, PatternFill
from risk.application.assess_risk_uc import RiskResult

_FILL = {"red": PatternFill("solid", fgColor="FFC7CE"),
         "yellow": PatternFill("solid", fgColor="FFEB9C"),
         "green": PatternFill("solid", fgColor="C6EFCE")}
_FOLLOWUP = {
    "ar_turnover": "매출채권 조회·기수령 검토·연령분석",
    "accrual_quality": "발생액 분석·수익인식 cutoff 검토",
    "debt_ratio": "차입약정 위반·만기구조·계속기업 평가",
    "interest_coverage": "계속기업 가정·차입금 상환능력 검토",
    "revenue_change": "수익인식 정책·이상거래 표본 검토",
}


def build_workpaper(res: RiskResult, path: str) -> str:
    wb = openpyxl.Workbook()
    # 표지
    ws = wb.active; ws.title = "표지"
    ws["A1"] = "감사전 위험평가 조서 (ISA 315)"; ws["A1"].font = Font(bold=True, size=14)
    ws["A3"] = "대상회사"; ws["B3"] = res.company
    ws["A4"] = "종합위험등급"; ws["B4"] = res.grade.grade if res.grade else "-"
    if res.materiality:
        ws["A5"] = "수행중요성(PM)"; ws["B5"] = res.materiality.pm
        ws["A6"] = "중요성 benchmark"; ws["B6"] = res.materiality.benchmark
    if res.error:
        ws["A8"] = "오류"; ws["B8"] = res.error

    # 재무요약
    ws2 = wb.create_sheet("재무요약")
    ws2.append(["연도", "매출", "영업이익", "당기순이익", "자산", "부채", "자본", "영업CF"])
    for y in res.years:
        ws2.append([y.year, y.revenue, y.operating_income, y.net_income,
                    y.total_assets, y.total_liabilities, y.total_equity, y.operating_cf])

    # 위험평가매트릭스 (계정×주장은 신호 매핑 요약)
    ws3 = wb.create_sheet("위험평가매트릭스")
    ws3.append(["축", "지표", "신호", "값", "기준", "AI코멘트"])
    for s in res.signals:
        row = [s.axis, s.label, s.level, s.value, s.threshold, res.comments.get(s.code, "")]
        ws3.append(row)
        ws3.cell(ws3.max_row, 3).fill = _FILL.get(s.level, _FILL["green"])

    # 4축신호상세
    ws4 = wb.create_sheet("신호상세")
    ws4.append(["축", "code", "지표", "신호", "값", "기준", "비고"])
    for s in res.signals:
        ws4.append([s.axis, s.code, s.label, s.level, s.value, s.threshold, s.note])

    # 외부리스크
    ws5 = wb.create_sheet("외부리스크")
    ws5.append(["키워드", "제목", "날짜", "요약", "출처"])
    for h in res.news:
        ws5.append([getattr(h, "keyword", ""), getattr(h, "title", ""),
                    getattr(h, "date", ""), getattr(h, "summary", ""), getattr(h, "url", "")])
    if not res.news:
        ws5.append(["", "특이사항 없음", "", "", ""])

    # 후속절차
    ws6 = wb.create_sheet("후속감사절차")
    ws6.append(["지표", "신호", "권고절차"])
    for s in res.signals:
        if s.level in ("yellow", "red"):
            ws6.append([s.label, s.level, _FOLLOWUP.get(s.code, "추가 검토 절차 설계")])

    wb.save(path)
    return path
```

- [ ] **Step 4: 통과 확인**

Run: `cd RISK_TOOL && python -m pytest tests/unit/test_workpaper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add RISK_TOOL/src/risk/infrastructure/excel/workpaper.py RISK_TOOL/tests/unit/test_workpaper.py
git commit -m "feat(risk): ISA 315 위험평가 Excel 조서 (6시트·신호색상·후속절차)"
```

---

## Phase 6 — Interface: API + 대시보드

### Task 12: FastAPI 라우트

**Files:**
- Create: `RISK_TOOL/src/risk/interface/api/app.py`, `RISK_TOOL/run_server.py`

- [ ] **Step 1: app.py 구현**

```python
from __future__ import annotations
import os, io
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pathlib, tempfile

from risk.infrastructure.dart.client import DartClient
from risk.infrastructure.dart.risk_extractor import RiskExtractor
from risk.infrastructure.news.researcher import NewsResearcher
from risk.infrastructure.llm.commenter import Commenter
from risk.application.assess_risk_uc import AssessRiskUseCase
from risk.infrastructure.excel.workpaper import build_workpaper
from dataclasses import asdict

app = FastAPI(title="감사전 리스크 확인 툴")
_FRONT = pathlib.Path(__file__).parent / "frontend"


def _build_uc():
    client = DartClient(api_key=os.environ.get("DART_API_KEY", ""))
    extractor = RiskExtractor(client)
    # WebSearch는 런타임 도구 → 서버에선 None search_fn(축4 degrade) 기본
    news = NewsResearcher(search_fn=lambda q: [])
    try:
        import anthropic
        llm = Commenter(anthropic.Anthropic()) if os.environ.get("ANTHROPIC_API_KEY") else Commenter(None)
    except Exception:
        llm = Commenter(None)
    return AssessRiskUseCase(extractor, client.find_corp_code, news, llm)


class AssessReq(BaseModel):
    company: str
    end_year: int


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/assess")
def assess(req: AssessReq):
    uc = _build_uc()
    res = uc.run(req.company, req.end_year)
    return JSONResponse({
        "company": res.company, "error": res.error,
        "grade": asdict(res.grade) if res.grade else None,
        "materiality": asdict(res.materiality) if res.materiality else None,
        "signals": [asdict(s) for s in res.signals],
        "comments": res.comments,
        "years": [asdict(y) for y in res.years],
        "news": [vars(h) for h in res.news],
    })


@app.post("/api/export")
def export(req: AssessReq):
    uc = _build_uc()
    res = uc.run(req.company, req.end_year)
    tmp = pathlib.Path(tempfile.gettempdir()) / f"risk_{req.company}_{req.end_year}.xlsx"
    build_workpaper(res, str(tmp))
    return FileResponse(str(tmp), filename=tmp.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


app.mount("/", StaticFiles(directory=str(_FRONT), html=True), name="static")
```

- [ ] **Step 2: run_server.py**

```python
import uvicorn
if __name__ == "__main__":
    uvicorn.run("risk.interface.api.app:app", host="127.0.0.1", port=8533, reload=False)
```

> 포트 8533 (기존 점유 확인: rcps·jet·cc 8521·bc 8766와 충돌 없음).

- [ ] **Step 3: 헬스 스모크**

Run: `cd RISK_TOOL && PYTHONPATH=src python -c "from risk.interface.api.app import app; print([r.path for r in app.routes])"`
Expected: `/healthz`, `/api/assess`, `/api/export` 포함 출력

- [ ] **Step 4: Commit**

```bash
git add RISK_TOOL/src/risk/interface/api/app.py RISK_TOOL/run_server.py
git commit -m "feat(risk): FastAPI 라우트 (assess·export·healthz, port 8533)"
```

### Task 13: WAT 셸 대시보드

**Files:**
- Create: `RISK_TOOL/src/risk/interface/api/frontend/index.html`

WAT 셸 표준 적용: 헤더 padding-left 7.25rem, 푸터 통일 문구(`Disclaimer.…` + `© 2026 Woongcpa`), `body.tool-mode` 호환.

- [ ] **Step 1: index.html 구현**

회사명 + 기준연도 입력 → `/api/assess` POST → 종합등급 신호등 배지 + 4축 카드(신호 색상) + 뉴스 리스트 + "조서 내보내기"(→ `/api/export` 다운로드). 신호등 색: red `#FFC7CE`, yellow `#FFEB9C`, green `#C6EFCE`.

```html
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>감사전 리스크 확인 툴</title>
<style>
:root{--bg:#0f1115;--card:#1a1d24;--text:#e7e9ee;--text2:#9aa0ab}
body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,'Malgun Gothic',sans-serif}
header{padding:1rem 1rem 1rem 7.25rem;border-bottom:1px solid #2a2e38}
main{max-width:1100px;margin:0 auto;padding:1.5rem}
.row{display:flex;gap:.6rem;flex-wrap:wrap;align-items:end}
input,button{padding:.55rem .8rem;border-radius:8px;border:1px solid #353a45;background:var(--card);color:var(--text)}
button{cursor:pointer;background:#3b82f6;border-color:#3b82f6}
.grade{display:inline-block;padding:.4rem 1rem;border-radius:999px;font-weight:700}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:.8rem;margin-top:1rem}
.card{background:var(--card);border:1px solid #2a2e38;border-radius:12px;padding:1rem}
.sig{display:flex;justify-content:space-between;padding:.3rem 0;border-bottom:1px solid #23262f;font-size:.9rem}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:.4rem}
footer.legal{padding:1rem;color:var(--text2);font-size:.7rem;border-top:1px solid #2a2e38;margin-top:2rem}
</style></head><body>
<header><h1 style="margin:0;font-size:1.1rem">감사전 리스크 확인 툴 · Pre-Audit Risk</h1></header>
<main>
  <div class="row">
    <div><label>회사명<br><input id="company" placeholder="예: 삼성전자"></label></div>
    <div><label>기준연도<br><input id="year" type="number" value="2025"></label></div>
    <button onclick="run()">리스크 분석</button>
    <button onclick="exp()" style="background:#10b981;border-color:#10b981">조서 내보내기</button>
  </div>
  <div id="status" style="margin-top:1rem;color:var(--text2)"></div>
  <div id="result"></div>
</main>
<footer class="legal">
  <div><b>Disclaimer.</b> 본 도구는 회계감사 실무 보조용 참고자료이며, 최종 판단과 책임은 사용자에게 있습니다.</div>
  <div>© 2026 Woongcpa</div>
</footer>
<script>
const C={red:'#FFC7CE',yellow:'#FFEB9C',green:'#C6EFCE'};
const AX={analytical:'분석적검토',fraud:'부정위험',going_concern:'계속기업'};
async function run(){
  const company=company_.value, year=+year_.value;
  status_.textContent='DART 조회·분석 중…';
  const r=await fetch('/api/assess',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({company,end_year:year})});
  const d=await r.json(); status_.textContent='';
  if(d.error){result_.innerHTML='<div class="card">⚠ '+d.error+'</div>';return;}
  const gc={높음:C.red,보통:C.yellow,낮음:C.green}[d.grade.grade];
  let html='<p>종합위험등급: <span class="grade" style="background:'+gc+';color:#111">'+d.grade.grade
    +'</span> (적 '+d.grade.red+' · 황 '+d.grade.yellow+')</p><div class="cards">';
  for(const ax of Object.keys(AX)){
    const sigs=d.signals.filter(s=>s.axis===ax);
    html+='<div class="card"><b>'+AX[ax]+'</b>';
    for(const s of sigs){html+='<div class="sig"><span><span class="dot" style="background:'
      +C[s.level]+'"></span>'+s.label+'</span><span>'+(s.value==null?'-':(+s.value).toFixed(1))+'</span></div>';
      if(d.comments[s.code])html+='<div style="font-size:.78rem;color:var(--text2)">'+d.comments[s.code]+'</div>';}
    html+='</div>';
  }
  html+='</div>';
  if(d.news&&d.news.length){html+='<h3>외부 리스크</h3>';for(const n of d.news)
    html+='<div class="sig"><a href="'+n.url+'" target="_blank" style="color:#7aa2f7">['+n.keyword+'] '+n.title+'</a></div>';}
  result_.innerHTML=html;
}
async function exp(){
  const r=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({company:company_.value,end_year:+year_.value})});
  const b=await r.blob(),u=URL.createObjectURL(b),a=document.createElement('a');
  a.href=u;a.download='risk_'+company_.value+'.xlsx';a.click();URL.revokeObjectURL(u);
}
const company_=document.getElementById('company'),year_=document.getElementById('year'),
  status_=document.getElementById('status'),result_=document.getElementById('result');
</script></body></html>
```

- [ ] **Step 2: 수동 확인 (서버 기동)**

Run: `cd RISK_TOOL && set DART_API_KEY=... && PYTHONPATH=src python run_server.py` 후 `http://127.0.0.1:8533/` 접속 → 회사명 입력·분석 → 신호등 표시 확인.

- [ ] **Step 3: Commit**

```bash
git add RISK_TOOL/src/risk/interface/api/frontend/index.html
git commit -m "feat(risk): WAT 셸 대시보드 (신호등·4축카드·조서내보내기)"
```

---

## Phase 7 — 통합 검증 & 마무리

### Task 14: 전체 테스트 + WAT 런처 등록

**Files:**
- Modify: `WAT/index.html` (TOOLS 등록 — 단 난독화 JS라 평문 영역만; 어려우면 별도 후속)
- Verify: 전체 pytest

- [ ] **Step 1: 전체 단위·통합 테스트**

Run: `cd RISK_TOOL && PYTHONPATH=src python -m pytest -v`
Expected: 전부 PASS (materiality 3 + indicators 8 + thresholds 6 + risk_grade 4 + extractor 1 + news 1 + commenter 1 + workpaper 1 + assess 2)

- [ ] **Step 2: 실서버 healthz 확인**

Run: `cd RISK_TOOL && PYTHONPATH=src python run_server.py` (백그라운드) → `curl http://127.0.0.1:8533/healthz`
Expected: `{"ok":true}`

- [ ] **Step 3: 라이브 DART 1건 (DART_API_KEY 있을 때)**

상장사 1곳 `/api/assess` 호출 → grade·signals 정상. 자료없으면 error 메시지 노출 확인(조용한 0 아님).

- [ ] **Step 4: Commit**

```bash
git add -A RISK_TOOL/
git commit -m "test(risk): 전체 통합검증 통과 (19 tests)"
```

---

## Self-Review 결과 (작성자 점검)

- **Spec 커버리지**: 4축(분석적/부정/GC=Task4, 외부=Task8) ✓, PM 이중게이트(Task2·4) ✓, DART 상장+외감(Task7) ✓, AI코멘트(Task9) ✓, 뉴스(Task8) ✓, Excel 6시트(Task11) ✓, 대시보드(Task13) ✓, 에러 degrade·수기입력(Task7·10) ✓, 테스트(전 Phase) ✓.
- **알려진 보정점**: ① `thresholds.py`에 `_band_low` 중복 정의 — 구현 시 1회만. ② DART account_id는 회사별 변형 가능 — Task7 라이브 검증에서 누락계정 확인·맵 보강. ③ WebSearch 서버측 연결은 런타임 도구 제약 → 기본 degrade, 실검색은 후속(MCP/배치) 과제. ④ 감사보고서 PDF fallback 포팅은 표 인식 품질 변동 — 실데이터 검증 필수(`bc_rowparser_realdata_bugs` 교훈).
- **타입 일관성**: `FinancialYear`·`Signal`·`Materiality`·`RiskGrade`·`RiskResult` 시그니처 태스크 간 일치 확인.
