# CC_SAMPLING_TOOL_V2 Phase 2 — Ingest + Sampling UC + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자료(거래처원장·재무제표·특관자·충당금명세) 드롭 → 자동감지·매핑확인 → AR/AP 분리 표본설계 → 단일 대시보드 ①②③(드롭존·표본설계 패널·합산 표본 테이블) 표시까지 e2e 완주.

**Architecture:** Phase 1 순수 도메인 위에 application UC (orchestration) + infrastructure adapter (Excel loader·WAT FX 클라이언트·DB repository) + Flask 라우트 + Vanilla JS 단일 대시보드. Clean arch 의존방향 유지 (api → application → domain ← infrastructure).

**Tech Stack:** Python 3.11+ / Flask 3.x / SQLAlchemy 2.x / openpyxl / pandas / Vanilla JS (no framework).

**Spec 참조:** [2026-05-28-cc-sampling-tool-v2-design.md](../specs/2026-05-28-cc-sampling-tool-v2-design.md) §3 (UI), §4 (구조), §5.3·5.4·5.5 (sampling 로직), §6.1 (흐름 [1]~[3]).

**Phase 2 마일스톤:** 더미 거래처원장(200건, 외화·RP·BAD 혼합) 드롭 → 합산 표본 ③ 화면에 표시. 회신·projection은 Phase 3.

---

## File Structure

신규/수정 (Phase 2):

```
CC_SAMPLING_TOOL_V2/
├── api/
│   ├── app.py                                # 수정: 라우트 등록 + CORS + static
│   └── routes/                                # 신규 패키지
│       ├── __init__.py
│       ├── project.py                        # CRUD /api/projects
│       ├── ingest.py                         # POST /api/projects/{id}/ingest
│       ├── sampling.py                       # POST /api/projects/{id}/sampling/design
│       └── state.py                          # GET /api/projects/{id}/state (대시보드 단일 source)
│
├── src/
│   ├── domain/
│   │   └── sampling/
│   │       └── allocation.py                 # 신규: strata n_required 비례 할당
│   │
│   ├── application/                           # 신규 패키지
│   │   ├── __init__.py
│   │   ├── ingest_uc.py                      # 파일 → Population[AR/AP] persist
│   │   └── design_sampling_uc.py             # Population → SampleDesign persist
│   │
│   └── infrastructure/
│       ├── db/
│       │   └── repository.py                 # 신규: Project/Account/Sample CRUD wrappers
│       ├── ingest/                            # 신규 패키지
│       │   ├── __init__.py
│       │   ├── excel_loader.py               # 시트·컬럼 자동감지 + 매핑확인
│       │   ├── fs_parser.py                  # 재무제표 매출/매입 합계 추출
│       │   ├── rp_parser.py                  # 특관자 거래처명 set
│       │   └── allowance_parser.py           # 거래처별 충당금·부실 플래그
│       └── fx/                                # 신규 패키지
│           ├── __init__.py
│           └── wat_rate_client.py            # WAT /api/rates HTTP wrapper
│
├── configs/
│   └── schema_mapping/                        # 신규 dir
│       └── default_aliases.yaml              # 시트·컬럼 alias 기본값
│
├── frontend/
│   ├── index.html                            # 수정: 단일 대시보드 ①②③
│   ├── app.js                                # 신규: fetch·render·sticky 좌측패널
│   └── styles.css                            # 신규: WAT 표준 토큰 + 레이아웃
│
└── tests/
    ├── integration/                            # 신규 dir
    │   ├── __init__.py
    │   ├── test_excel_loader.py              # 다양한 시트·컬럼 fixture
    │   ├── test_ingest_uc.py
    │   ├── test_design_sampling_uc.py
    │   └── test_routes.py                    # Flask client e2e
    ├── e2e/                                    # 신규 dir
    │   ├── __init__.py
    │   ├── fixtures/
    │   │   ├── dummy_ledger.xlsx             # 200건 더미 (AR/AP, USD/KRW, RP/BAD 혼합)
    │   │   ├── dummy_fs.xlsx
    │   │   ├── dummy_rp.xlsx
    │   │   └── dummy_allowance.xlsx
    │   └── test_drop_to_sampling.py          # 풀 시나리오
    └── unit/
        └── test_allocation.py                 # 신규
```

**책임 분리**:
- `domain/sampling/allocation.py` — 순수 함수 (strata BV 비례 n 할당)
- `application/*_uc.py` — orchestration. domain 호출 + infrastructure 어댑터 조립
- `infrastructure/db/repository.py` — ORM ↔ domain dataclass 변환
- `infrastructure/ingest/*` — pandas/openpyxl 사용 OK (domain 의존 X)
- `infrastructure/fx/wat_rate_client.py` — requests 또는 urllib (도메인 격리)
- `api/routes/*` — HTTP 변환만. 로직 X
- `frontend/{index.html,app.js,styles.css}` — 단일 대시보드 (Vanilla JS, no framework)

---

## 작업 순서

전반(infrastructure/application/domain helper) → 후반(API → Frontend → E2E).

1. **Task 1**: domain `sampling/allocation.py` (strata n_required 비례 할당)
2. **Task 2**: `infrastructure/db/repository.py` (CRUD wrapper)
3. **Task 3**: `infrastructure/fx/wat_rate_client.py`
4. **Task 4**: `configs/schema_mapping/default_aliases.yaml` + 시트 감지
5. **Task 5**: `infrastructure/ingest/excel_loader.py` (시트·컬럼 자동감지)
6. **Task 6**: `infrastructure/ingest/{fs,rp,allowance}_parser.py`
7. **Task 7**: `application/ingest_uc.py`
8. **Task 8**: `application/design_sampling_uc.py`
9. **Task 9**: `api/routes/project.py` (CRUD)
10. **Task 10**: `api/routes/ingest.py` (multipart upload)
11. **Task 11**: `api/routes/sampling.py` + `state.py`
12. **Task 12**: 더미 fixture 생성 스크립트
13. **Task 13**: `frontend/index.html` + `styles.css` (WAT shell + 레이아웃)
14. **Task 14**: `frontend/app.js` (좌측 패널·진행도·핵심지표·fetch)
15. **Task 15**: Frontend ① 드롭존 + 매핑확인 인라인
16. **Task 16**: Frontend ② 표본설계 패널 (AR/AP twin column + 슬라이더)
17. **Task 17**: Frontend ③ 합산 표본 테이블 (필터·정렬·선정사유)
18. **Task 18**: E2E `test_drop_to_sampling.py` + Phase 2 회귀 + tag

---

### Task 1: Domain helper — strata n_required 할당

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/domain/sampling/allocation.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/unit/test_allocation.py`

설계 §3 UX에 "strata 자동제안 → 수동조정" 명시. 자동제안의 기본 정책 = strata별 BV 비례 (총 표본수에서 강제포함 차감 후 잔여를 strata BV 비율로 할당).

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_allocation.py`:

```python
import pytest
from src.domain.entities import Account, Strata
from src.domain.sampling.allocation import allocate_strata


def _acc(pid, balance):
    return Account(party_id=pid, name=pid, gl_account="x",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_allocate_proportional_to_strata_bv():
    # strata1 BV = 100, strata2 BV = 900, total_n = 10
    # → strata1 n=1, strata2 n=9
    accs = [_acc(f"s{i}", 10) for i in range(10)] + \
           [_acc(f"l{i}", 100) for i in range(9)]
    strata = [Strata(0, 50, n_required=0), Strata(50, 1000, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=10)
    assert result[0].n_required == 1
    assert result[1].n_required == 9


def test_allocate_total_n_zero():
    strata = [Strata(0, 100, n_required=0), Strata(100, 200, n_required=0)]
    accs = [_acc("a", 50)]
    result = allocate_strata(strata, accounts=accs, total_n=0)
    assert all(s.n_required == 0 for s in result)


def test_allocate_min_one_per_strata_with_bv():
    # 각 strata에 잔액 있으면 최소 1개씩 (n 충분할 때)
    accs = [_acc("s1", 10), _acc("l1", 10_000)]
    strata = [Strata(0, 100, n_required=0), Strata(100, 100_000, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=5)
    assert result[0].n_required >= 1
    assert result[1].n_required >= 1
    assert result[0].n_required + result[1].n_required == 5


def test_allocate_empty_strata_gets_zero():
    accs = [_acc("a", 100)]
    strata = [Strata(0, 200, n_required=0), Strata(200, 300, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=5)
    assert result[0].n_required == 5
    assert result[1].n_required == 0


def test_allocate_preserves_strata_bounds():
    accs = [_acc(f"a{i}", 100) for i in range(10)]
    strata = [Strata(0, 500, n_required=0)]
    result = allocate_strata(strata, accounts=accs, total_n=3)
    assert result[0].low == 0 and result[0].high == 500
```

- [ ] **Step 2: 실패 확인**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/unit/test_allocation.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`src/domain/sampling/allocation.py`:

```python
"""Strata n_required 할당 — BV 비례 + 최소 1개 (잔액 존재 시).

설계서 §3 UX (strata 자동제안), §5.3 보강.
"""
from __future__ import annotations
from src.domain.entities import Account, Strata


def allocate_strata(
    strata: list[Strata],
    accounts: list[Account],
    total_n: int,
) -> list[Strata]:
    """각 strata에 표본수 비례 할당.

    정책:
    - 각 strata의 BV(잔액 합) 비례로 floor 분배
    - 잔여 표본은 BV 큰 strata부터 1개씩 추가
    - 잔액 있는 strata는 최소 1개 보장 (단 total_n이 충분할 때)
    - 잔액 0인 strata는 0
    """
    if total_n <= 0:
        return [Strata(s.low, s.high, n_required=0) for s in strata]

    bvs = []
    for s in strata:
        bv = sum(abs(a.balance_krw) for a in accounts
                 if s.contains(abs(a.balance_krw)))
        bvs.append(bv)

    total_bv = sum(bvs)
    if total_bv <= 0:
        return [Strata(s.low, s.high, n_required=0) for s in strata]

    # 1차: floor proportional
    raw = [bv / total_bv * total_n for bv in bvs]
    n_allocs = [int(r) for r in raw]

    # 잔액 있는 strata에 최소 1 보장 (가능한 한)
    needs_min = [i for i, bv in enumerate(bvs) if bv > 0 and n_allocs[i] == 0]
    while needs_min and sum(n_allocs) < total_n:
        idx = needs_min.pop(0)
        n_allocs[idx] = 1

    # 잔여 분배 (남은 fraction 큰 순서로)
    remainders = sorted(
        [(raw[i] - n_allocs[i], i) for i in range(len(strata))],
        reverse=True,
    )
    leftover = total_n - sum(n_allocs)
    for _, i in remainders:
        if leftover <= 0:
            break
        if bvs[i] > 0:
            n_allocs[i] += 1
            leftover -= 1

    return [
        Strata(strata[i].low, strata[i].high, n_required=n_allocs[i])
        for i in range(len(strata))
    ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_allocation.py -v` → 5 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/sampling/allocation.py CC_SAMPLING_TOOL_V2/tests/unit/test_allocation.py
git -C c:/Claude commit -m "feat(domain): strata n_required allocation (BV proportional + min-1)"
```

---

### Task 2: Repository (DB CRUD wrapper)

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_repository.py`

domain dataclass ↔ ORM Row 변환 + Project/Account/Sample CRUD. application UC가 사용.

- [ ] **Step 1: 실패 테스트**

`tests/integration/__init__.py` (빈 파일 생성).

`tests/integration/test_repository.py`:

