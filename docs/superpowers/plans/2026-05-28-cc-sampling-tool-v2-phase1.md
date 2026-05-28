# CC_SAMPLING_TOOL_V2 Phase 1 — Skeleton + Domain Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 디렉토리·Flask 부트·SQLAlchemy 모델·순수 도메인 로직(7개 모듈) + 단위테스트 작성. Phase 1 종료 시 `pytest tests/unit -q` 그린.

**Architecture:** Clean architecture — `src/domain/` 순수 함수·dataclass (pandas·Flask·SQLAlchemy import 금지), `src/infrastructure/db/` SQLAlchemy 모델, `api/app.py` Flask app factory (라우트 미등록). TDD 빨강→초록→리팩토링.

**Tech Stack:** Python 3.11+, Flask 3.x, SQLAlchemy 2.x, pytest, dataclasses, numpy, pandas (infrastructure only).

**Spec 참조:** [2026-05-28-cc-sampling-tool-v2-design.md](../specs/2026-05-28-cc-sampling-tool-v2-design.md)

**Phase 1 마일스톤:** `cd CC_SAMPLING_TOOL_V2 && pytest tests/unit -q` 모두 PASS. API·UI는 Phase 2 이후.

---

## File Structure

생성 파일 (Phase 1):

```
CC_SAMPLING_TOOL_V2/
├── api/
│   ├── __init__.py
│   └── app.py                              # Flask app factory만 (라우트 X)
├── src/
│   ├── __init__.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── entities.py                     # dataclass 7개
│   │   ├── sampling/
│   │   │   ├── __init__.py
│   │   │   ├── sample_size.py              # AAG-SAM
│   │   │   ├── mus.py                      # PPS 선택
│   │   │   ├── stratified.py               # 다단계 + fallback
│   │   │   └── classification.py           # KEY/RP/BAD
│   │   ├── projection/
│   │   │   ├── __init__.py
│   │   │   └── pps.py                      # tainting·upper limit
│   │   ├── fx.py                           # 외화 환산
│   │   ├── allowance.py                    # 대손충당금
│   │   └── matching.py                     # 회신 차이판정
│   └── infrastructure/
│       ├── __init__.py
│       └── db/
│           ├── __init__.py
│           ├── models.py                   # SQLAlchemy 모델
│           └── session.py                  # engine·sessionmaker
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── unit/
│       ├── __init__.py
│       ├── test_entities.py
│       ├── test_sample_size.py
│       ├── test_mus.py
│       ├── test_stratified.py
│       ├── test_classification.py
│       ├── test_projection.py
│       ├── test_fx.py
│       ├── test_allowance.py
│       ├── test_matching.py
│       └── test_db_models.py
├── requirements.txt
├── pytest.ini
└── README.md
```

**책임 분리**:
- `entities.py` — 모든 도메인 dataclass (Project, Account, Sample, ...)
- `sampling/*` — 표본설계 알고리즘 (각 1 파일 1 책임)
- `projection/pps.py` — ISA 530 모집단오차 추정 (분리 가능성 위해 패키지로)
- `fx.py`, `allowance.py`, `matching.py` — 단순 함수 모듈
- `infrastructure/db/models.py` — DB ORM. domain entity와 1:1 매핑하나 분리 (clean arch)

---

## 작업 순서

1. **Task 1**: 프로젝트 스캐폴딩
2. **Task 2**: 도메인 entities (dataclass)
3. **Task 3**: Sample size (AAG-SAM)
4. **Task 4**: MUS PPS 선택
5. **Task 5**: FX 환산
6. **Task 6**: Allowance 판정
7. **Task 7**: Classification (KEY/RP/BAD)
8. **Task 8**: Stratification + fallback
9. **Task 9**: Matching 차이판정
10. **Task 10**: PPS Projection
11. **Task 11**: SQLAlchemy DB models
12. **Task 12**: Flask app factory + Phase 1 회귀 confirm

---

### Task 1: 프로젝트 스캐폴딩

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/requirements.txt`
- Create: `CC_SAMPLING_TOOL_V2/pytest.ini`
- Create: `CC_SAMPLING_TOOL_V2/README.md`
- Create: 디렉토리 + `__init__.py` (10개)

- [ ] **Step 1: 디렉토리·빈 파일 생성 + tests/conftest.py (Python path 보정)**

```bash
cd c:/Claude
mkdir -p CC_SAMPLING_TOOL_V2/{api,src/domain/sampling,src/domain/projection,src/infrastructure/db,tests/unit}
cd CC_SAMPLING_TOOL_V2
touch api/__init__.py src/__init__.py src/domain/__init__.py \
      src/domain/sampling/__init__.py src/domain/projection/__init__.py \
      src/infrastructure/__init__.py src/infrastructure/db/__init__.py \
      tests/__init__.py tests/unit/__init__.py