```python
import pytest
from datetime import date
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session(engine)
    s = Session()
    yield s
    s.close()


def test_project_create_get(session):
    repo = ProjectRepo(session)
    pid = repo.create(client="ACME", period_end=date(2025, 12, 31),
                      base_ccy="KRW", materiality=500_000_000,
                      tolerable=250_000_000)
    assert pid > 0
    p = repo.get(pid)
    assert p.client == "ACME"
    assert p.tolerable == 250_000_000


def test_account_bulk_insert(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    accs = [
        Account(party_id=f"P{i}", name=f"갑{i}", gl_account="11200",
                balance_orig=1000 * (i + 1), ccy="KRW", fx_rate=1.0,
                balance_krw=1000 * (i + 1))
        for i in range(5)
    ]
    acc_repo.bulk_insert(project_id=pid, kind=Kind.AR, accounts=accs)
    fetched = acc_repo.list_by_project_kind(pid, Kind.AR)
    assert len(fetched) == 5
    assert fetched[0].party_id == "P0"


def test_account_split_by_kind(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    ar = [Account(party_id="AR1", name="ar", gl_account="x",
                  balance_orig=100, ccy="KRW", fx_rate=1.0, balance_krw=100)]
    ap = [Account(party_id="AP1", name="ap", gl_account="x",
                  balance_orig=200, ccy="KRW", fx_rate=1.0, balance_krw=200)]
    acc_repo.bulk_insert(pid, Kind.AR, ar)
    acc_repo.bulk_insert(pid, Kind.AP, ap)
    assert len(acc_repo.list_by_project_kind(pid, Kind.AR)) == 1
    assert len(acc_repo.list_by_project_kind(pid, Kind.AP)) == 1


def test_sample_persist(session):
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    acc_repo.bulk_insert(pid, Kind.AR, [acc])
    accs = acc_repo.list_by_project_kind(pid, Kind.AR)

    sample_repo = SampleRepo(session)
    sample_repo.persist(
        project_id=pid, kind=Kind.AR,
        selections=[(accs[0], SelectionReason.FORCED_RP)],
    )
    rows = sample_repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0][1] == SelectionReason.FORCED_RP


def test_sample_replace_on_redesign(session):
    """재설계 시 기존 sample 삭제 후 신규 insert."""
    proj_repo = ProjectRepo(session)
    pid = proj_repo.create(client="X", period_end=date(2025, 12, 31),
                           base_ccy="KRW", materiality=1, tolerable=1)
    acc_repo = AccountRepo(session)
    acc = Account(party_id="P1", name="x", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    acc_repo.bulk_insert(pid, Kind.AR, [acc])
    accs = acc_repo.list_by_project_kind(pid, Kind.AR)

    sample_repo = SampleRepo(session)
    sample_repo.persist(pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    sample_repo.persist(pid, Kind.AR, [(accs[0], SelectionReason.FORCED_KEY)])
    rows = sample_repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0][1] == SelectionReason.FORCED_KEY
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/integration/test_repository.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/infrastructure/db/repository.py`:

```python
"""Repository — ORM Row ↔ domain dataclass 변환.

application UC만 호출. domain은 이 모듈 import 금지.
"""
from __future__ import annotations
from datetime import date
from src.domain.entities import (
    Account, Project, Kind, SelectionReason,
)
from src.infrastructure.db.models import (
    ProjectRow, AccountRow, SampleRow,
)


class ProjectRepo:
    def __init__(self, session):
        self.s = session

    def create(self, *, client: str, period_end: date, base_ccy: str,
               materiality: float, tolerable: float) -> int:
        row = ProjectRow(client=client, period_end=period_end,
                         base_ccy=base_ccy, materiality=materiality,
                         tolerable=tolerable)
        self.s.add(row)
        self.s.commit()
        return row.id

    def get(self, project_id: int) -> Project:
        row = self.s.get(ProjectRow, project_id)
        if row is None:
            raise KeyError(f"project {project_id} not found")
        return Project(
            id=row.id, client=row.client, period_end=row.period_end,
            base_ccy=row.base_ccy, materiality=row.materiality,
            tolerable=row.tolerable, created_at=row.created_at,
        )

    def list_all(self) -> list[Project]:
        rows = self.s.query(ProjectRow).order_by(ProjectRow.created_at.desc()).all()
        return [
            Project(id=r.id, client=r.client, period_end=r.period_end,
                    base_ccy=r.base_ccy, materiality=r.materiality,
                    tolerable=r.tolerable, created_at=r.created_at)
            for r in rows
        ]


class AccountRepo:
    def __init__(self, session):
        self.s = session

    def bulk_insert(self, project_id: int, kind: Kind,
                    accounts: list[Account]) -> None:
        rows = [
            AccountRow(
                project_id=project_id, kind=kind.value,
                party_id=a.party_id, name=a.name, gl_account=a.gl_account,
                balance_orig=a.balance_orig, ccy=a.ccy, fx_rate=a.fx_rate,
                balance_krw=a.balance_krw,
                is_related_party=a.is_related_party,
                is_bad_debt=a.is_bad_debt, allowance_amt=a.allowance_amt,
                aging_bucket=a.aging_bucket,
                src_sheet=a.src_sheet, src_row=a.src_row,
            )
            for a in accounts
        ]
        self.s.add_all(rows)
        self.s.commit()

    def list_by_project_kind(self, project_id: int,
                             kind: Kind) -> list[Account]:
        rows = (self.s.query(AccountRow)
                .filter(AccountRow.project_id == project_id,
                        AccountRow.kind == kind.value)
                .order_by(AccountRow.id)
                .all())
        return [self._to_domain(r) for r in rows]

    def replace_all(self, project_id: int, kind: Kind,
                    accounts: list[Account]) -> None:
        """재ingest 시: 기존 동일 (project, kind) 모두 삭제 후 insert."""
        (self.s.query(AccountRow)
         .filter(AccountRow.project_id == project_id,
                 AccountRow.kind == kind.value)
         .delete(synchronize_session=False))
        self.s.commit()
        self.bulk_insert(project_id, kind, accounts)

    @staticmethod
    def _to_domain(r: AccountRow) -> Account:
        return Account(
            party_id=r.party_id, name=r.name, gl_account=r.gl_account,
            balance_orig=r.balance_orig, ccy=r.ccy, fx_rate=r.fx_rate,
            balance_krw=r.balance_krw,
            is_related_party=r.is_related_party,
            is_bad_debt=r.is_bad_debt, allowance_amt=r.allowance_amt,
            aging_bucket=r.aging_bucket,
            src_sheet=r.src_sheet, src_row=r.src_row,
        )


class SampleRepo:
    def __init__(self, session):
        self.s = session

    def persist(self, project_id: int, kind: Kind,
                selections: list[tuple[Account, SelectionReason]]) -> None:
        """기존 (project, kind) sample 삭제 후 신규 insert."""
        (self.s.query(SampleRow)
         .filter(SampleRow.project_id == project_id,
                 SampleRow.kind == kind.value)
         .delete(synchronize_session=False))
        self.s.commit()

        # account_id 매핑
        account_rows = (self.s.query(AccountRow)
                        .filter(AccountRow.project_id == project_id,
                                AccountRow.kind == kind.value)
                        .all())
        by_party = {r.party_id: r.id for r in account_rows}

        rows = []
        for acc, reason in selections:
            aid = by_party.get(acc.party_id)
            if aid is None:
                raise ValueError(
                    f"account party_id {acc.party_id!r} not found in DB"
                )
            rows.append(SampleRow(
                project_id=project_id, account_id=aid,
                kind=kind.value, selection_reason=reason.value,
            ))
        self.s.add_all(rows)
        self.s.commit()

    def list_by_project_kind(self, project_id: int, kind: Kind
                             ) -> list[tuple[Account, SelectionReason]]:
        rows = (self.s.query(SampleRow, AccountRow)
                .join(AccountRow, SampleRow.account_id == AccountRow.id)
                .filter(SampleRow.project_id == project_id,
                        SampleRow.kind == kind.value)
                .all())
        return [
            (AccountRepo._to_domain(a_row),
             SelectionReason(s_row.selection_reason))
            for s_row, a_row in rows
        ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/integration/test_repository.py -v` → 5 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py CC_SAMPLING_TOOL_V2/tests/integration/
git -C c:/Claude commit -m "feat(infra): repository (Project/Account/Sample CRUD + dataclass conversion)"
```

---

### Task 3: WAT FX rate client

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/fx/__init__.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/fx/wat_rate_client.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_wat_rate_client.py`

WAT 통합 Flask 서버의 `/api/rates` proxy 호출. domain.fx와 분리 (도메인은 rate 받아서 환산만).

- [ ] **Step 1: 실패 테스트** (HTTP mock 사용)

`tests/integration/test_wat_rate_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
from src.infrastructure.fx.wat_rate_client import WatRateClient, RateLookupError


def _mock_response(status, body):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    return m


def test_lookup_rate_success():
    body = {"date": "2025-12-31", "rates": {"USD": 1300, "EUR": 1450}}
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               return_value=_mock_response(200, body)):
        c = WatRateClient(base_url="http://localhost:9090")
        rate = c.lookup("USD", date(2025, 12, 31))
        assert rate == 1300


def test_lookup_krw_returns_one():
    c = WatRateClient(base_url="http://localhost:9090")
    assert c.lookup("KRW", date(2025, 12, 31)) == 1.0


def test_lookup_unknown_ccy_raises():
    body = {"date": "2025-12-31", "rates": {"USD": 1300}}
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               return_value=_mock_response(200, body)):
        c = WatRateClient(base_url="http://localhost:9090")
        with pytest.raises(RateLookupError):
            c.lookup("EUR", date(2025, 12, 31))


def test_lookup_http_error_raises():
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               return_value=_mock_response(500, {})):
        c = WatRateClient(base_url="http://localhost:9090")
        with pytest.raises(RateLookupError):
            c.lookup("USD", date(2025, 12, 31))


def test_lookup_caches_per_date():
    body = {"date": "2025-12-31", "rates": {"USD": 1300}}
    mock_get = MagicMock(return_value=_mock_response(200, body))
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               mock_get):
        c = WatRateClient(base_url="http://localhost:9090")
        c.lookup("USD", date(2025, 12, 31))
        c.lookup("USD", date(2025, 12, 31))  # 캐시 적중
        assert mock_get.call_count == 1
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_wat_rate_client.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/infrastructure/fx/__init__.py`:

```python
from src.infrastructure.fx.wat_rate_client import WatRateClient, RateLookupError

__all__ = ["WatRateClient", "RateLookupError"]
```

`src/infrastructure/fx/wat_rate_client.py`:

```python
"""WAT /api/rates HTTP wrapper.

설계서 §5.5. 기말환율 조회·캐싱.
"""
from __future__ import annotations
from datetime import date
from typing import Optional
import requests


class RateLookupError(Exception):
    pass


class WatRateClient:
    def __init__(self, base_url: str = "http://localhost:9090",
                 timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._cache: dict[str, dict[str, float]] = {}  # date_iso → {ccy: rate}

    def lookup(self, ccy: str, period_end: date) -> float:
        if ccy.upper() == "KRW":
            return 1.0
        key = period_end.isoformat()
        rates = self._cache.get(key)
        if rates is None:
            rates = self._fetch(period_end)
            self._cache[key] = rates
        if ccy.upper() not in rates:
            raise RateLookupError(
                f"ccy {ccy} not available at {key}; available: {sorted(rates)}"
            )
        return rates[ccy.upper()]

    def _fetch(self, period_end: date) -> dict[str, float]:
        url = f"{self.base_url}/api/rates"
        try:
            resp = requests.get(url, params={"date": period_end.isoformat()},
                                timeout=self.timeout)
        except requests.RequestException as e:
            raise RateLookupError(f"WAT /api/rates request failed: {e}") from e
        if resp.status_code != 200:
            raise RateLookupError(
                f"WAT /api/rates {resp.status_code}: {resp.text[:200]}"
            )
        body = resp.json()
        rates = body.get("rates", {})
        return {k.upper(): float(v) for k, v in rates.items()}
```

- [ ] **Step 4: requirements.txt에 `requests` 추가**

Edit `c:/Claude/CC_SAMPLING_TOOL_V2/requirements.txt` — 추가 라인:

```
requests>=2.31
```

설치: `python -m pip install requests`.

- [ ] **Step 5: 통과 확인**

`pytest tests/integration/test_wat_rate_client.py -v` → 5 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/fx/ CC_SAMPLING_TOOL_V2/tests/integration/test_wat_rate_client.py CC_SAMPLING_TOOL_V2/requirements.txt
git -C c:/Claude commit -m "feat(infra): WAT /api/rates client (cache by date)"
```

---

### Task 4: Schema mapping config

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/configs/schema_mapping/default_aliases.yaml`

시트명·컬럼명 alias 사전. excel_loader가 로드.

- [ ] **Step 1: 디렉토리·파일 생성**

```bash
mkdir -p c:/Claude/CC_SAMPLING_TOOL_V2/configs/schema_mapping
```

- [ ] **Step 2: `default_aliases.yaml` 작성**

```yaml
# CC_SAMPLING_TOOL_V2 시트·컬럼 alias 기본값
# 사용자가 configs/schema_mapping/<project>.yaml로 override 가능

sheets:
  AR:
    - 채권원장
    - 매출처원장
    - 매출원장
    - AR
    - 매출채권
    - 외상매출금
    - Trade Receivables
  AP:
    - 채무원장
    - 매입처원장
    - 매입원장
    - AP
    - 매입채무
    - 외상매입금
    - Trade Payables
  FS:
    - 재무제표
    - 재무상태표
    - BS
    - Balance Sheet
    - FS_M
  RP:
    - 특관자
    - 특수관계자
    - 특관자리스트
    - 관계회사
    - Related Parties
  ALLOWANCE:
    - 대손충당금
    - 충당금명세
    - 대손충당금명세서
    - Allowance

columns:
  party_id:
    - 거래처코드
    - 거래처번호
    - 거래처ID
    - party_id
    - code
  name:
    - 거래처명
    - 거래처
    - 상호
    - name
    - 회사명
  gl_account:
    - 계정과목
    - 계정코드
    - 계정
    - account
    - GL
  balance:
    - 기말잔액
    - 잔액
    - balance
    - 당기말잔액
    - 기말금액
  ccy:
    - 통화
    - 통화코드
    - ccy
    - currency
  fx_rate:
    - 환율
    - rate
    - exchange_rate
  aging:
    - 연령
    - aging
    - 연령구분
  allowance:
    - 충당금
    - 대손충당금
    - allowance
    - allowance_amt
```

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/configs/
git -C c:/Claude commit -m "feat(configs): default schema mapping aliases (sheet/column)"
```

---

### Task 5: Excel loader — 시트·컬럼 자동감지

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/__init__.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/excel_loader.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_excel_loader.py`

설계 §1.4 성공기준 3 — 자동감지 정확도 ≥ 95%, 실패 시 UI 매핑확인 (confidence < 0.95).

- [ ] **Step 1: 실패 테스트 + fixture excel 생성**

`tests/integration/test_excel_loader.py`:

```python
import pytest
from pathlib import Path
import openpyxl
from src.infrastructure.ingest.excel_loader import (
    detect_sheet_kind, detect_columns, load_account_sheet, MappingConfidence,
)


def _make_xlsx(tmp_path, sheets: dict[str, list[list]]) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    p = tmp_path / "test.xlsx"
    wb.save(p)
    return p


def test_detect_sheet_kind_exact_match():
    assert detect_sheet_kind("매출채권") == "AR"
    assert detect_sheet_kind("매입채무") == "AP"
    assert detect_sheet_kind("재무제표") == "FS"


def test_detect_sheet_kind_partial_match():
    # "매출채권원장" 같이 alias가 일부 포함된 시트명도 인식
    assert detect_sheet_kind("매출채권 원장") == "AR"
    assert detect_sheet_kind("Trade Receivables 2024") == "AR"


def test_detect_sheet_kind_unknown():
    assert detect_sheet_kind("기타시트") is None


def test_detect_columns_korean(tmp_path):
    p = _make_xlsx(tmp_path, {
        "매출채권": [
            ["거래처코드", "거래처명", "계정과목", "기말잔액", "통화"],
            ["P1", "갑", "11200", 1_000_000, "KRW"],
        ],
    })
    wb = openpyxl.load_workbook(p)
    ws = wb["매출채권"]
    headers = [c.value for c in ws[1]]
    mapping, confidence = detect_columns(headers)
    assert mapping["party_id"] == 0
    assert mapping["name"] == 1
    assert mapping["gl_account"] == 2
    assert mapping["balance"] == 3
    assert mapping["ccy"] == 4
    assert confidence >= 0.95


def test_detect_columns_arbitrary_order(tmp_path):
    p = _make_xlsx(tmp_path, {
        "매출채권": [
            ["기말잔액", "거래처명", "통화", "계정", "거래처코드"],
        ],
    })
    wb = openpyxl.load_workbook(p)
    headers = [c.value for c in wb["매출채권"][1]]
    mapping, _ = detect_columns(headers)
    assert mapping["balance"] == 0
    assert mapping["party_id"] == 4


def test_detect_columns_low_confidence(tmp_path):
    p = _make_xlsx(tmp_path, {
        "매출채권": [
            ["col1", "col2", "col3"],
        ],
    })
    wb = openpyxl.load_workbook(p)
    headers = [c.value for c in wb["매출채권"][1]]
    _, confidence = detect_columns(headers)
    assert confidence < 0.95


def test_load_account_sheet_full(tmp_path):
    p = _make_xlsx(tmp_path, {
        "매출채권": [
            ["거래처코드", "거래처명", "계정과목", "기말잔액", "통화", "환율"],
            ["P1", "갑", "11200", 1_000_000, "KRW", 1.0],
            ["P2", "을", "11200", 5_000, "USD", 1300.0],
        ],
    })
    accs, meta = load_account_sheet(p, sheet_name="매출채권")
    assert len(accs) == 2
    assert accs[0].party_id == "P1"
    assert accs[1].ccy == "USD"
    assert accs[1].balance_orig == 5_000
    assert meta["sheet_kind"] == "AR"
    assert meta["confidence"] >= 0.95


def test_load_account_sheet_skips_blank_rows(tmp_path):
    p = _make_xlsx(tmp_path, {
        "매출채권": [
            ["거래처코드", "거래처명", "계정", "기말잔액"],
            ["P1", "갑", "11200", 1000],
            [None, None, None, None],
            ["P2", "을", "11200", 2000],
        ],
    })
    accs, _ = load_account_sheet(p, sheet_name="매출채권")
    assert len(accs) == 2
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_excel_loader.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/infrastructure/ingest/__init__.py` (빈 파일).

`src/infrastructure/ingest/excel_loader.py`:

```python
"""Excel 원장·시트 자동감지·로드.

설계서 §6.1 [2]. confidence < 0.95이면 UI 매핑확인 차단 (호출자 책임).
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Literal
import yaml
import openpyxl
from src.domain.entities import Account


MappingConfidence = float
_CFG_PATH = Path(__file__).resolve().parent.parent.parent.parent / \
    "configs" / "schema_mapping" / "default_aliases.yaml"


def _load_aliases() -> dict:
    with open(_CFG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


_ALIASES = _load_aliases()


def detect_sheet_kind(sheet_name: str) -> Optional[Literal["AR","AP","FS","RP","ALLOWANCE"]]:
    """시트명에서 종류 추정. alias 정확 or 포함 매칭."""
    name = sheet_name.strip().lower()
    for kind, aliases in _ALIASES["sheets"].items():
        for a in aliases:
            if a.lower() == name or a.lower() in name:
                return kind
    return None


def detect_columns(headers: list[Optional[str]]) -> tuple[dict[str, int], MappingConfidence]:
    """헤더 행에서 컬럼명 → index 매핑.

    Returns:
        (mapping, confidence). confidence = 발견된 필수컬럼 / 총 필수 (5개).
    """
    required = ["party_id", "name", "gl_account", "balance", "ccy"]
    mapping: dict[str, int] = {}
    norm_headers = [(h or "").strip().lower() for h in headers]

    for field, aliases in _ALIASES["columns"].items():
        for idx, h in enumerate(norm_headers):
            if any(a.lower() == h or a.lower() in h for a in aliases):
                if field not in mapping:
                    mapping[field] = idx
                break

    found_required = sum(1 for f in required if f in mapping)
    confidence = found_required / len(required)
    return mapping, confidence


def load_account_sheet(
    path: Path,
    sheet_name: str,
) -> tuple[list[Account], dict]:
    """엑셀 시트에서 Account 목록 + meta 반환.

    Returns:
        (accounts, meta). meta = {sheet_kind, confidence, mapping}.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"sheet {sheet_name!r} not found in {path}")
    ws = wb[sheet_name]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return [], {"sheet_kind": None, "confidence": 0.0, "mapping": {}}

    headers = list(rows[0])
    mapping, confidence = detect_columns(headers)
    sheet_kind = detect_sheet_kind(sheet_name)

    accounts: list[Account] = []
    for r_idx, row in enumerate(rows[1:], start=2):
        # 모든 셀이 비어있으면 skip
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
            continue
        if "party_id" not in mapping or "balance" not in mapping:
            break  # 헤더가 잘못된 경우 본문 로드 무의미

        def cell(field, default=None):
            i = mapping.get(field)
            if i is None or i >= len(row):
                return default
            v = row[i]
            return default if v is None else v

        party_id = str(cell("party_id", "")).strip()
        if not party_id:
            continue

        name = str(cell("name", "")).strip()
        gl_account = str(cell("gl_account", "")).strip()
        balance_orig = float(cell("balance", 0) or 0)
        ccy = str(cell("ccy", "KRW")).strip() or "KRW"
        fx_rate = float(cell("fx_rate", 1.0) or 1.0)
        balance_krw = balance_orig * fx_rate  # fx 모듈은 ingest_uc에서 정확히 환산

        accounts.append(Account(
            party_id=party_id, name=name, gl_account=gl_account,
            balance_orig=balance_orig, ccy=ccy, fx_rate=fx_rate,
            balance_krw=balance_krw,
            aging_bucket=str(cell("aging", "")).strip() or None,
            allowance_amt=float(cell("allowance", 0) or 0),
            src_sheet=sheet_name, src_row=r_idx,
        ))

    return accounts, {
        "sheet_kind": sheet_kind,
        "confidence": confidence,
        "mapping": mapping,
    }
```

- [ ] **Step 4: 통과 확인**

`pytest tests/integration/test_excel_loader.py -v` → 7 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/ CC_SAMPLING_TOOL_V2/tests/integration/test_excel_loader.py
git -C c:/Claude commit -m "feat(infra): excel loader (sheet/column auto-detect, confidence ≥0.95)"
```

---

### Task 6: FS/RP/Allowance parsers

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/fs_parser.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/rp_parser.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/allowance_parser.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_parsers.py`

각 파일은 단일 책임:
- FS: 매출/매입 합계 추출 (모집단 합계 cross-check용)
- RP: 거래처명 set 반환 → ingest_uc가 Account.is_related_party 플래그
- Allowance: 거래처별 충당금·부실 플래그

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_parsers.py`:

```python
import pytest
import openpyxl
from src.infrastructure.ingest.fs_parser import parse_fs_totals
from src.infrastructure.ingest.rp_parser import parse_related_parties
from src.infrastructure.ingest.allowance_parser import parse_allowance