```

`tests/conftest.py` 즉시 작성 (이후 모든 task의 import 보장):

```python
"""tests 루트 conftest — src/ api/ 패키지 import 보장."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
```

- [ ] **Step 2: requirements.txt**

```
flask>=3.0
sqlalchemy>=2.0
openpyxl>=3.1
pandas>=2.0
numpy>=1.24
pyyaml>=6.0
pdfplumber>=0.11
pytest>=8.0
pytest-cov>=5.0
```

- [ ] **Step 3: pytest.ini**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra --strict-markers
filterwarnings =
    ignore::DeprecationWarning
```

- [ ] **Step 4: README.md**

```markdown
# CC_SAMPLING_TOOL_V2

채권채무조회서 샘플링·회수 툴 V2 (재설계).

설계서: `docs/superpowers/specs/2026-05-28-cc-sampling-tool-v2-design.md`

## 설치
\`\`\`
pip install -r requirements.txt
\`\`\`

## 테스트
\`\`\`
pytest tests/unit -q
\`\`\`
```

- [ ] **Step 5: 의존성 설치 확인**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pip install -r requirements.txt`
Expected: 모든 패키지 설치 OK.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/
git -C c:/Claude commit -m "chore: CC_SAMPLING_TOOL_V2 scaffolding"
```

---

### Task 2: 도메인 entities

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/entities.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_entities.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_entities.py`:

```python
import pytest
from datetime import date
from src.domain.entities import (
    Project, Account, Sample, Confirmation,
    AlternativeProcedure, ProjectionResult, Strata,
    Kind, SelectionReason, Verdict,
)


def test_project_defaults():
    p = Project(
        client="ACME", period_end=date(2025, 12, 31),
        base_ccy="KRW", materiality=500_000_000, tolerable=250_000_000,
    )
    assert p.materiality == 500_000_000
    assert p.tolerable == 250_000_000


def test_account_balance_krw_default():
    a = Account(party_id="P1", name="갑", gl_account="11200",
                balance_orig=1000, ccy="USD", fx_rate=1300,
                balance_krw=1_300_000)
    assert a.balance_krw == 1_300_000
    assert a.is_related_party is False
    assert a.is_bad_debt is False
    assert a.allowance_amt == 0


def test_kind_enum_values():
    assert Kind.AR.value == "AR"
    assert Kind.AP.value == "AP"


def test_selection_reason_priority():
    # Higher value = higher priority for resolution
    order = [
        SelectionReason.EXCLUDED_BAD,
        SelectionReason.EXCLUDED_ZERO,
        SelectionReason.FORCED_RP,
        SelectionReason.FORCED_KEY,
        SelectionReason.REP,
    ]
    # 모두 distinct
    assert len({r.value for r in order}) == 5


def test_sample_holds_accounts():
    a1 = Account(party_id="P1", name="갑", gl_account="11200",
                 balance_orig=100, ccy="KRW", fx_rate=1, balance_krw=100)
    s = Sample(kind=Kind.AR, accounts=[(a1, SelectionReason.FORCED_RP)])
    assert len(s.accounts) == 1
    assert s.accounts[0][1] == SelectionReason.FORCED_RP


def test_strata_range():
    st = Strata(low=0, high=1_000_000, n_required=10)
    assert st.contains(500_000) is True
    assert st.contains(1_000_001) is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/unit/test_entities.py -v`
Expected: ImportError — entities module not found.

- [ ] **Step 3: entities.py 구현**

`src/domain/entities.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class Kind(str, Enum):
    AR = "AR"  # 채권 (매출채권 등)
    AP = "AP"  # 채무 (매입채무 등)


class SelectionReason(str, Enum):
    EXCLUDED_BAD = "EXCLUDED_BAD"
    EXCLUDED_ZERO = "EXCLUDED_ZERO"
    FORCED_RP = "FORCED_RP"
    FORCED_KEY = "FORCED_KEY"
    REP = "REP"


class Verdict(str, Enum):
    MATCH = "MATCH"
    RECONCILED = "RECONCILED"
    DISCREPANCY = "DISCREPANCY"
    NO_RESPONSE = "NO_RESPONSE"


class ResponseStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    NO_RESPONSE = "NO_RESPONSE"
    EXTRACT_FAILED = "EXTRACT_FAILED"


@dataclass
class Project:
    client: str
    period_end: date
    base_ccy: str
    materiality: float
    tolerable: float
    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Account:
    party_id: str
    name: str
    gl_account: str
    balance_orig: float
    ccy: str
    fx_rate: float
    balance_krw: float
    is_related_party: bool = False
    is_bad_debt: bool = False
    allowance_amt: float = 0.0
    aging_bucket: Optional[str] = None
    src_sheet: Optional[str] = None
    src_row: Optional[int] = None

    @property
    def allowance_ratio(self) -> float:
        if abs(self.balance_orig) < 1e-9:
            return 0.0
        return self.allowance_amt / abs(self.balance_orig)


@dataclass
class Strata:
    low: float
    high: float
    n_required: int

    def contains(self, amount: float) -> bool:
        return self.low <= amount <= self.high


@dataclass
class Sample:
    kind: Kind
    accounts: list[tuple[Account, SelectionReason]] = field(default_factory=list)


@dataclass
class Confirmation:
    kind: Kind
    account_party_id: str
    expected: float
    status: ResponseStatus = ResponseStatus.PENDING
    confirmed: Optional[float] = None
    diff: Optional[float] = None
    diff_reason: Optional[str] = None
    pdf_path: Optional[str] = None
    verdict: Optional[Verdict] = None
    sent_at: Optional[datetime] = None
    extracted_at: Optional[datetime] = None


@dataclass
class AlternativeProcedure:
    kind: Kind
    account_party_id: str
    procedure_type: str
    evidence_sum: float
    coverage_pct: float = 0.0


@dataclass
class ProjectionResult:
    kind: Kind
    projected_misstatement: float
    basic_precision: float
    incremental_allowance: float
    upper_limit: float
    tolerable: float
    verdict: str  # "WITHIN_TOLERABLE" or "EXCEED"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_entities.py -v`
Expected: 6 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/entities.py CC_SAMPLING_TOOL_V2/tests/unit/test_entities.py
git -C c:/Claude commit -m "feat(domain): entities (Project/Account/Sample/Confirmation/Projection)"
```

---

### Task 3: Sample size (AAG-SAM)

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/sampling/sample_size.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_sample_size.py`

설계 5.1 식: `n = (BV × RF) / (TM − EM × ExpansionFactor)`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_sample_size.py`:

```python
import pytest
from src.domain.sampling.sample_size import (
    reliability_factor, expansion_factor, sample_size_mus,
)


@pytest.mark.parametrize("confidence,rf", [
    (0.99, 4.61),
    (0.95, 3.00),
    (0.90, 2.31),
    (0.80, 1.61),
])
def test_reliability_factor(confidence, rf):
    assert reliability_factor(confidence) == pytest.approx(rf, abs=0.01)


def test_reliability_factor_invalid():
    with pytest.raises(ValueError):
        reliability_factor(0.5)  # 미지원


def test_expansion_factor_zero_em():
    assert expansion_factor(0.95, em_ratio=0.0) == pytest.approx(1.0, abs=0.01)


def test_expansion_factor_increases_with_em():
    f_low = expansion_factor(0.95, em_ratio=0.1)
    f_high = expansion_factor(0.95, em_ratio=0.5)
    assert f_high > f_low


def test_sample_size_basic():
    n = sample_size_mus(
        book_value=10_000_000_000,
        confidence=0.95,
        tolerable=500_000_000,
        expected_ms=0,
    )
    # n = (10B × 3.0) / 500M = 60
    assert n == 60


def test_sample_size_with_em():
    n = sample_size_mus(
        book_value=10_000_000_000,
        confidence=0.95,
        tolerable=500_000_000,
        expected_ms=100_000_000,  # 20% of tolerable
    )
    # n_base = 60, expanded due to EM > 0
    assert n > 60


def test_sample_size_invalid_when_em_geq_tm():
    with pytest.raises(ValueError):
        sample_size_mus(10_000_000_000, 0.95, 500_000_000, 600_000_000)


def test_sample_size_round_up():
    n = sample_size_mus(
        book_value=1_000_000_000,
        confidence=0.95,
        tolerable=100_000_000,
        expected_ms=0,
    )
    # 10×3 = 30 — exact
    assert n == 30
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_sample_size.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/sampling/sample_size.py`:

```python
"""AAG-SAM 기반 MUS 표본규모 산정.