def _xlsx(tmp_path, sheet, rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(sheet)
    for r in rows:
        ws.append(r)
    p = tmp_path / "f.xlsx"
    wb.save(p)
    return p


def test_parse_fs_totals(tmp_path):
    p = _xlsx(tmp_path, "재무제표", [
        ["계정", "기말금액"],
        ["매출채권", 50_000_000],
        ["매입채무", 30_000_000],
        ["기타", 1],
    ])
    totals = parse_fs_totals(p, sheet_name="재무제표")
    assert totals["AR"] == 50_000_000
    assert totals["AP"] == 30_000_000


def test_parse_related_parties(tmp_path):
    p = _xlsx(tmp_path, "특관자", [
        ["거래처명"],
        ["A자회사"],
        ["B관계회사"],
    ])
    rps = parse_related_parties(p, sheet_name="특관자")
    assert "A자회사" in rps
    assert "B관계회사" in rps


def test_parse_allowance(tmp_path):
    p = _xlsx(tmp_path, "충당금명세", [
        ["거래처코드", "거래처명", "잔액", "충당금", "부실여부"],
        ["P1", "갑", 1000, 500, "N"],
        ["P2", "을", 2000, 2000, "Y"],
    ])
    allow = parse_allowance(p, sheet_name="충당금명세")
    assert allow["P1"]["allowance_amt"] == 500
    assert allow["P1"]["is_bad_debt"] is False
    assert allow["P2"]["allowance_amt"] == 2000
    assert allow["P2"]["is_bad_debt"] is True
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_parsers.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/infrastructure/ingest/fs_parser.py`:

```python
"""재무제표 — AR/AP 합계 추출 (모집단 cross-check용)."""
from __future__ import annotations
from pathlib import Path
import openpyxl


_AR_LABELS = {"매출채권", "외상매출금", "trade receivables"}
_AP_LABELS = {"매입채무", "외상매입금", "trade payables"}


def parse_fs_totals(path: Path, sheet_name: str) -> dict[str, float]:
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        return {}
    ws = wb[sheet_name]
    out: dict[str, float] = {}
    for row in ws.iter_rows(values_only=True):
        if len(row) < 2:
            continue
        label = str(row[0] or "").strip().lower()
        try:
            amount = float(row[1] or 0)
        except (TypeError, ValueError):
            continue
        if any(lab in label for lab in _AR_LABELS):
            out["AR"] = out.get("AR", 0) + amount
        if any(lab in label for lab in _AP_LABELS):
            out["AP"] = out.get("AP", 0) + amount
    return out
```

`src/infrastructure/ingest/rp_parser.py`:

```python
"""특수관계자 거래처명 set 반환."""
from __future__ import annotations
from pathlib import Path
import openpyxl


def parse_related_parties(path: Path, sheet_name: str) -> set[str]:
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        return set()
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return set()
    # 첫 열에 거래처명이 있다고 가정 (header 1행 skip)
    return {str(r[0]).strip() for r in rows[1:] if r and r[0]}
```

`src/infrastructure/ingest/allowance_parser.py`:

```python
"""거래처별 대손충당금 + 부실 플래그."""
from __future__ import annotations
from pathlib import Path
import openpyxl


def parse_allowance(path: Path, sheet_name: str
                    ) -> dict[str, dict[str, float | bool]]:
    """party_id → {allowance_amt, is_bad_debt}."""
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        return {}
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return {}

    headers = [str(h or "").strip().lower() for h in rows[0]]
    def idx(*candidates):
        for i, h in enumerate(headers):
            if any(c in h for c in candidates):
                return i
        return -1

    i_party = idx("거래처코드", "거래처번호", "code", "party")
    i_allow = idx("충당금", "allowance")
    i_bad = idx("부실", "bad")

    out: dict[str, dict] = {}
    for row in rows[1:]:
        if i_party < 0 or i_party >= len(row) or row[i_party] is None:
            continue
        pid = str(row[i_party]).strip()
        allowance_amt = 0.0
        if 0 <= i_allow < len(row) and row[i_allow] is not None:
            try:
                allowance_amt = float(row[i_allow])
            except (TypeError, ValueError):
                allowance_amt = 0.0
        is_bad = False
        if 0 <= i_bad < len(row) and row[i_bad] is not None:
            val = str(row[i_bad]).strip().upper()
            is_bad = val in {"Y", "YES", "TRUE", "1", "부실"}
        out[pid] = {"allowance_amt": allowance_amt, "is_bad_debt": is_bad}
    return out
```

- [ ] **Step 4: 통과 확인**

`pytest tests/integration/test_parsers.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/fs_parser.py CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/rp_parser.py CC_SAMPLING_TOOL_V2/src/infrastructure/ingest/allowance_parser.py CC_SAMPLING_TOOL_V2/tests/integration/test_parsers.py
git -C c:/Claude commit -m "feat(infra): FS/RP/Allowance parsers"
```

---

### Task 7: Application — ingest_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/__init__.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/ingest_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_ingest_uc.py`

설계 §6.1 [2]. excel_loader + fx 환산 + RP·BAD 플래그 + AccountRepo.replace_all.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_ingest_uc.py`:

```python
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
import openpyxl

from src.application.ingest_uc import IngestUC, IngestResult
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo, AccountRepo
from src.domain.entities import Kind


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session(engine)
    s = Session()
    yield s
    s.close()


@pytest.fixture
def project_id(session):
    return ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000,
    )


def _make_ledger(tmp_path) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ar = wb.create_sheet("매출채권")
    ar.append(["거래처코드", "거래처명", "계정과목", "기말잔액", "통화"])
    ar.append(["P1", "갑", "11200", 1_000_000, "KRW"])
    ar.append(["P2", "을", "11200", 100, "USD"])  # 외화
    ap = wb.create_sheet("매입채무")
    ap.append(["거래처코드", "거래처명", "계정과목", "기말잔액", "통화"])
    ap.append(["P3", "병", "21100", 500_000, "KRW"])
    p = tmp_path / "ledger.xlsx"
    wb.save(p)
    return p


def test_ingest_creates_ar_ap(session, project_id, tmp_path):
    ledger = _make_ledger(tmp_path)
    fx_client = MagicMock()
    fx_client.lookup.return_value = 1300.0  # USD → KRW
    uc = IngestUC(session, fx_client=fx_client)

    result = uc.ingest(project_id=project_id, ledger_path=ledger,
                       fs_path=None, rp_path=None, allowance_path=None)

    assert result.ar_count == 2
    assert result.ap_count == 1

    acc_repo = AccountRepo(session)
    ar = acc_repo.list_by_project_kind(project_id, Kind.AR)
    ap = acc_repo.list_by_project_kind(project_id, Kind.AP)
    assert len(ar) == 2
    assert len(ap) == 1
    # USD acc 환산
    usd = next(a for a in ar if a.ccy == "USD")
    assert usd.balance_krw == 100 * 1300.0


def test_ingest_with_rp_flags(session, project_id, tmp_path):
    ledger = _make_ledger(tmp_path)
    # RP 파일
    wb_rp = openpyxl.Workbook()
    ws = wb_rp.active
    ws.title = "특관자"
    ws.append(["거래처명"])
    ws.append(["갑"])
    rp_path = tmp_path / "rp.xlsx"
    wb_rp.save(rp_path)

    fx = MagicMock(lookup=MagicMock(return_value=1300.0))
    uc = IngestUC(session, fx_client=fx)
    uc.ingest(project_id=project_id, ledger_path=ledger,
              fs_path=None, rp_path=rp_path, allowance_path=None)

    ar = AccountRepo(session).list_by_project_kind(project_id, Kind.AR)
    gap = next(a for a in ar if a.name == "갑")
    assert gap.is_related_party is True


def test_ingest_with_allowance(session, project_id, tmp_path):
    ledger = _make_ledger(tmp_path)
    wb_allow = openpyxl.Workbook()
    ws = wb_allow.active
    ws.title = "충당금명세"
    ws.append(["거래처코드", "잔액", "충당금", "부실여부"])
    ws.append(["P1", 1_000_000, 500_000, "N"])
    ws.append(["P2", 130_000, 130_000, "Y"])
    allow_path = tmp_path / "allow.xlsx"
    wb_allow.save(allow_path)

    fx = MagicMock(lookup=MagicMock(return_value=1300.0))
    uc = IngestUC(session, fx_client=fx)
    uc.ingest(project_id=project_id, ledger_path=ledger,
              fs_path=None, rp_path=None, allowance_path=allow_path)

    ar = AccountRepo(session).list_by_project_kind(project_id, Kind.AR)
    p1 = next(a for a in ar if a.party_id == "P1")
    p2 = next(a for a in ar if a.party_id == "P2")
    assert p1.allowance_amt == 500_000
    assert p1.is_bad_debt is False
    assert p2.is_bad_debt is True


def test_ingest_replaces_existing(session, project_id, tmp_path):
    ledger = _make_ledger(tmp_path)
    fx = MagicMock(lookup=MagicMock(return_value=1300.0))
    uc = IngestUC(session, fx_client=fx)
    uc.ingest(project_id, ledger, None, None, None)
    uc.ingest(project_id, ledger, None, None, None)  # 재ingest
    ar = AccountRepo(session).list_by_project_kind(project_id, Kind.AR)
    assert len(ar) == 2  # 중복 X
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_ingest_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/__init__.py` (빈 파일).

`src/application/ingest_uc.py`:

```python
"""IngestUC — 파일 → Population[AR/AP] persist orchestration.

설계서 §6.1 [2].
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import openpyxl

from src.domain.entities import Account, Kind
from src.domain.fx import convert_to_base, FxRateMissing
from src.infrastructure.db.repository import ProjectRepo, AccountRepo
from src.infrastructure.ingest.excel_loader import (
    detect_sheet_kind, load_account_sheet,
)
from src.infrastructure.ingest.rp_parser import parse_related_parties
from src.infrastructure.ingest.allowance_parser import parse_allowance
from src.infrastructure.ingest.fs_parser import parse_fs_totals


@dataclass
class IngestResult:
    project_id: int
    ar_count: int
    ap_count: int
    ar_total_krw: float
    ap_total_krw: float
    confidence_ar: float
    confidence_ap: float
    fs_totals: dict
    needs_mapping_confirmation: bool


class IngestUC:
    def __init__(self, session, fx_client):
        self.s = session
        self.fx = fx_client
        self.proj = ProjectRepo(session)
        self.acc = AccountRepo(session)

    def ingest(
        self,
        project_id: int,
        ledger_path: Path,
        fs_path: Optional[Path],
        rp_path: Optional[Path],
        allowance_path: Optional[Path],
    ) -> IngestResult:
        project = self.proj.get(project_id)

        # 1) 시트 자동감지
        wb = openpyxl.load_workbook(ledger_path, read_only=True)
        sheet_assignment: dict[str, str] = {}  # sheet_name → "AR"/"AP"
        for sn in wb.sheetnames:
            kind = detect_sheet_kind(sn)
            if kind in ("AR", "AP"):
                sheet_assignment.setdefault(kind, sn)

        # 2) RP/충당금 사전로드
        rp_names: set[str] = set()
        if rp_path is not None:
            rp_sheet = self._auto_sheet(rp_path, "RP")
            if rp_sheet:
                rp_names = parse_related_parties(rp_path, rp_sheet)

        allow_map: dict[str, dict] = {}
        if allowance_path is not None:
            allow_sheet = self._auto_sheet(allowance_path, "ALLOWANCE")
            if allow_sheet:
                allow_map = parse_allowance(allowance_path, allow_sheet)

        # 3) FS totals (cross-check 정보)
        fs_totals: dict[str, float] = {}
        if fs_path is not None:
            fs_sheet = self._auto_sheet(fs_path, "FS")
            if fs_sheet:
                fs_totals = parse_fs_totals(fs_path, fs_sheet)

        # 4) AR/AP 로드 + 플래그 + 환산 + persist
        counts = {"AR": 0, "AP": 0}
        totals = {"AR": 0.0, "AP": 0.0}
        confidences = {"AR": 0.0, "AP": 0.0}
        for kind_str in ("AR", "AP"):
            sn = sheet_assignment.get(kind_str)
            if sn is None:
                continue
            accs, meta = load_account_sheet(ledger_path, sn)
            confidences[kind_str] = meta["confidence"]

            enriched: list[Account] = []
            for a in accs:
                rate = a.fx_rate
                if a.ccy.upper() != project.base_ccy.upper():
                    try:
                        rate = self.fx.lookup(a.ccy, project.period_end)
                    except Exception:
                        rate = a.fx_rate  # 폴백: 시트값 유지
                try:
                    balance_krw = convert_to_base(
                        a.balance_orig, a.ccy, project.base_ccy, rate
                    )
                except FxRateMissing:
                    balance_krw = a.balance_orig  # 폴백

                allow = allow_map.get(a.party_id, {})
                enriched.append(Account(
                    party_id=a.party_id, name=a.name,
                    gl_account=a.gl_account,
                    balance_orig=a.balance_orig,
                    ccy=a.ccy.upper(), fx_rate=rate,
                    balance_krw=balance_krw,
                    is_related_party=(a.name in rp_names),
                    is_bad_debt=bool(allow.get("is_bad_debt", False)),
                    allowance_amt=float(allow.get("allowance_amt",
                                                  a.allowance_amt)),
                    aging_bucket=a.aging_bucket,
                    src_sheet=a.src_sheet, src_row=a.src_row,
                ))

            self.acc.replace_all(project_id, Kind(kind_str), enriched)
            counts[kind_str] = len(enriched)
            totals[kind_str] = sum(abs(a.balance_krw) for a in enriched)

        needs_confirm = (
            (confidences["AR"] > 0 and confidences["AR"] < 0.95)
            or (confidences["AP"] > 0 and confidences["AP"] < 0.95)
        )

        return IngestResult(
            project_id=project_id,
            ar_count=counts["AR"], ap_count=counts["AP"],
            ar_total_krw=totals["AR"], ap_total_krw=totals["AP"],
            confidence_ar=confidences["AR"],
            confidence_ap=confidences["AP"],
            fs_totals=fs_totals,
            needs_mapping_confirmation=needs_confirm,
        )

    @staticmethod
    def _auto_sheet(path: Path, target_kind: str) -> Optional[str]:
        wb = openpyxl.load_workbook(path, read_only=True)
        for sn in wb.sheetnames:
            if detect_sheet_kind(sn) == target_kind:
                return sn
        # fallback: 첫 시트
        return wb.sheetnames[0] if wb.sheetnames else None
```

- [ ] **Step 4: 통과 확인**

`pytest tests/integration/test_ingest_uc.py -v` → 4 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/ CC_SAMPLING_TOOL_V2/tests/integration/test_ingest_uc.py
git -C c:/Claude commit -m "feat(application): ingest_uc (ledger → AR/AP populations + flags + fx)"
```

---

### Task 8: Application — design_sampling_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/design_sampling_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_design_sampling_uc.py`

설계 §6.1 [3]. sample_size + classify + suggest_strata + allocate + stratified_pps + SampleRepo.persist. AR/AP 병렬. **seed persistence**: 결과에 used_seed 포함.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_design_sampling_uc.py`:

```python
import pytest
from datetime import date
from src.application.design_sampling_uc import (
    DesignSamplingUC, DesignParams, DesignResult,
)
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo, AccountRepo, SampleRepo


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_accounts(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000,
    )
    accs = []
    for i in range(200):
        bal = (i + 1) * 10_000
        accs.append(Account(
            party_id=f"P{i:03d}", name=f"갑{i}", gl_account="11200",
            balance_orig=bal, ccy="KRW", fx_rate=1.0, balance_krw=bal,
        ))
    # RP, BAD 추가
    accs.append(Account(
        party_id="RP1", name="자회사", gl_account="11200",
        balance_orig=100, ccy="KRW", fx_rate=1.0, balance_krw=100,
        is_related_party=True,
    ))
    accs.append(Account(
        party_id="BAD1", name="부실거래처", gl_account="11200",
        balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000,
        is_bad_debt=True, allowance_amt=1000,
    ))
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    return pid


def test_design_runs_ar(session, project_with_accounts):
    pid = project_with_accounts
    uc = DesignSamplingUC(session)
    params = DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=1_000_000, n_strata=4, seed=42,
    )
    result = uc.design(project_id=pid, kind=Kind.AR, params=params)

    assert result.kind == Kind.AR
    assert result.used_seed == 42
    assert result.n_total > 0
    assert result.n_forced >= 1  # RP 강제
    # BAD는 제외
    sample = SampleRepo(session).list_by_project_kind(pid, Kind.AR)
    sample_ids = {a.party_id for a, _ in sample}
    assert "BAD1" not in sample_ids
    assert "RP1" in sample_ids


def test_design_persists_replaceable(session, project_with_accounts):
    pid = project_with_accounts
    uc = DesignSamplingUC(session)
    params = DesignParams(confidence=0.95, expected_ms_pct=0.0,
                          key_threshold=999_999_999, n_strata=4, seed=1)
    r1 = uc.design(pid, Kind.AR, params)
    r2 = uc.design(pid, Kind.AR, params)
    # 두 번 호출 — 동일 seed면 동일 결과
    assert r1.n_total == r2.n_total


def test_design_includes_strata_metadata(session, project_with_accounts):
    pid = project_with_accounts
    uc = DesignSamplingUC(session)
    params = DesignParams(confidence=0.95, expected_ms_pct=0.0,
                          key_threshold=999_999_999, n_strata=4, seed=1)
    result = uc.design(pid, Kind.AR, params)
    assert len(result.strata) >= 1
    for s in result.strata:
        assert hasattr(s, "low") and hasattr(s, "high") and hasattr(s, "n_required")
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_design_sampling_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/design_sampling_uc.py`:

```python
"""DesignSamplingUC — Population → SampleDesign orchestration.

설계서 §6.1 [3]. AR/AP 각 호출 분리 (병렬 실행은 호출자 책임).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from src.domain.entities import Account, Kind, SelectionReason, Strata
from src.domain.sampling.sample_size import sample_size_mus
from src.domain.sampling.classification import classify_population
from src.domain.sampling.stratified import (
    should_use_single_stratum, suggest_strata, stratified_pps,
)
from src.domain.sampling.allocation import allocate_strata
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)


@dataclass
class DesignParams:
    confidence: float
    expected_ms_pct: float          # tolerable 대비 비율 (0.0~)
    key_threshold: float
    n_strata: int = 4
    seed: Optional[int] = None


@dataclass
class DesignResult:
    kind: Kind
    n_total: int
    n_forced: int
    n_excluded: int
    n_representative: int
    used_seed: Optional[int]
    strata: list[Strata]
    population_bv: float


class DesignSamplingUC:
    def __init__(self, session):
        self.s = session
        self.proj = ProjectRepo(session)
        self.acc = AccountRepo(session)
        self.sample = SampleRepo(session)

    def design(
        self,
        project_id: int,
        kind: Kind,
        params: DesignParams,
    ) -> DesignResult:
        project = self.proj.get(project_id)
        accounts = self.acc.list_by_project_kind(project_id, kind)

        if not accounts:
            return DesignResult(
                kind=kind, n_total=0, n_forced=0, n_excluded=0,
                n_representative=0, used_seed=params.seed,
                strata=[], population_bv=0.0,
            )

        # 1) 분류 (KEY/RP/BAD/ZERO)
        forced, excluded, remaining = classify_population(
            accounts, key_threshold=params.key_threshold,
        )

        # 2) 표본규모 (전체 모집단 BV 기준)
        population_bv = sum(abs(a.balance_krw) for a in accounts)
        expected_ms = project.tolerable * params.expected_ms_pct
        n_total = sample_size_mus(
            book_value=population_bv,
            confidence=params.confidence,
            tolerable=project.tolerable,
            expected_ms=expected_ms,
        )

        # 3) Representative 잔여 표본수 = n_total - 강제포함
        n_rep_target = max(0, n_total - len(forced))

        # 4) Stratify (remaining만)
        if remaining and not should_use_single_stratum(remaining):
            strata = suggest_strata(remaining, n_strata=params.n_strata)
        else:
            max_b = max((abs(a.balance_krw) for a in remaining), default=0.0)
            strata = [Strata(low=0.0, high=max_b, n_required=0)]
        strata = allocate_strata(strata, remaining, total_n=n_rep_target)

        rep_sample = stratified_pps(remaining, strata, seed=params.seed)
        rep_with_reason: list[tuple[Account, SelectionReason]] = [
            (a, SelectionReason.REP) for a in rep_sample
        ]

        # 5) 합치고 persist
        all_selections = list(forced) + rep_with_reason
        self.sample.persist(project_id, kind, all_selections)

        return DesignResult(
            kind=kind,
            n_total=len(all_selections),
            n_forced=len(forced),
            n_excluded=len(excluded),
            n_representative=len(rep_with_reason),
            used_seed=params.seed,
            strata=strata,
            population_bv=population_bv,
        )
```

- [ ] **Step 4: 통과 확인**

`pytest tests/integration/test_design_sampling_uc.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/design_sampling_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_design_sampling_uc.py
git -C c:/Claude commit -m "feat(application): design_sampling_uc (size + classify + strata + PPS)"
```

---

### Task 9: API routes — project CRUD

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/__init__.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/project.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/app.py` (라우트 등록 + DB 의존주입)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_routes.py`

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_routes.py`:

```python
import pytest
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


@pytest.fixture
def app():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session(engine)
    app = create_app(testing=True, session_factory=SessionFactory)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_project(client):
    resp = client.post("/api/projects", json={
        "client": "ACME", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 500_000_000,
        "tolerable": 250_000_000,
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"] > 0
    assert body["client"] == "ACME"


def test_list_projects(client):
    client.post("/api/projects", json={
        "client": "A", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    client.post("/api/projects", json={
        "client": "B", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 2


def test_get_project(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    pid = r.get_json()["id"]
    resp = client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    assert resp.get_json()["client"] == "X"


def test_get_project_not_found(client):
    resp = client.get("/api/projects/99999")
    assert resp.status_code == 404
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_routes.py -v` → ImportError.

- [ ] **Step 3: api/app.py 수정**

```python
"""Flask app factory with route registration."""
from __future__ import annotations
from typing import Optional
from flask import Flask, jsonify, g
from src.infrastructure.db.session import make_engine, make_session


def create_app(testing: bool = False, session_factory=None) -> Flask:
    app = Flask(__name__, static_folder="../frontend",
                static_url_path="")
    app.config["TESTING"] = testing

    # session_factory 미주입 시 기본값
    if session_factory is None:
        engine = make_engine()
        from src.infrastructure.db.models import Base
        Base.metadata.create_all(engine)
        session_factory = make_session(engine)
    app.config["SESSION_FACTORY"] = session_factory

    @app.before_request
    def open_session():
        g.session = session_factory()

    @app.teardown_request
    def close_session(exc):
        s = g.pop("session", None)
        if s is not None:
            s.close()

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    # 라우트 등록
    from api.routes.project import bp as project_bp
    app.register_blueprint(project_bp)

    return app
```

- [ ] **Step 4: api/routes/__init__.py (빈 파일) + api/routes/project.py**

```python
"""Project CRUD routes."""
from __future__ import annotations
from datetime import date
from flask import Blueprint, request, jsonify, g
from src.infrastructure.db.repository import ProjectRepo


bp = Blueprint("projects", __name__, url_prefix="/api/projects")


def _proj_to_json(p):
    return {
        "id": p.id,
        "client": p.client,
        "period_end": p.period_end.isoformat(),
        "base_ccy": p.base_ccy,
        "materiality": p.materiality,
        "tolerable": p.tolerable,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@bp.post("")
def create_project():
    data = request.get_json(force=True)
    repo = ProjectRepo(g.session)
    pid = repo.create(
        client=data["client"],
        period_end=date.fromisoformat(data["period_end"]),
        base_ccy=data.get("base_ccy", "KRW"),
        materiality=float(data["materiality"]),
        tolerable=float(data["tolerable"]),
    )
    return jsonify(_proj_to_json(repo.get(pid))), 201


@bp.get("")
def list_projects():
    repo = ProjectRepo(g.session)
    return jsonify([_proj_to_json(p) for p in repo.list_all()])


@bp.get("/<int:pid>")
def get_project(pid: int):
    repo = ProjectRepo(g.session)
    try:
        return jsonify(_proj_to_json(repo.get(pid)))
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404
```

- [ ] **Step 5: 통과 확인**

`pytest tests/integration/test_routes.py -v` → 4 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_routes.py
git -C c:/Claude commit -m "feat(api): project CRUD routes + session lifecycle"
```

---

### Task 10: API route — ingest

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/ingest.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/app.py` (이미 위에서 generic 등록 패턴, 추가)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_ingest_route.py`

multipart/form-data로 ledger·fs·rp·allowance 파일 업로드.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_ingest_route.py`:

```python
import pytest
import io
import openpyxl
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


def _build_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("매출채권")
    ws.append(["거래처코드", "거래처명", "계정과목", "기말잔액", "통화"])
    ws.append(["P1", "갑", "11200", 1000, "KRW"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SF = make_session(engine)
    app = create_app(testing=True, session_factory=SF)
    return app.test_client()


def test_ingest_endpoint_success(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1_000_000, "tolerable": 500_000,
    })
    pid = r.get_json()["id"]

    data = {
        "ledger": (io.BytesIO(_build_xlsx_bytes()), "ledger.xlsx"),
    }
    resp = client.post(f"/api/projects/{pid}/ingest",
                       data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ar_count"] == 1
    assert body["ap_count"] == 0


def test_ingest_missing_ledger(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 1, "tolerable": 1,
    })
    pid = r.get_json()["id"]
    resp = client.post(f"/api/projects/{pid}/ingest",
                       data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_ingest_route.py -v` → ImportError or 404.

- [ ] **Step 3: api/routes/ingest.py**

```python
"""Ingest route — multipart 파일 업로드."""
from __future__ import annotations
import tempfile
from pathlib import Path
from flask import Blueprint, request, jsonify, g, current_app
from src.application.ingest_uc import IngestUC
from src.infrastructure.fx.wat_rate_client import WatRateClient


bp = Blueprint("ingest", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/ingest")
def ingest_files(pid: int):
    if "ledger" not in request.files:
        return jsonify({"error": "ledger file required"}), 400

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ledger_path = tdp / "ledger.xlsx"
        request.files["ledger"].save(ledger_path)

        fs_path = None
        if "fs" in request.files and request.files["fs"].filename:
            fs_path = tdp / "fs.xlsx"
            request.files["fs"].save(fs_path)

        rp_path = None
        if "rp" in request.files and request.files["rp"].filename:
            rp_path = tdp / "rp.xlsx"
            request.files["rp"].save(rp_path)

        allow_path = None
        if "allowance" in request.files and request.files["allowance"].filename:
            allow_path = tdp / "allow.xlsx"
            request.files["allowance"].save(allow_path)

        fx_client = current_app.config.get("FX_CLIENT") or WatRateClient()
        uc = IngestUC(g.session, fx_client=fx_client)
        try:
            result = uc.ingest(pid, ledger_path, fs_path, rp_path, allow_path)
        except KeyError:
            return jsonify({"error": f"project {pid} not found"}), 404

    return jsonify({
        "project_id": result.project_id,
        "ar_count": result.ar_count,
        "ap_count": result.ap_count,
        "ar_total_krw": result.ar_total_krw,
        "ap_total_krw": result.ap_total_krw,
        "confidence_ar": result.confidence_ar,
        "confidence_ap": result.confidence_ap,
        "fs_totals": result.fs_totals,
        "needs_mapping_confirmation": result.needs_mapping_confirmation,
    })
```