근거: AICPA Audit Guide — Audit Sampling (AAG-SAM), Table A-2 (신뢰계수),
Table A-3 (Expansion Factor).
"""
from __future__ import annotations
import math


# AAG-SAM Table A-2: Reliability factors at zero misstatement
_RF_TABLE = {
    0.99: 4.61,
    0.95: 3.00,
    0.90: 2.31,
    0.80: 1.61,
}

# AAG-SAM Table A-3: Expansion Factor for Expected Misstatement
# 키: 신뢰수준, 값: (em_ratio → factor) 선형보간용
_EXPANSION_TABLE = {
    0.99: [(0.0, 1.00), (0.1, 1.60), (0.3, 1.90), (0.5, 2.30)],
    0.95: [(0.0, 1.00), (0.1, 1.50), (0.3, 1.75), (0.5, 2.00)],
    0.90: [(0.0, 1.00), (0.1, 1.40), (0.3, 1.60), (0.5, 1.80)],
    0.80: [(0.0, 1.00), (0.1, 1.30), (0.3, 1.50), (0.5, 1.70)],
}


def reliability_factor(confidence: float) -> float:
    """신뢰수준에 대응하는 reliability factor 반환."""
    if confidence not in _RF_TABLE:
        raise ValueError(
            f"unsupported confidence {confidence!r}; "
            f"choose from {sorted(_RF_TABLE)}"
        )
    return _RF_TABLE[confidence]


def expansion_factor(confidence: float, em_ratio: float) -> float:
    """예상오차 비율 (EM/TM)에 따른 Expansion Factor (선형보간)."""
    if confidence not in _EXPANSION_TABLE:
        raise ValueError(f"unsupported confidence {confidence!r}")
    if em_ratio < 0:
        raise ValueError("em_ratio must be >= 0")

    points = _EXPANSION_TABLE[confidence]
    if em_ratio >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= em_ratio <= x1:
            if x1 == x0:
                return y0
            t = (em_ratio - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[0][1]


def sample_size_mus(
    book_value: float,
    confidence: float,
    tolerable: float,
    expected_ms: float,
) -> int:
    """MUS 표본규모.

    n = (BV × RF) / (TM − EM × ExpansionFactor)

    Args:
        book_value: 모집단 장부가 (외화 환산 후 base_ccy).
        confidence: 신뢰수준 (0.80/0.90/0.95/0.99).
        tolerable: tolerable misstatement.
        expected_ms: expected misstatement.

    Returns:
        표본수 (올림).

    Raises:
        ValueError: EM × ExpansionFactor ≥ TM 인 경우 (표본 불가능).
    """
    rf = reliability_factor(confidence)
    em_ratio = expected_ms / tolerable if tolerable > 0 else 0
    ef = expansion_factor(confidence, em_ratio)

    denom = tolerable - expected_ms * ef
    if denom <= 0:
        raise ValueError(
            f"EM × ExpansionFactor ({expected_ms * ef:.0f}) "
            f">= tolerable ({tolerable:.0f}) — sample design impossible"
        )
    return math.ceil((book_value * rf) / denom)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_sample_size.py -v`
Expected: 8 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/sampling/sample_size.py CC_SAMPLING_TOOL_V2/tests/unit/test_sample_size.py
git -C c:/Claude commit -m "feat(domain): MUS sample size (AAG-SAM Table A-2/A-3)"
```

---

### Task 4: MUS PPS 선택

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/sampling/mus.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_mus.py`

설계 5.2: 누적잔액 기반 systematic PPS.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_mus.py`:

```python
import pytest
from src.domain.entities import Account
from src.domain.sampling.mus import pps_select


def _acc(pid, balance):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_pps_deterministic_with_seed():
    accs = [_acc(f"P{i}", (i + 1) * 100) for i in range(10)]
    s1 = pps_select(accs, n=3, seed=42)
    s2 = pps_select(accs, n=3, seed=42)
    assert [a.party_id for a in s1] == [a.party_id for a in s2]


def test_pps_returns_n_accounts():
    accs = [_acc(f"P{i}", 100) for i in range(20)]
    s = pps_select(accs, n=5, seed=0)
    assert len(s) == 5


def test_pps_larger_balances_more_likely():
    """PPS = probability proportional to size."""
    accs = [_acc("small", 1), _acc("big", 9999)]
    s = pps_select(accs, n=1, seed=0)
    # big has ~99.99% probability — likely selected
    assert s[0].party_id == "big"


def test_pps_n_zero_returns_empty():
    accs = [_acc("a", 100)]
    assert pps_select(accs, n=0, seed=0) == []


def test_pps_n_geq_population_returns_all():
    accs = [_acc("a", 100), _acc("b", 200)]
    s = pps_select(accs, n=5, seed=0)
    assert {a.party_id for a in s} == {"a", "b"}


def test_pps_skips_zero_balance():
    accs = [_acc("zero", 0), _acc("real", 1000)]
    s = pps_select(accs, n=1, seed=0)
    assert s[0].party_id == "real"


def test_pps_negative_balance_uses_abs():
    accs = [_acc("refund", -5000), _acc("normal", 1)]
    s = pps_select(accs, n=1, seed=0)
    assert s[0].party_id == "refund"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_mus.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/sampling/mus.py`:

```python
"""MUS systematic PPS 선택.

설계서 5.2.
"""
from __future__ import annotations
import random
from typing import Optional
from src.domain.entities import Account


def pps_select(
    accounts: list[Account],
    n: int,
    seed: Optional[int] = None,
) -> list[Account]:
    """누적잔액 기반 systematic PPS.

    각 acc는 |balance_krw| 비례 확률로 선정. n ≥ population 이면 모두 반환.

    Args:
        accounts: 후보 모집단.
        n: 추출 개수.
        seed: 결정적 추출용. None이면 매 호출 다름 (운영용).

    Returns:
        선정된 Account 리스트 (입력 순서 유지).
    """
    if n <= 0:
        return []

    positives = [a for a in accounts if abs(a.balance_krw) > 1e-9]
    if not positives:
        return []
    if n >= len(positives):
        return list(positives)

    cumsum = []
    running = 0.0
    for a in positives:
        running += abs(a.balance_krw)
        cumsum.append(running)
    total = cumsum[-1]
    interval = total / n

    rng = random.Random(seed)
    start = rng.uniform(0, interval)

    selected: list[Account] = []
    j = 0
    for i in range(n):
        target = start + i * interval
        while j < len(positives) and cumsum[j] < target:
            j += 1
        if j >= len(positives):
            break
        if not selected or selected[-1] is not positives[j]:
            selected.append(positives[j])

    return selected
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_mus.py -v`
Expected: 7 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/sampling/mus.py CC_SAMPLING_TOOL_V2/tests/unit/test_mus.py
git -C c:/Claude commit -m "feat(domain): MUS systematic PPS selection"
```

---

### Task 5: FX 환산

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/fx.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_fx.py`

설계 5.5: 기말환율 환산.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_fx.py`:

```python
import pytest
from src.domain.fx import convert_to_base, FxRateMissing


def test_convert_same_currency_noop():
    assert convert_to_base(amount=1000, ccy="KRW",
                           base_ccy="KRW", rate=None) == 1000


def test_convert_with_rate():
    # USD 100 × 1300 = 130000
    assert convert_to_base(amount=100, ccy="USD",
                           base_ccy="KRW", rate=1300) == 130_000


def test_convert_missing_rate_raises():
    with pytest.raises(FxRateMissing):
        convert_to_base(amount=100, ccy="EUR",
                        base_ccy="KRW", rate=None)


def test_convert_zero_rate_raises():
    with pytest.raises(FxRateMissing):
        convert_to_base(amount=100, ccy="EUR",
                        base_ccy="KRW", rate=0)


def test_convert_negative_amount():
    # 환불금 -100 USD × 1300
    assert convert_to_base(amount=-100, ccy="USD",
                           base_ccy="KRW", rate=1300) == -130_000


def test_convert_same_currency_rate_ignored():
    # 동일통화면 rate 무의미
    assert convert_to_base(amount=500, ccy="KRW",
                           base_ccy="KRW", rate=9999) == 500
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_fx.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/fx.py`:

```python
"""외화 환산.