- [ ] **Step 4: app.py 라우트 등록 추가**

`api/app.py` 의 `register_blueprint(project_bp)` 아래에 추가:

```python
    from api.routes.ingest import bp as ingest_bp
    app.register_blueprint(ingest_bp)
```

- [ ] **Step 5: 통과 확인**

`pytest tests/integration/test_ingest_route.py -v` → 2 passed.

테스트에서 WAT 호출은 실제 발생하지 않음 (KRW만 사용). 외화 케이스는 별도 fx_client mock 주입으로 검증 가능.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_ingest_route.py
git -C c:/Claude commit -m "feat(api): ingest route (multipart upload + temp file handling)"
```

---

### Task 11: API routes — sampling + state

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/sampling.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/state.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/app.py` (register)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_sampling_route.py`

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_sampling_route.py`:

```python
import pytest
import io
import openpyxl
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


def _ledger_bytes():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("매출채권")
    ws.append(["거래처코드", "거래처명", "계정", "기말잔액", "통화"])
    for i in range(50):
        ws.append([f"P{i:03d}", f"갑{i}", "11200", (i + 1) * 100_000, "KRW"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client_with_project():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    c = app.test_client()
    r = c.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 10_000_000, "tolerable": 5_000_000,
    })
    pid = r.get_json()["id"]
    c.post(f"/api/projects/{pid}/ingest",
           data={"ledger": (io.BytesIO(_ledger_bytes()), "x.xlsx")},
           content_type="multipart/form-data")
    return c, pid


def test_design_sampling(client_with_project):
    c, pid = client_with_project
    resp = c.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AR",
        "confidence": 0.95,
        "expected_ms_pct": 0.0,
        "key_threshold": 999_999_999,
        "n_strata": 4,
        "seed": 42,
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["kind"] == "AR"
    assert body["n_total"] > 0
    assert body["used_seed"] == 42


def test_state_returns_dashboard_view(client_with_project):
    c, pid = client_with_project
    # 표본설계 전 state
    resp = c.get(f"/api/projects/{pid}/state")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project"]["id"] == pid
    assert body["populations"]["AR"]["count"] == 50
    assert body["populations"]["AP"]["count"] == 0
    assert body["samples"]["AR"]["count"] == 0
    # 표본설계 후
    c.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AR", "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 999_999_999, "n_strata": 4, "seed": 1,
    })
    resp = c.get(f"/api/projects/{pid}/state")
    body = resp.get_json()
    assert body["samples"]["AR"]["count"] > 0
    assert isinstance(body["samples"]["AR"]["items"], list)
    item = body["samples"]["AR"]["items"][0]
    assert "party_id" in item and "selection_reason" in item
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_sampling_route.py -v` → ImportError or 404.

- [ ] **Step 3: api/routes/sampling.py**

```python
"""Sampling design route."""
from __future__ import annotations
from flask import Blueprint, request, jsonify, g
from src.domain.entities import Kind
from src.application.design_sampling_uc import (
    DesignSamplingUC, DesignParams,
)


bp = Blueprint("sampling", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/sampling/design")
def design_sampling(pid: int):
    data = request.get_json(force=True)
    try:
        kind = Kind(data["kind"])
    except (KeyError, ValueError):
        return jsonify({"error": "kind must be 'AR' or 'AP'"}), 400
    params = DesignParams(
        confidence=float(data.get("confidence", 0.95)),
        expected_ms_pct=float(data.get("expected_ms_pct", 0.0)),
        key_threshold=float(data.get("key_threshold", 0)),
        n_strata=int(data.get("n_strata", 4)),
        seed=data.get("seed"),
    )
    uc = DesignSamplingUC(g.session)
    try:
        result = uc.design(pid, kind, params)
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404
    return jsonify({
        "kind": result.kind.value,
        "n_total": result.n_total,
        "n_forced": result.n_forced,
        "n_excluded": result.n_excluded,
        "n_representative": result.n_representative,
        "used_seed": result.used_seed,
        "population_bv": result.population_bv,
        "strata": [
            {"low": s.low, "high": s.high, "n_required": s.n_required}
            for s in result.strata
        ],
    })
```

- [ ] **Step 4: api/routes/state.py**

```python
"""Dashboard state — 좌측패널·테이블에 필요한 모든 정보 한방."""
from __future__ import annotations
from flask import Blueprint, jsonify, g
from src.domain.entities import Kind
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)


bp = Blueprint("state", __name__, url_prefix="/api/projects")


@bp.get("/<int:pid>/state")
def project_state(pid: int):
    proj_repo = ProjectRepo(g.session)
    acc_repo = AccountRepo(g.session)
    sample_repo = SampleRepo(g.session)
    try:
        p = proj_repo.get(pid)
    except KeyError:
        return jsonify({"error": "not found"}), 404

    out = {
        "project": {
            "id": p.id, "client": p.client,
            "period_end": p.period_end.isoformat(),
            "base_ccy": p.base_ccy,
            "materiality": p.materiality, "tolerable": p.tolerable,
        },
        "populations": {},
        "samples": {},
    }
    for k in (Kind.AR, Kind.AP):
        accs = acc_repo.list_by_project_kind(pid, k)
        out["populations"][k.value] = {
            "count": len(accs),
            "total_krw": sum(abs(a.balance_krw) for a in accs),
        }
        sample = sample_repo.list_by_project_kind(pid, k)
        out["samples"][k.value] = {
            "count": len(sample),
            "total_krw": sum(abs(a.balance_krw) for a, _ in sample),
            "items": [
                {
                    "party_id": a.party_id,
                    "name": a.name,
                    "gl_account": a.gl_account,
                    "balance_krw": a.balance_krw,
                    "ccy": a.ccy,
                    "selection_reason": r.value,
                    "is_related_party": a.is_related_party,
                    "is_bad_debt": a.is_bad_debt,
                }
                for a, r in sample
            ],
        }
    return jsonify(out)
```

- [ ] **Step 5: app.py에 등록**

`api/app.py` 의 blueprint 등록 부분에 추가:

```python
    from api.routes.sampling import bp as sampling_bp
    app.register_blueprint(sampling_bp)
    from api.routes.state import bp as state_bp
    app.register_blueprint(state_bp)
```

- [ ] **Step 6: 통과 확인**

`pytest tests/integration/test_sampling_route.py -v` → 2 passed.

- [ ] **Step 7: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_sampling_route.py
git -C c:/Claude commit -m "feat(api): sampling design route + dashboard state aggregator"
```

---

### Task 12: E2E fixtures — 더미 데이터 생성

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/__init__.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/__init__.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/build_dummy.py`

스크립트로 더미 데이터 4종 생성. 200건 거래처(AR 120 + AP 80), 외화 10건, RP 5건, 부실 3건.

- [ ] **Step 1: 스크립트 작성**

`tests/e2e/fixtures/build_dummy.py`:

```python
"""더미 데이터 4종 생성 스크립트.

실행: python tests/e2e/fixtures/build_dummy.py
출력: tests/e2e/fixtures/{ledger, fs, rp, allowance}.xlsx
"""
from __future__ import annotations
from pathlib import Path
import random
import openpyxl


OUT = Path(__file__).parent


def build_ledger():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ar = wb.create_sheet("매출채권")
    ar.append(["거래처코드", "거래처명", "계정과목", "기말잔액", "통화", "환율"])
    rng = random.Random(7)
    for i in range(120):
        bal = rng.choice([10_000, 50_000, 100_000, 500_000, 2_000_000, 10_000_000])
        bal *= rng.uniform(0.5, 2.0)
        ccy = "USD" if i < 5 else "KRW"
        fx = 1300.0 if ccy == "USD" else 1.0
        ar.append([f"AR{i:03d}", f"고객사{i:03d}", "11200",
                   round(bal, 0), ccy, fx])

    ap = wb.create_sheet("매입채무")
    ap.append(["거래처코드", "거래처명", "계정과목", "기말잔액", "통화", "환율"])
    for i in range(80):
        bal = rng.choice([5_000, 30_000, 200_000, 1_000_000]) * rng.uniform(0.5, 2.0)
        ccy = "USD" if i < 3 else "KRW"
        fx = 1300.0 if ccy == "USD" else 1.0
        ap.append([f"AP{i:03d}", f"공급사{i:03d}", "21100",
                   round(bal, 0), ccy, fx])

    wb.save(OUT / "dummy_ledger.xlsx")


def build_fs():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("재무제표")
    ws.append(["계정", "기말금액"])
    ws.append(["매출채권", 250_000_000])
    ws.append(["매입채무", 120_000_000])
    wb.save(OUT / "dummy_fs.xlsx")


def build_rp():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("특관자")
    ws.append(["거래처명"])
    for i in range(5):
        ws.append([f"고객사{i:03d}"])  # AR P000~P004 → RP
    wb.save(OUT / "dummy_rp.xlsx")


def build_allowance():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("충당금명세")
    ws.append(["거래처코드", "거래처명", "잔액", "충당금", "부실여부"])
    # 3건 부실 + 5건 부분충당
    ws.append(["AR050", "고객사050", 500_000, 500_000, "Y"])
    ws.append(["AR051", "고객사051", 800_000, 800_000, "Y"])
    ws.append(["AR052", "고객사052", 200_000, 200_000, "Y"])
    ws.append(["AR053", "고객사053", 600_000, 300_000, "N"])
    ws.append(["AR054", "고객사054", 400_000, 100_000, "N"])
    wb.save(OUT / "dummy_allowance.xlsx")


if __name__ == "__main__":
    build_ledger()
    build_fs()
    build_rp()
    build_allowance()
    print("dummy fixtures built at:", OUT)
```

- [ ] **Step 2: 빈 __init__.py 생성**

```bash
touch c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/__init__.py
touch c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/__init__.py
```

- [ ] **Step 3: 실행하여 fixture 생성**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python tests/e2e/fixtures/build_dummy.py
```

Expected: `dummy fixtures built at: ...`

- [ ] **Step 4: 4개 xlsx 파일 확인 + 커밋**

```bash
ls c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/e2e/
git -C c:/Claude commit -m "test(e2e): dummy fixtures (200 accounts, FX/RP/BAD mix)"
```

---

### Task 13: Frontend — HTML shell + CSS (WAT 표준)

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css`

WAT 표준 (메모리 [[wat_tool_standard]]: 헤더 padding-left 7.25rem, 푸터 통일, h1·디자인 토큰). 단일 대시보드 레이아웃 (좌측 sticky panel + 메인 스크롤 섹션).

- [ ] **Step 1: index.html 작성**

`c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html`:

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>채권채무조회서 샘플링·회수 툴 V2</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>

<header class="wat-header">
  <h1>채권채무조회서 샘플링·회수 툴 V2</h1>
  <div class="header-meta">
    <select id="projectSelect"></select>
    <button id="newProjectBtn">+ 새 프로젝트</button>
  </div>
</header>

<div class="dashboard">

  <aside class="side-panel">
    <section class="progress">
      <h3>진행도</h3>
      <ul id="progressList">
        <li data-step="ingest">자료 수집</li>
        <li data-step="design-ar">AR 표본</li>
        <li data-step="design-ap">AP 표본</li>
        <li data-step="send">발송 (Phase 3)</li>
        <li data-step="receive">회신 (Phase 3)</li>
        <li data-step="projection">Projection (Phase 3)</li>
      </ul>
    </section>

    <section class="metrics">
      <h3>핵심지표</h3>
      <div class="metric">
        <span class="label">모집단</span>
        <span class="value" id="populationTotal">—</span>
      </div>
      <div class="metric">
        <span class="label">표본</span>
        <span class="value" id="sampleTotal">—</span>
      </div>
      <div class="metric">
        <span class="label">커버리지</span>
        <span class="value" id="coveragePct">—</span>
      </div>
    </section>

    <section class="downloads">
      <h3>다운로드</h3>
      <button disabled>C100 (Phase 4)</button>
      <button disabled>AA100 (Phase 4)</button>
    </section>
  </aside>

  <main class="main-area">

    <!-- ① 자료 드롭존 -->
    <section id="dropzone">
      <h2>① 자료 업로드</h2>
      <div class="drops">
        <label>거래처원장<input type="file" id="file-ledger" accept=".xlsx"></label>
        <label>재무제표<input type="file" id="file-fs" accept=".xlsx"></label>
        <label>특관자<input type="file" id="file-rp" accept=".xlsx"></label>
        <label>충당금명세<input type="file" id="file-allowance" accept=".xlsx"></label>
      </div>
      <button id="ingestBtn">업로드·자동감지 실행</button>
      <div id="ingestResult"></div>
    </section>

    <!-- ② 표본설계 패널 -->
    <section id="designPanel">
      <h2>② 표본설계</h2>
      <div class="twin">
        <div class="kind-col" data-kind="AR">
          <h3>채권 (AR)</h3>
          <label>신뢰수준 <select class="conf"><option value="0.95">95%</option><option value="0.90">90%</option><option value="0.99">99%</option></select></label>
          <label>Expected MS% <input type="number" class="ems" step="0.05" value="0" min="0" max="0.5"></label>
          <label>Key threshold <input type="number" class="keyth" value="0" min="0"></label>
          <label>n_strata <input type="number" class="nstrata" value="4" min="1" max="10"></label>
          <button class="runDesign">설계 실행</button>
          <div class="designResult"></div>
        </div>
        <div class="kind-col" data-kind="AP">
          <h3>채무 (AP)</h3>
          <label>신뢰수준 <select class="conf"><option value="0.95">95%</option><option value="0.90">90%</option><option value="0.99">99%</option></select></label>
          <label>Expected MS% <input type="number" class="ems" step="0.05" value="0" min="0" max="0.5"></label>
          <label>Key threshold <input type="number" class="keyth" value="0" min="0"></label>
          <label>n_strata <input type="number" class="nstrata" value="4" min="1" max="10"></label>
          <button class="runDesign">설계 실행</button>
          <div class="designResult"></div>
        </div>
      </div>
    </section>

    <!-- ③ 합산 표본 테이블 -->
    <section id="sampleTable">
      <h2>③ 표본 합산 (AR + AP)</h2>
      <div class="filters">
        <label>종류 <select id="filterKind"><option value="">전체</option><option value="AR">AR</option><option value="AP">AP</option></select></label>
        <label>선정사유 <select id="filterReason"><option value="">전체</option><option value="FORCED_RP">RP</option><option value="FORCED_KEY">KEY</option><option value="REP">REP</option></select></label>
      </div>
      <table id="mergedTable">
        <thead>
          <tr>
            <th>종류</th><th>거래처코드</th><th>거래처명</th>
            <th>잔액(KRW)</th><th>통화</th><th>선정사유</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>

  </main>

</div>

<footer class="wat-footer">© CC_SAMPLING_TOOL V2 · K-IFRS 1109 · ISA 530/505</footer>

<script src="app.js"></script>
</body>
</html>
```

- [ ] **Step 2: styles.css 작성**

`c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css`:

```css
:root {
  --color-primary: #1e3a5f;
  --color-accent: #d4a017;
  --color-bg: #f7f9fc;
  --color-text: #222;
  --color-muted: #6b7280;
  --color-border: #e5e7eb;
  --color-ar: #3b82f6;
  --color-ap: #f97316;
  --color-bad: #dc2626;
  --color-key: #7c3aed;
  --color-rp: #059669;
  --radius: 6px;
  --shadow: 0 1px 3px rgba(0,0,0,.08);
  --font-base: -apple-system, "Segoe UI", "Pretendard", Roboto, sans-serif;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; font-family: var(--font-base);
              color: var(--color-text); background: var(--color-bg); }

/* WAT 표준 헤더 */
.wat-header {
  position: sticky; top: 0; z-index: 100;
  padding: 1.25rem 7.25rem;
  min-height: 76px;
  background: var(--color-primary); color: white;
  display: flex; align-items: center; justify-content: space-between;
}
.wat-header h1 { font-size: 1.25rem; margin: 0; }
.header-meta { display: flex; gap: .5rem; }
.header-meta select, .header-meta button {
  padding: .35rem .75rem; border-radius: var(--radius);
  border: 1px solid rgba(255,255,255,.25); background: rgba(255,255,255,.1);
  color: white;
}

/* WAT 표준 푸터 */
.wat-footer {
  position: fixed; bottom: 0; left: 0; right: 0;
  padding: .5rem 7.25rem;
  background: #2d3748; color: #cbd5e0;
  font-size: .75rem; text-align: center;
}

.dashboard {
  display: grid; grid-template-columns: 260px 1fr;
  gap: 1.5rem; padding: 1.5rem 7.25rem 4rem;
}

.side-panel {
  position: sticky; top: 92px; align-self: start;
  background: white; border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 1rem;
  display: flex; flex-direction: column; gap: 1.5rem;
}
.side-panel h3 { font-size: .9rem; color: var(--color-muted);
                  margin: 0 0 .5rem; text-transform: uppercase; }
.progress ul { list-style: none; padding: 0; margin: 0; }
.progress li { padding: .35rem .5rem; border-left: 3px solid var(--color-border);
               font-size: .85rem; }
.progress li.done { border-color: var(--color-rp); color: var(--color-text); }
.progress li.disabled { color: var(--color-muted); }
.metric { display: flex; justify-content: space-between; padding: .25rem 0;
          font-size: .85rem; }
.metric .label { color: var(--color-muted); }
.metric .value { font-weight: 600; }

.main-area { display: flex; flex-direction: column; gap: 1.5rem; }
.main-area section {
  background: white; border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 1.25rem;
}
.main-area h2 { font-size: 1.05rem; margin: 0 0 .75rem;
                color: var(--color-primary); }