설계서 5.5. 기말환율 사용 (잔액 평가용).
"""
from __future__ import annotations
from typing import Optional


class FxRateMissing(Exception):
    """환율 미확보 시 발생."""


def convert_to_base(
    amount: float,
    ccy: str,
    base_ccy: str,
    rate: Optional[float],
) -> float:
    """원통화 금액을 base_ccy로 환산.

    Args:
        amount: 원통화 잔액 (음수 허용 — 환불·선수금 등).
        ccy: 원통화 코드.
        base_ccy: 기준통화 코드.
        rate: ccy 1단위당 base_ccy 환율. ccy == base_ccy면 무시.

    Returns:
        base_ccy 환산 금액.

    Raises:
        FxRateMissing: 다른 통화이면서 rate가 None·0·음수일 때.
    """
    if ccy == base_ccy:
        return amount
    if rate is None or rate <= 0:
        raise FxRateMissing(f"missing or invalid fx rate for {ccy}->{base_ccy}: {rate}")
    return amount * rate
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_fx.py -v`
Expected: 6 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/fx.py CC_SAMPLING_TOOL_V2/tests/unit/test_fx.py
git -C c:/Claude commit -m "feat(domain): fx conversion (period-end rate)"
```

---

### Task 6: Allowance 판정

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/allowance.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_allowance.py`

대손충당금·부실판정. 설계 5.4의 BAD 분류 근거 제공.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_allowance.py`:

```python
import pytest
from src.domain.entities import Account
from src.domain.allowance import (
    is_fully_provisioned, classify_allowance_band,
)


def _acc(balance, allowance):
    return Account(party_id="p", name="p", gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance, allowance_amt=allowance,
                   is_bad_debt=(allowance == balance and balance > 0))


def test_fully_provisioned_true():
    a = _acc(1000, 1000)
    assert is_fully_provisioned(a) is True


def test_fully_provisioned_false_partial():
    a = _acc(1000, 500)
    assert is_fully_provisioned(a) is False


def test_fully_provisioned_zero_balance_false():
    a = _acc(0, 0)
    assert is_fully_provisioned(a) is False


def test_fully_provisioned_not_flagged_bad():
    # allowance == balance인데 is_bad_debt 플래그 없으면 False
    a = Account(party_id="p", name="p", gl_account="x",
                balance_orig=1000, ccy="KRW", fx_rate=1.0,
                balance_krw=1000, allowance_amt=1000, is_bad_debt=False)
    assert is_fully_provisioned(a) is False


def test_band_normal():
    a = _acc(1000, 0)
    assert classify_allowance_band(a) == "NORMAL"


def test_band_partial():
    a = _acc(1000, 300)
    assert classify_allowance_band(a) == "PARTIAL"


def test_band_full():
    a = _acc(1000, 1000)
    assert classify_allowance_band(a) == "FULL"


def test_band_excess():
    a = _acc(1000, 1500)
    assert classify_allowance_band(a) == "EXCESS"  # 이상 — 데이터 검증 필요
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_allowance.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/allowance.py`:

```python
"""대손충당금 판정.

설계서 5.4 — 부실채권 자동 제외 판정 근거.
"""
from __future__ import annotations
from src.domain.entities import Account


def is_fully_provisioned(acc: Account) -> bool:
    """충당금 100% & is_bad_debt 플래그.

    잔액 ≤ 0이면 False. 두 조건 모두 만족해야 표본에서 자동 제외 대상.
    """
    if abs(acc.balance_krw) < 1e-9:
        return False
    if not acc.is_bad_debt:
        return False
    return acc.allowance_ratio >= 1.0 - 1e-9


def classify_allowance_band(acc: Account) -> str:
    """충당금 구간 분류.

    Returns:
        "NORMAL" (충당 0), "PARTIAL" (0~100%), "FULL" (정확히 100%),
        "EXCESS" (>100%, 데이터 이상).
    """
    ratio = acc.allowance_ratio
    if ratio < 1e-9:
        return "NORMAL"
    if ratio < 1.0 - 1e-9:
        return "PARTIAL"
    if ratio < 1.0 + 1e-9:
        return "FULL"
    return "EXCESS"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_allowance.py -v`
Expected: 8 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/allowance.py CC_SAMPLING_TOOL_V2/tests/unit/test_allowance.py
git -C c:/Claude commit -m "feat(domain): allowance band + fully-provisioned check"
```

---

### Task 7: Classification (KEY/RP/BAD)

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/sampling/classification.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_classification.py`

설계 5.4. 우선순위: EXCLUDED_BAD > EXCLUDED_ZERO > FORCED_RP > FORCED_KEY > REP.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_classification.py`:

```python
import pytest
from src.domain.entities import Account, SelectionReason
from src.domain.sampling.classification import classify_population


def _acc(pid, balance, **kw):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance, **kw)


def test_zero_balance_excluded():
    accs = [_acc("p", 0)]
    forced, excluded, remaining = classify_population(accs, key_threshold=1000)
    assert forced == []
    assert excluded[0][1] == SelectionReason.EXCLUDED_ZERO
    assert remaining == []


def test_bad_debt_full_provisioned_excluded():
    accs = [_acc("p", 1000, is_bad_debt=True, allowance_amt=1000)]
    forced, excluded, remaining = classify_population(accs, key_threshold=999_999_999)
    assert excluded[0][1] == SelectionReason.EXCLUDED_BAD


def test_bad_priority_over_rp():
    accs = [_acc("p", 1000, is_bad_debt=True, allowance_amt=1000,
                 is_related_party=True)]
    _, excluded, _ = classify_population(accs, key_threshold=999_999_999)
    assert excluded[0][1] == SelectionReason.EXCLUDED_BAD


def test_zero_priority_over_rp():
    accs = [_acc("p", 0, is_related_party=True)]
    _, excluded, _ = classify_population(accs, key_threshold=999)
    assert excluded[0][1] == SelectionReason.EXCLUDED_ZERO


def test_rp_forced():
    accs = [_acc("p", 100, is_related_party=True)]
    forced, _, _ = classify_population(accs, key_threshold=999_999_999)
    assert forced[0][1] == SelectionReason.FORCED_RP


def test_rp_skips_key_check():
    # RP인 acc은 잔액 >= key여도 FORCED_RP로 분류 (KEY 검사 skip)
    accs = [_acc("p", 9_999_999, is_related_party=True)]
    forced, _, _ = classify_population(accs, key_threshold=100)
    assert forced[0][1] == SelectionReason.FORCED_RP


def test_key_forced():
    accs = [_acc("p", 5_000_000)]
    forced, _, _ = classify_population(accs, key_threshold=1_000_000)
    assert forced[0][1] == SelectionReason.FORCED_KEY


def test_below_key_goes_to_remaining():
    accs = [_acc("p", 100)]
    _, _, remaining = classify_population(accs, key_threshold=1_000_000)
    assert remaining == accs


def test_classify_full_example():
    accs = [
        _acc("rp", 100, is_related_party=True),
        _acc("bad", 500, is_bad_debt=True, allowance_amt=500),
        _acc("zero", 0),
        _acc("key", 10_000_000),
        _acc("rep", 50_000),
    ]
    forced, excluded, remaining = classify_population(accs, key_threshold=1_000_000)
    forced_ids = {a.party_id for a, _ in forced}
    excluded_ids = {a.party_id for a, _ in excluded}
    remaining_ids = {a.party_id for a in remaining}
    assert forced_ids == {"rp", "key"}
    assert excluded_ids == {"bad", "zero"}
    assert remaining_ids == {"rep"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_classification.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/sampling/classification.py`:

```python
"""KEY / RP / BAD / EXCLUDED 분류.