#dropzone .drops {
  display: grid; grid-template-columns: repeat(2, 1fr);
  gap: .75rem; margin-bottom: 1rem;
}
#dropzone label {
  display: flex; flex-direction: column; gap: .25rem;
  padding: .5rem .75rem; border: 1px dashed var(--color-border);
  border-radius: var(--radius); font-size: .85rem;
}
button {
  background: var(--color-primary); color: white;
  border: none; padding: .45rem 1rem; border-radius: var(--radius);
  cursor: pointer; font-size: .85rem;
}
button:disabled { background: var(--color-muted); cursor: not-allowed; }
button:hover:not(:disabled) { background: #284a78; }

.twin { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.kind-col {
  padding: 1rem; border: 1px solid var(--color-border);
  border-radius: var(--radius);
}
.kind-col[data-kind="AR"] { border-top: 3px solid var(--color-ar); }
.kind-col[data-kind="AP"] { border-top: 3px solid var(--color-ap); }
.kind-col h3 { margin: 0 0 .75rem; font-size: .95rem; }
.kind-col label {
  display: flex; flex-direction: column; gap: .25rem;
  margin-bottom: .5rem; font-size: .8rem;
}
.kind-col input, .kind-col select {
  padding: .3rem .5rem; border-radius: var(--radius);
  border: 1px solid var(--color-border); font-size: .85rem;
}
.designResult { font-size: .8rem; color: var(--color-muted); margin-top: .5rem; }

.filters { display: flex; gap: .75rem; margin-bottom: .75rem; }
.filters label { font-size: .8rem; display: flex; gap: .25rem; align-items: center; }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { padding: .4rem .5rem; border-bottom: 1px solid var(--color-border);
         text-align: left; }
th { background: var(--color-bg); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.kind-tag {
  display: inline-block; padding: 1px 6px; border-radius: 10px;
  font-size: .7rem; font-weight: 600;
}
.kind-tag.AR { background: #dbeafe; color: var(--color-ar); }
.kind-tag.AP { background: #ffedd5; color: var(--color-ap); }
.reason-tag {
  display: inline-block; padding: 1px 6px; border-radius: 10px;
  font-size: .7rem;
}
.reason-tag.FORCED_RP { background: #d1fae5; color: var(--color-rp); }
.reason-tag.FORCED_KEY { background: #ede9fe; color: var(--color-key); }
.reason-tag.REP { background: #f3f4f6; color: var(--color-muted); }
```

- [ ] **Step 3: Flask static_folder가 frontend를 가리키도록 확인**

`api/app.py`에서 `Flask(__name__, static_folder="../frontend", static_url_path="")` 이미 설정됨 (Task 9에서).

- [ ] **Step 4: 시각 확인 (수동)**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m flask --app api.app run --host 127.0.0.1 --port 8521
```

브라우저: `http://127.0.0.1:8521/index.html` → 헤더·좌측 패널·3 섹션 보이는지 확인. 자바스크립트는 Task 14에서.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/
git -C c:/Claude commit -m "feat(frontend): dashboard shell (WAT header/footer, sticky side panel, 3 sections)"
```

---

### Task 14: Frontend — app.js (fetch + state + side panel)

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`

좌측 진행도·핵심지표·프로젝트 선택 + 단일 GET /state 호출로 전체 갱신.

- [ ] **Step 1: app.js 작성**

```javascript
"use strict";

const API = "/api";
let currentProjectId = null;
let currentState = null;

// ---- 유틸 ----
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const fmt = (n) => (n == null ? "—" : new Intl.NumberFormat("ko-KR").format(Math.round(n)));
const pct = (v) => (v == null ? "—" : (v * 100).toFixed(1) + "%");

async function api(method, path, body, isFile = false) {
  const opts = { method };
  if (body && !isFile) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  } else if (body && isFile) {
    opts.body = body;  // FormData
  }
  const resp = await fetch(API + path, opts);
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(`${resp.status}: ${err}`);
  }
  return resp.json();
}

// ---- 프로젝트 ----
async function loadProjectList() {
  const projects = await api("GET", "/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = '<option value="">— 프로젝트 선택 —</option>';
  for (const p of projects) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = `${p.client} · ${p.period_end}`;
    sel.appendChild(opt);
  }
  if (projects.length && currentProjectId == null) {
    sel.value = projects[0].id;
    await selectProject(projects[0].id);
  }
}

async function selectProject(pid) {
  currentProjectId = parseInt(pid, 10);
  if (!currentProjectId) return;
  await refreshState();
}

async function newProject() {
  const client = prompt("회사명?");
  if (!client) return;
  const period_end = prompt("평가기준일 (YYYY-MM-DD)?", "2025-12-31");
  if (!period_end) return;
  const materiality = parseFloat(prompt("Materiality (KRW)?", "500000000"));
  const tolerable = parseFloat(prompt("Tolerable misstatement (KRW)?", "250000000"));
  const created = await api("POST", "/projects", {
    client, period_end, base_ccy: "KRW", materiality, tolerable,
  });
  await loadProjectList();
  $("#projectSelect").value = created.id;
  await selectProject(created.id);
}

// ---- 상태 갱신 ----
async function refreshState() {
  if (!currentProjectId) return;
  currentState = await api("GET", `/projects/${currentProjectId}/state`);
  renderSidePanel();
  renderMergedTable();
}

function renderSidePanel() {
  const s = currentState;
  if (!s) return;
  const pop = (s.populations.AR.total_krw || 0) + (s.populations.AP.total_krw || 0);
  const samp = (s.samples.AR.total_krw || 0) + (s.samples.AP.total_krw || 0);
  $("#populationTotal").textContent = "₩" + fmt(pop);
  $("#sampleTotal").textContent = "₩" + fmt(samp);
  $("#coveragePct").textContent = pop > 0 ? pct(samp / pop) : "—";

  // 진행도 업데이트
  const setStep = (step, status) => {
    const li = $(`#progressList li[data-step="${step}"]`);
    if (!li) return;
    li.classList.remove("done", "disabled");
    if (status) li.classList.add(status);
  };
  setStep("ingest", s.populations.AR.count + s.populations.AP.count > 0 ? "done" : null);
  setStep("design-ar", s.samples.AR.count > 0 ? "done" : null);
  setStep("design-ap", s.samples.AP.count > 0 ? "done" : null);
  setStep("send", "disabled");
  setStep("receive", "disabled");
  setStep("projection", "disabled");
}

// ---- ③ 합산 테이블 (Task 17에서 더 정교화) ----
function renderMergedTable() {
  const tbody = $("#mergedTable tbody");
  tbody.innerHTML = "";
  const filterKind = $("#filterKind").value;
  const filterReason = $("#filterReason").value;
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const it of currentState.samples[k].items || []) {
      rows.push({ ...it, kind: k });
    }
  }
  const filtered = rows.filter(r =>
    (!filterKind || r.kind === filterKind)
    && (!filterReason || r.selection_reason === filterReason)
  );
  for (const r of filtered) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.party_id}</td>
      <td>${r.name}</td>
      <td class="num">${fmt(r.balance_krw)}</td>
      <td>${r.ccy}</td>
      <td><span class="reason-tag ${r.selection_reason}">${r.selection_reason}</span></td>
    `;
    tbody.appendChild(tr);
  }
}

// ---- 초기화 ----
async function init() {
  $("#projectSelect").addEventListener("change", e => selectProject(e.target.value));
  $("#newProjectBtn").addEventListener("click", newProject);
  $("#filterKind").addEventListener("change", renderMergedTable);
  $("#filterReason").addEventListener("change", renderMergedTable);
  await loadProjectList();
}

init().catch(e => { console.error(e); alert("초기화 실패: " + e.message); });
```

- [ ] **Step 2: 수동 테스트**

서버 재시작 → 브라우저 새로고침 → "+ 새 프로젝트" 누르고 입력 → 좌측 패널 갱신 확인.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/app.js
git -C c:/Claude commit -m "feat(frontend): app.js (project select/create, state polling, side panel)"
```

---

### Task 15: Frontend — ① 드롭존 ingest 핸들러

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js` (ingest 핸들러 추가)

- [ ] **Step 1: app.js에 ingest 함수 추가**

`frontend/app.js` 끝 부분 (`init()` 호출 전)에 추가:

```javascript
// ---- ① Ingest ----
async function runIngest() {
  if (!currentProjectId) { alert("프로젝트 먼저 선택"); return; }
  const fd = new FormData();
  const ledger = $("#file-ledger").files[0];
  if (!ledger) { alert("거래처원장 필수"); return; }
  fd.append("ledger", ledger);
  for (const [name, id] of [["fs", "file-fs"], ["rp", "file-rp"], ["allowance", "file-allowance"]]) {
    const f = $("#" + id).files[0];
    if (f) fd.append(name, f);
  }
  $("#ingestResult").textContent = "업로드·자동감지 중...";
  try {
    const result = await api("POST", `/projects/${currentProjectId}/ingest`, fd, true);
    const lines = [
      `AR ${result.ar_count}건 · ₩${fmt(result.ar_total_krw)} (자동감지 ${pct(result.confidence_ar)})`,
      `AP ${result.ap_count}건 · ₩${fmt(result.ap_total_krw)} (자동감지 ${pct(result.confidence_ap)})`,
    ];
    if (result.needs_mapping_confirmation) {
      lines.push("⚠ 자동감지 신뢰도 < 95% — 매핑확인 필요 (Phase 2 향후 추가)");
    }
    if (result.fs_totals && Object.keys(result.fs_totals).length > 0) {
      lines.push(`FS cross-check: AR=₩${fmt(result.fs_totals.AR)}, AP=₩${fmt(result.fs_totals.AP)}`);
    }
    $("#ingestResult").innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    await refreshState();
  } catch (e) {
    $("#ingestResult").textContent = "오류: " + e.message;
  }
}

// init() 안에 추가:
// $("#ingestBtn").addEventListener("click", runIngest);
```

기존 `init()` 함수 안 다른 listener와 함께 `$("#ingestBtn").addEventListener("click", runIngest);` 추가.

- [ ] **Step 2: 수동 테스트**

서버 재시작 → 더미 fixture (`tests/e2e/fixtures/dummy_*.xlsx`) 드롭 → "업로드·자동감지 실행" → 결과 표시 + 좌측 패널 모집단 갱신 확인.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/app.js
git -C c:/Claude commit -m "feat(frontend): ingest handler (drop zone → /ingest + result inline)"
```

---

### Task 16: Frontend — ② 표본설계 패널 핸들러

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`

- [ ] **Step 1: app.js에 design 함수 추가**

```javascript
// ---- ② Design ----
async function runDesign(ev) {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const col = ev.target.closest(".kind-col");
  const kind = col.dataset.kind;
  const params = {
    kind,
    confidence: parseFloat(col.querySelector(".conf").value),
    expected_ms_pct: parseFloat(col.querySelector(".ems").value),
    key_threshold: parseFloat(col.querySelector(".keyth").value || "0"),
    n_strata: parseInt(col.querySelector(".nstrata").value, 10),
    seed: Math.floor(Math.random() * 1_000_000),  // 자동 seed (재실행 다른 결과)
  };
  const resultDiv = col.querySelector(".designResult");
  resultDiv.textContent = "설계 중...";
  try {
    const r = await api("POST", `/projects/${currentProjectId}/sampling/design`, params);
    const lines = [
      `표본 ${r.n_total}건 (강제 ${r.n_forced} · 대표 ${r.n_representative})`,
      `제외 ${r.n_excluded} · BV ₩${fmt(r.population_bv)}`,
      `seed ${r.used_seed}`,
    ];
    resultDiv.innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    await refreshState();
  } catch (e) {
    resultDiv.textContent = "오류: " + e.message;
  }
}

// init() 안에 추가:
// $$(".runDesign").forEach(btn => btn.addEventListener("click", runDesign));
```

`init()` 함수 안에 `$$(".runDesign").forEach(btn => btn.addEventListener("click", runDesign));` 추가.

- [ ] **Step 2: 수동 테스트**

AR 패널에서 "설계 실행" → 표본 N건 표시 + ③ 합산 테이블에 행 표시 확인.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/app.js
git -C c:/Claude commit -m "feat(frontend): design panel handler (AR/AP twin column → /sampling/design)"
```

---

### Task 17: Frontend — ③ 합산 테이블 정렬·금액 정밀화

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`

테이블 정렬 + balance_krw 큰 순서 default. RP/BAD 배지 표시.

- [ ] **Step 1: renderMergedTable 개선**

`renderMergedTable` 함수를 다음으로 교체:

```javascript
function renderMergedTable() {
  const tbody = $("#mergedTable tbody");
  tbody.innerHTML = "";
  const filterKind = $("#filterKind").value;
  const filterReason = $("#filterReason").value;
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const it of currentState.samples[k].items || []) {
      rows.push({ ...it, kind: k });
    }
  }
  // 잔액 큰 순서로 default 정렬
  rows.sort((a, b) => Math.abs(b.balance_krw) - Math.abs(a.balance_krw));
  const filtered = rows.filter(r =>
    (!filterKind || r.kind === filterKind)
    && (!filterReason || r.selection_reason === filterReason)
  );
  for (const r of filtered) {
    const tr = document.createElement("tr");
    const badges = [];
    if (r.is_related_party) badges.push(`<span class="badge rp">RP</span>`);
    if (r.is_bad_debt) badges.push(`<span class="badge bad">BAD</span>`);
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.party_id}</td>
      <td>${r.name} ${badges.join(" ")}</td>
      <td class="num">${fmt(r.balance_krw)}</td>
      <td>${r.ccy}</td>
      <td><span class="reason-tag ${r.selection_reason}">${r.selection_reason}</span></td>
    `;
    tbody.appendChild(tr);
  }
  // 빈 결과
  if (!filtered.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="6" style="text-align:center;color:var(--color-muted);padding:2rem;">표본 없음 — ② 패널에서 설계 실행</td>`;
    tbody.appendChild(tr);
  }
}
```

- [ ] **Step 2: 배지 CSS 추가 — styles.css 끝에**

```css
.badge {
  display: inline-block; padding: 0px 4px; border-radius: 8px;
  font-size: .6rem; font-weight: 600; margin-left: 3px;
}
.badge.rp { background: #d1fae5; color: var(--color-rp); }
.badge.bad { background: #fee2e2; color: var(--color-bad); }
```

- [ ] **Step 3: 수동 테스트**

테이블에 RP·BAD 배지·잔액 desc 정렬 확인. 필터 동작 확인.

- [ ] **Step 4: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/app.js CC_SAMPLING_TOOL_V2/frontend/styles.css
git -C c:/Claude commit -m "feat(frontend): merged table sort by balance + RP/BAD badges"
```

---

### Task 18: E2E test + Phase 2 회귀 + tag

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/test_drop_to_sampling.py`

전 흐름: 프로젝트 생성 → 더미 fixture 4개 ingest → AR·AP 표본설계 → state 확인.

- [ ] **Step 1: 실패 테스트**

`tests/e2e/test_drop_to_sampling.py`:

```python
"""E2E — Phase 2 마일스톤: 드롭 → 합산 표본 표시 직전까지."""
import pytest
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def fixtures_ready():
    for name in ("dummy_ledger", "dummy_fs", "dummy_rp", "dummy_allowance"):
        if not (FIXTURES / f"{name}.xlsx").exists():
            pytest.skip(f"fixture {name}.xlsx missing — run build_dummy.py")


@pytest.fixture
def client(fixtures_ready):
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SF = make_session(engine)

    fx_mock = MagicMock()
    fx_mock.lookup.return_value = 1300.0

    app = create_app(testing=True, session_factory=SF)
    app.config["FX_CLIENT"] = fx_mock
    return app.test_client()


def _file(name):
    return (open(FIXTURES / f"{name}.xlsx", "rb"), f"{name}.xlsx")


def test_e2e_drop_to_sampling(client):
    # 1) 프로젝트 생성
    r = client.post("/api/projects", json={
        "client": "DUMMY_CLIENT", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 50_000_000, "tolerable": 25_000_000,
    })
    pid = r.get_json()["id"]

    # 2) 4종 ingest
    data = {
        "ledger": _file("dummy_ledger"),
        "fs": _file("dummy_fs"),
        "rp": _file("dummy_rp"),
        "allowance": _file("dummy_allowance"),
    }
    r = client.post(f"/api/projects/{pid}/ingest",
                    data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    ing = r.get_json()
    assert ing["ar_count"] == 120
    assert ing["ap_count"] == 80
    assert ing["confidence_ar"] >= 0.95
    assert ing["confidence_ap"] >= 0.95
    assert ing["fs_totals"]["AR"] == 250_000_000  # FS cross-check

    # 3) AR 표본설계
    r = client.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AR", "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
    })
    assert r.status_code == 200
    ar = r.get_json()
    assert ar["n_total"] >= 5  # 적어도 RP 5건은 포함

    # 4) AP 표본설계
    r = client.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AP", "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
    })
    assert r.status_code == 200
    ap = r.get_json()
    assert ap["n_total"] > 0

    # 5) state 합산 확인
    r = client.get(f"/api/projects/{pid}/state")
    body = r.get_json()
    assert body["populations"]["AR"]["count"] == 120
    assert body["populations"]["AP"]["count"] == 80
    assert body["samples"]["AR"]["count"] == ar["n_total"]
    assert body["samples"]["AP"]["count"] == ap["n_total"]
    # 합산 items에 AR/AP 모두 있는지
    ar_items = body["samples"]["AR"]["items"]
    ap_items = body["samples"]["AP"]["items"]
    assert any(i["selection_reason"] == "FORCED_RP" for i in ar_items)
    # 부실 거래처 제외 확인
    for item in ar_items + ap_items:
        if item["is_bad_debt"] and item["selection_reason"] in ("FORCED_KEY", "REP"):
            pytest.fail(f"부실거래처가 표본 포함: {item}")
```

- [ ] **Step 2: 실행**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/e2e -v
```

Expected: PASS. 실패 시 디버그.

- [ ] **Step 3: Phase 2 전체 회귀**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/ -q
```

Expected: 모든 unit + integration + e2e 통과. 테스트 수 = Phase 1(88) + Phase 2 신규(~30+) = ~120+.

- [ ] **Step 4: domain 순수성 재검증**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -c "
import ast, sys
from pathlib import Path
forbidden = {'flask', 'sqlalchemy', 'pandas', 'openpyxl', 'pdfplumber', 'requests'}
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

Expected: `domain pure: OK`.

- [ ] **Step 5: Phase 2 마무리 커밋 + tag**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/e2e/test_drop_to_sampling.py
git -C c:/Claude commit -m "test(e2e): drop-to-sampling full flow + Phase 2 complete"
git -C c:/Claude tag cc-v2-phase2
```

---

## Phase 2 완료 기준

- `pytest tests/ -q` 전체 PASS (~120+ tests)
- domain 순수성 통과 (forbidden import 0)
- e2e 시나리오 (드롭 → 표본 표시) 자동 회귀
- 단일 대시보드 ①②③ 작동 (수동 시각 확인)
- `git tag cc-v2-phase2`

## Phase 3 예고

- 발송명단 Excel 생성
- PDF 회신 추출·매칭·차이판정
- 대체적 절차 등록·coverage
- ISA 530 PPS projection 결과 표시 + ⑥ 패널
- 별도 plan: `2026-05-28-cc-sampling-tool-v2-phase3.md`

## Phase 1 이월 참고

- ISA 530 incremental allowance — Table A-4 rank-증분 (Phase 3 ±0.5% 정합 위해)
- PPS seed persistence — DB 저장 (현재 응답에만 포함; Phase 3 SampleDesign 테이블 추가 시 함께)
- floor/ratio 임계 불연속 — Phase 2 UX 검토 결과 그대로 유지
- FK 인덱스·cascade 대칭 — Phase 4 마이그레이션 시