설계서 5.4. 우선순위:
EXCLUDED_BAD > EXCLUDED_ZERO > FORCED_RP > FORCED_KEY > REP.
"""
from __future__ import annotations
from src.domain.entities import Account, SelectionReason
from src.domain.allowance import is_fully_provisioned


def classify_population(
    accounts: list[Account],
    key_threshold: float,
) -> tuple[
    list[tuple[Account, SelectionReason]],   # forced (강제포함)
    list[tuple[Account, SelectionReason]],   # excluded (제외)
    list[Account],                           # remaining (MUS PPS 대상)
]:
    """모집단을 강제포함·제외·잔여로 분류.

    Args:
        accounts: 분류 대상.
        key_threshold: |잔액| ≥ threshold면 KEY로 강제포함.

    Returns:
        (forced, excluded, remaining).
        forced·excluded는 (account, reason) 페어. remaining은 raw Account.
    """
    forced: list[tuple[Account, SelectionReason]] = []
    excluded: list[tuple[Account, SelectionReason]] = []
    remaining: list[Account] = []

    for acc in accounts:
        if is_fully_provisioned(acc):
            excluded.append((acc, SelectionReason.EXCLUDED_BAD))
            continue
        if abs(acc.balance_krw) < 1e-9:
            excluded.append((acc, SelectionReason.EXCLUDED_ZERO))
            continue
        if acc.is_related_party:
            forced.append((acc, SelectionReason.FORCED_RP))
            continue
        if abs(acc.balance_krw) >= key_threshold:
            forced.append((acc, SelectionReason.FORCED_KEY))
            continue
        remaining.append(acc)

    return forced, excluded, remaining
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_classification.py -v`
Expected: 9 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/sampling/classification.py CC_SAMPLING_TOOL_V2/tests/unit/test_classification.py
git -C c:/Claude commit -m "feat(domain): KEY/RP/BAD/ZERO classification with priority"
```

---

### Task 8: Stratification + fallback

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/sampling/stratified.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_stratified.py`

설계 5.3. log-binning 자동 strata + 균일·소규모 fallback.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_stratified.py`:

```python
import pytest
from src.domain.entities import Account, Strata
from src.domain.sampling.stratified import (
    suggest_strata, should_use_single_stratum, stratified_pps,
)


def _acc(pid, balance):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_single_stratum_when_small_population():
    accs = [_acc(f"p{i}", 100 * (i + 1)) for i in range(30)]
    assert should_use_single_stratum(accs) is True


def test_single_stratum_when_uniform():
    # CV < 0.3 → uniform
    accs = [_acc(f"p{i}", 1000 + i) for i in range(100)]
    assert should_use_single_stratum(accs) is True


def test_multi_stratum_when_diverse():
    # 명확한 분포 차이
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"m{i}", 10_000) for i in range(30)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    assert should_use_single_stratum(accs) is False


def test_suggest_strata_four_bins_default():
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"m{i}", 10_000) for i in range(30)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    strata = suggest_strata(accs, n_strata=4)
    assert len(strata) == 4
    # 인접 strata 경계 연속
    for i in range(len(strata) - 1):
        assert strata[i].high <= strata[i + 1].low + 1e-9


def test_suggest_strata_covers_all():
    accs = [_acc(f"p{i}", (i + 1) * 100) for i in range(100)]
    strata = suggest_strata(accs, n_strata=3)
    min_b = min(a.balance_krw for a in accs)
    max_b = max(a.balance_krw for a in accs)
    assert strata[0].low <= min_b
    assert strata[-1].high >= max_b


def test_stratified_pps_distributes_sample():
    accs = ([_acc(f"s{i}", 100) for i in range(50)]
            + [_acc(f"l{i}", 1_000_000) for i in range(10)])
    strata = [Strata(0, 1000, n_required=2),
              Strata(1000, 1_000_001, n_required=3)]
    sample = stratified_pps(accs, strata, seed=0)
    # 각 strata에서 정확히 n_required개 (가용 모집단 한도)
    assert len(sample) == 5
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_stratified.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/sampling/stratified.py`:

```python
"""Stratification — 다단계 + uniform·소규모 fallback.

설계서 5.3.
"""
from __future__ import annotations
import math
import statistics
from typing import Optional
from src.domain.entities import Account, Strata
from src.domain.sampling.mus import pps_select


MIN_POPULATION_FOR_STRATIFY = 50
UNIFORM_CV_THRESHOLD = 0.3


def should_use_single_stratum(accounts: list[Account]) -> bool:
    """단일 strata로 강등할지 판단.

    조건: 모집단 < 50 OR 잔액 변동계수(CV) < 0.3.
    """
    if len(accounts) < MIN_POPULATION_FOR_STRATIFY:
        return True
    balances = [abs(a.balance_krw) for a in accounts if a.balance_krw != 0]
    if not balances:
        return True
    mean = statistics.fmean(balances)
    if mean == 0:
        return True
    stdev = statistics.pstdev(balances)
    cv = stdev / mean
    return cv < UNIFORM_CV_THRESHOLD


def suggest_strata(
    accounts: list[Account],
    n_strata: int = 4,
) -> list[Strata]:
    """log-binning으로 strata 경계 제안.

    각 strata의 n_required는 0 (호출자가 별도 할당).
    """
    if n_strata < 1:
        raise ValueError("n_strata must be >= 1")
    balances = sorted(abs(a.balance_krw) for a in accounts if a.balance_krw != 0)
    if not balances:
        return [Strata(low=0.0, high=0.0, n_required=0)]

    min_b = balances[0]
    max_b = balances[-1]
    if min_b == max_b or n_strata == 1:
        return [Strata(low=0.0, high=max_b, n_required=0)]

    # log-spaced edges
    log_min = math.log10(min_b if min_b > 0 else 1)
    log_max = math.log10(max_b)
    edges = [10 ** (log_min + (log_max - log_min) * i / n_strata)
             for i in range(n_strata + 1)]
    edges[0] = 0.0  # 최저 strata는 0부터 (작은 잔액 흡수)

    return [Strata(low=edges[i], high=edges[i + 1], n_required=0)
            for i in range(n_strata)]


def stratified_pps(
    accounts: list[Account],
    strata: list[Strata],
    seed: Optional[int] = None,
) -> list[Account]:
    """각 strata 내 MUS PPS 독립 수행 후 union."""
    sample: list[Account] = []
    for i, st in enumerate(strata):
        bucket = [a for a in accounts if st.contains(abs(a.balance_krw))]
        sub_seed = None if seed is None else seed + i
        sample.extend(pps_select(bucket, st.n_required, seed=sub_seed))
    return sample
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_stratified.py -v`
Expected: 6 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/sampling/stratified.py CC_SAMPLING_TOOL_V2/tests/unit/test_stratified.py
git -C c:/Claude commit -m "feat(domain): stratification (log-binning + uniform/small fallback)"
```

---

### Task 9: Matching 차이판정

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/matching.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_matching.py`

설계 5.6. abs() 음수안전 + NO_RESPONSE 분기.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_matching.py`:

```python
import pytest
from src.domain.entities import Verdict
from src.domain.matching import judge_response


def test_no_response_when_confirmed_none():
    v = judge_response(expected=1000, confirmed=None, diff_reason=None)
    assert v == Verdict.NO_RESPONSE


def test_match_within_threshold():
    # diff 500 < max(1000, 1_000_000_000 × 0.001 = 1_000_000)
    v = judge_response(expected=1_000_000_000, confirmed=1_000_000_500,
                       diff_reason=None)
    assert v == Verdict.MATCH


def test_match_minimum_threshold_1000():
    # 작은 잔액: max(1000, 100 × 0.001 = 0.1) → 1000
    v = judge_response(expected=100, confirmed=999, diff_reason=None)
    assert v == Verdict.MATCH


def test_reconciled_with_timing():
    v = judge_response(expected=1000, confirmed=0, diff_reason="시점차이")
    assert v == Verdict.RECONCILED


def test_reconciled_with_other_reasons():
    for r in ["미수령", "미발송"]:
        v = judge_response(expected=1000, confirmed=0, diff_reason=r)
        assert v == Verdict.RECONCILED


def test_discrepancy_default():
    v = judge_response(expected=1000, confirmed=500, diff_reason=None)
    assert v == Verdict.DISCREPANCY


def test_negative_expected_uses_abs_threshold():
    # 환불금 -1M, confirmed -999.5K → diff 500 < threshold 1000
    v = judge_response(expected=-1_000_000, confirmed=-999_500,
                       diff_reason=None)
    assert v == Verdict.MATCH


def test_custom_threshold():
    # 0.01% (10bp)로 strict
    v = judge_response(expected=1_000_000, confirmed=1_000_500,
                       diff_reason=None, ratio_threshold=0.0001)
    assert v == Verdict.DISCREPANCY  # 500 > max(1000, 100)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_matching.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/matching.py`:

```python
"""회신 매칭·차이판정.

설계서 5.6.
"""
from __future__ import annotations
from typing import Optional
from src.domain.entities import Verdict


DEFAULT_FLOOR = 1000.0
DEFAULT_RATIO = 0.001
RECONCILABLE_REASONS = {"시점차이", "미수령", "미발송"}


def judge_response(
    expected: float,
    confirmed: Optional[float],
    diff_reason: Optional[str],
    floor: float = DEFAULT_FLOOR,
    ratio_threshold: float = DEFAULT_RATIO,
) -> Verdict:
    """회신 결과를 판정.

    Args:
        expected: 장부상 기대 잔액.
        confirmed: 회신 받은 잔액. None이면 미회신·추출 실패.
        diff_reason: 사용자 입력 차이사유 (시점차이 등).
        floor: 최소 절대 임계값 (기본 ₩1,000).
        ratio_threshold: |expected| 대비 비율 (기본 0.1%).

    Returns:
        MATCH / RECONCILED / DISCREPANCY / NO_RESPONSE.
    """
    if confirmed is None:
        return Verdict.NO_RESPONSE

    diff = confirmed - expected
    threshold = max(floor, abs(expected) * ratio_threshold)

    if abs(diff) <= threshold:
        return Verdict.MATCH
    if diff_reason in RECONCILABLE_REASONS:
        return Verdict.RECONCILED
    return Verdict.DISCREPANCY
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_matching.py -v`
Expected: 8 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/matching.py CC_SAMPLING_TOOL_V2/tests/unit/test_matching.py
git -C c:/Claude commit -m "feat(domain): response matching (MATCH/RECONCILED/DISCREPANCY/NO_RESPONSE)"
```

---

### Task 10: PPS Projection

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/domain/projection/pps.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_projection.py`

설계 5.8. tainting + basic precision + incremental allowance.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_projection.py`:

```python
import pytest
from src.domain.entities import Kind
from src.domain.projection.pps import (
    tainting, project_misstatement,
)


def test_tainting_full():
    # book < interval → tainting = ms/book
    t = tainting(misstatement=500, book=1000, sampling_interval=10_000)
    assert t == 0.5


def test_tainting_key_item_full_misstatement():
    # book >= interval (key item) → 자체 추정, tainting 개념 미적용
    # 반환은 None 또는 1.0 — 구현 결정 (여기서는 None)
    t = tainting(misstatement=500, book=20_000, sampling_interval=10_000)
    assert t is None


def test_tainting_zero_misstatement():
    t = tainting(misstatement=0, book=1000, sampling_interval=10_000)
    assert t == 0.0


def test_project_within_tolerable():
    # 표본 1건 오차 100, book 500, interval 10000
    # tainting=0.2, projected=2000, basic_precision = 3.0 × 10000 = 30000
    # upper = 2000 + 30000 + incremental≈0 = 32000 < tolerable 50000
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=50_000,
        sampled_misstatements=[(100, 500)],  # [(ms_amt, book)]
    )
    assert result.kind == Kind.AR
    assert result.verdict == "WITHIN_TOLERABLE"
    assert result.upper_limit < 50_000


def test_project_exceeds_tolerable():
    # 큰 오차로 upper > tolerable
    result = project_misstatement(
        kind=Kind.AP,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=10_000,
        sampled_misstatements=[(500, 1000), (300, 600)],
    )
    assert result.verdict == "EXCEED"


def test_project_upper_geq_projected():
    # upper limit ≥ projected sum (basic precision 가산 보장)
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(100, 500), (50, 300)],
    )
    assert result.upper_limit >= result.projected_misstatement


def test_project_no_misstatements():
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=50_000,
        sampled_misstatements=[],
    )
    assert result.projected_misstatement == 0.0
    assert result.upper_limit == pytest.approx(30_000, abs=1)  # basic precision only
    assert result.verdict == "WITHIN_TOLERABLE"


def test_key_item_projection_uses_actual_ms():
    # book >= interval인 key item은 실제 misstatement 그대로 projected에 가산
    result = project_misstatement(
        kind=Kind.AR,
        confidence=0.95,
        sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(5_000, 20_000)],  # key item
    )
    assert result.projected_misstatement == pytest.approx(5_000, abs=1)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_projection.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/projection/pps.py`:

```python
"""ISA 530 PPS Projection.

설계서 5.8.
"""
from __future__ import annotations
from typing import Optional
from src.domain.entities import Kind, ProjectionResult
from src.domain.sampling.sample_size import reliability_factor


# AAG-SAM Table A-2: Incremental allowance factor (RF increment between
# ranks for tainting < 1). 단순화: 동일 RF 사용 (각 rank별 reliability_factor 차분
# 테이블은 별도 데이터 필요. 여기선 보수적 근사).
_INCREMENTAL_FACTOR = {
    0.99: 1.40,
    0.95: 1.00,
    0.90: 0.85,
    0.80: 0.70,
}


def tainting(
    misstatement: float,
    book: float,
    sampling_interval: float,
) -> Optional[float]:
    """tainting 비율 계산.

    Returns:
        book < interval이면 ms/book (tainting 비율).
        book >= interval이면 None (key item, 자체 추정 모드).
    """
    if abs(book) >= sampling_interval:
        return None
    if abs(book) < 1e-9:
        return 0.0
    return misstatement / book


def project_misstatement(
    kind: Kind,
    confidence: float,
    sampling_interval: float,
    tolerable: float,
    sampled_misstatements: list[tuple[float, float]],
) -> ProjectionResult:
    """ISA 530 PPS projection.

    Args:
        kind: AR / AP.
        confidence: 신뢰수준.
        sampling_interval: BV / n.
        tolerable: tolerable misstatement.
        sampled_misstatements: [(misstatement_amt, book_amt), ...].

    Returns:
        ProjectionResult.
    """
    rf = reliability_factor(confidence)
    basic_precision = rf * sampling_interval

    projected_ms = 0.0
    taintings_sub_one: list[float] = []
    for ms_amt, book in sampled_misstatements:
        t = tainting(ms_amt, book, sampling_interval)
        if t is None:
            # key item: 실제 오차 사용
            projected_ms += ms_amt
        else:
            projected_ms += t * sampling_interval
            if 0 < t < 1.0:
                taintings_sub_one.append(t)

    # incremental allowance: tainting < 1인 case 가산
    inc_factor = _INCREMENTAL_FACTOR.get(confidence, 1.0)
    taintings_sub_one.sort(reverse=True)
    incremental = sum(
        inc_factor * t * sampling_interval for t in taintings_sub_one
    )

    upper = projected_ms + basic_precision + incremental
    verdict = "WITHIN_TOLERABLE" if upper <= tolerable else "EXCEED"

    return ProjectionResult(
        kind=kind,
        projected_misstatement=projected_ms,
        basic_precision=basic_precision,
        incremental_allowance=incremental,
        upper_limit=upper,
        tolerable=tolerable,
        verdict=verdict,
    )
```

- [ ] **Step 4: projection 패키지 __init__.py 작성**

`src/domain/projection/__init__.py`:

```python
from src.domain.projection.pps import tainting, project_misstatement

__all__ = ["tainting", "project_misstatement"]
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_projection.py -v`
Expected: 8 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/projection/ CC_SAMPLING_TOOL_V2/tests/unit/test_projection.py
git -C c:/Claude commit -m "feat(domain): ISA 530 PPS projection (tainting + basic precision + incremental)"
```

---

### Task 11: SQLAlchemy DB models

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/src/infrastructure/db/models.py`
- Create: `CC_SAMPLING_TOOL_V2/src/infrastructure/db/session.py`
- Test: `CC_SAMPLING_TOOL_V2/tests/unit/test_db_models.py`

도메인 entity와 1:1 매핑. domain 의존방향 위배 X (infrastructure → domain만).

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_db_models.py`:

```python
import pytest
from datetime import date
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import (
    Base, ProjectRow, AccountRow, SampleRow, ConfirmationRow,
)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session(engine)
    s = SessionFactory()
    yield s
    s.close()


def test_create_project(session):
    p = ProjectRow(client="ACME", period_end=date(2025, 12, 31),
                   base_ccy="KRW", materiality=500_000_000,
                   tolerable=250_000_000)
    session.add(p)
    session.commit()
    assert p.id is not None


def test_account_belongs_to_project(session):
    p = ProjectRow(client="ACME", period_end=date(2025, 12, 31),
                   base_ccy="KRW", materiality=1, tolerable=1)
    session.add(p)
    session.commit()
    a = AccountRow(project_id=p.id, kind="AR", party_id="P1",
                   name="갑", gl_account="11200",
                   balance_orig=1000, ccy="USD", fx_rate=1300,
                   balance_krw=1_300_000)
    session.add(a)
    session.commit()
    assert a.id is not None
    assert a.project_id == p.id


def test_kind_constraint_only_ar_ap(session):
    p = ProjectRow(client="X", period_end=date(2025, 12, 31),
                   base_ccy="KRW", materiality=1, tolerable=1)
    session.add(p)
    session.commit()
    # AR·AP 외 값 거부 — CHECK 제약 또는 enum
    from sqlalchemy.exc import IntegrityError
    a = AccountRow(project_id=p.id, kind="BAD", party_id="P1",
                   name="x", gl_account="x", balance_orig=0,
                   ccy="KRW", fx_rate=1, balance_krw=0)
    session.add(a)
    with pytest.raises((IntegrityError, ValueError)):
        session.commit()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_db_models.py -v`
Expected: ImportError.

- [ ] **Step 3: session.py 구현**

`src/infrastructure/db/session.py`:

```python
"""SQLAlchemy engine + sessionmaker."""
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_engine(url: str = "sqlite:///data/cc_v2.db"):
    return create_engine(url, future=True)


def make_session(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
```

- [ ] **Step 4: models.py 구현**

`src/infrastructure/db/models.py`:

```python
"""SQLAlchemy 모델 — domain entity와 1:1 매핑.

NOTE: domain은 이 모듈을 import 금지. 의존방향: api/application → domain ← infrastructure.
"""
from __future__ import annotations
from datetime import date, datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    ForeignKey, CheckConstraint, Text,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class ProjectRow(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    client = Column(String(200), nullable=False)
    period_end = Column(Date, nullable=False)
    base_ccy = Column(String(3), nullable=False, default="KRW")
    materiality = Column(Float, nullable=False)
    tolerable = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    accounts = relationship("AccountRow", back_populates="project",
                            cascade="all, delete-orphan")


class AccountRow(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_account_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    party_id = Column(String(50), nullable=False)
    name = Column(String(200), nullable=False)
    gl_account = Column(String(50), nullable=False)
    balance_orig = Column(Float, nullable=False)
    ccy = Column(String(3), nullable=False)
    fx_rate = Column(Float, nullable=False)
    balance_krw = Column(Float, nullable=False)
    is_related_party = Column(Boolean, default=False, nullable=False)
    is_bad_debt = Column(Boolean, default=False, nullable=False)
    allowance_amt = Column(Float, default=0.0, nullable=False)
    aging_bucket = Column(String(50))
    src_sheet = Column(String(200))
    src_row = Column(Integer)

    project = relationship("ProjectRow", back_populates="accounts")


class SampleRow(Base):
    __tablename__ = "samples"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_sample_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    selection_reason = Column(String(20), nullable=False)


class ConfirmationRow(Base):
    __tablename__ = "confirmations"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_conf_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    expected = Column(Float, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    confirmed = Column(Float)
    diff = Column(Float)
    diff_reason = Column(String(100))
    pdf_path = Column(Text)
    verdict = Column(String(20))
    sent_at = Column(DateTime)
    extracted_at = Column(DateTime)
```

- [ ] **Step 5: __init__.py 노출**

`src/infrastructure/db/__init__.py`:

```python
from src.infrastructure.db.models import (
    Base, ProjectRow, AccountRow, SampleRow, ConfirmationRow,
)
from src.infrastructure.db.session import make_engine, make_session

__all__ = [
    "Base", "ProjectRow", "AccountRow", "SampleRow", "ConfirmationRow",
    "make_engine", "make_session",
]
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_db_models.py -v`
Expected: 3 passed.

SQLite는 CHECK constraint 적용. `pytest -v` 출력에서 `test_kind_constraint_only_ar_ap` PASS 확인.

- [ ] **Step 7: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/db/ CC_SAMPLING_TOOL_V2/tests/unit/test_db_models.py
git -C c:/Claude commit -m "feat(infra): SQLAlchemy models (Project/Account/Sample/Confirmation)"
```

---

### Task 12: Flask app factory + Phase 1 회귀

**Files:**
- Create: `CC_SAMPLING_TOOL_V2/api/app.py`
- Modify: `CC_SAMPLING_TOOL_V2/tests/conftest.py` (생성)

라우트는 Phase 2에서 추가. Phase 1은 app factory + healthz 1개만.

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_app_boot.py`:

```python
import pytest
from api.app import create_app


def test_app_factory_creates_flask_instance():
    app = create_app(testing=True)
    assert app is not None
    assert app.config["TESTING"] is True


def test_healthz_returns_ok():
    app = create_app(testing=True)
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json == {"status": "ok"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_app_boot.py -v`
Expected: ImportError.

- [ ] **Step 3: api/app.py 구현**

`api/app.py`:

```python
"""Flask app factory. Phase 1은 healthz만. Phase 2부터 라우트 추가."""
from __future__ import annotations
from flask import Flask, jsonify


def create_app(testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = testing

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    return app
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_app_boot.py -v`
Expected: 2 passed.

- [ ] **Step 5: Phase 1 회귀 (전체)**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/unit -q`
Expected: 모든 테스트 (≈60+) PASS.

테스트 수 합산:
- test_entities: 6
- test_sample_size: 8
- test_mus: 7
- test_fx: 6
- test_allowance: 8
- test_classification: 9
- test_stratified: 6
- test_matching: 8
- test_projection: 8
- test_db_models: 3
- test_app_boot: 2
- **합계: 71**

- [ ] **Step 6: domain 순수성 검증 (clean arch invariant)**

Run:
```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && \
python -c "
import ast, sys
from pathlib import Path
forbidden = {'flask', 'sqlalchemy', 'pandas', 'openpyxl', 'pdfplumber'}
violations = []
for py in Path('src/domain').rglob('*.py'):
    tree = ast.parse(py.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.split('.')[0] in forbidden:
                    violations.append((str(py), n.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in forbidden:
                violations.append((str(py), node.module))
if violations:
    for v in violations:
        print('VIOLATION:', v)
    sys.exit(1)
print('domain pure: OK')
"
```

Expected: `domain pure: OK`. 위반 시 즉시 해당 import 제거.

- [ ] **Step 7: Phase 1 마무리 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/
git -C c:/Claude commit -m "feat(api): Flask app factory + healthz; Phase 1 complete"
git -C c:/Claude tag cc-v2-phase1
```

---

## Phase 1 완료 기준

- `pytest tests/unit -q` 모든 테스트 PASS (≈71개)
- domain 순수성 검증 통과 (forbidden import 없음)
- `git tag cc-v2-phase1` 작성
- 디렉토리 구조 spec [§4](../specs/2026-05-28-cc-sampling-tool-v2-design.md) 일치
- API·UI 아직 없음 — Phase 2에서 ingest_uc·design_sampling_uc 작성 시작

## Phase 2 예고 (별도 plan 파일에서)

- excel_loader (시트·컬럼 자동감지) + 매핑확인 UI
- ingest_uc·design_sampling_uc (application layer)
- /api/projects, /api/ingest, /api/sampling 라우트
- 단일 대시보드 ①②③ 구현 (자료 드롭존·표본설계·합산표)

별도 plan: `2026-05-28-cc-sampling-tool-v2-phase2.md` (Phase 1 완료 후 작성).
