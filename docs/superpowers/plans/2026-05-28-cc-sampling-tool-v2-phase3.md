# CC_SAMPLING_TOOL_V2 Phase 3 — Confirmation + Alternative + Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 표본별 발송명단 Excel 생성 → PDF 회신 업로드·자동추출·매칭·차이판정 → 미회신에 대체적 절차 등록·coverage 산정 → ISA 530 PPS projection (AR·AP 분리, 합산판정) 완주. UI ④⑤⑥ 추가.

**Architecture:** Phase 1·2 위에 추가 layer — 새 도메인 helper(coverage), pdfplumber 추출 어댑터, 새 DB 테이블 2개(AlternativeProcedure, Projection), 4개 application UC, 3개 API 라우트 패밀리, Vanilla JS 단일 대시보드 3개 섹션. Clean arch 의존방향 유지.

**Tech Stack:** Python 3.11+ / Flask 3.x / SQLAlchemy 2.x / pdfplumber / openpyxl / pandas / Vanilla JS.

**Spec 참조:** [2026-05-28-cc-sampling-tool-v2-design.md](../specs/2026-05-28-cc-sampling-tool-v2-design.md) §3 (UI ④⑤⑥), §5.6 (matching, Phase 2에서 이미 도메인 함수 작성), §5.7 (alt-proc coverage), §5.8 (PPS projection, Phase 1에서 도메인 함수 작성), §6.1 [4]~[7] (흐름).

**Phase 3 마일스톤:** 더미 데이터 + 더미 PDF 회신 → 발송명단 Excel 생성 → PDF 매칭·차이 → 대체적 절차 → AR·AP 합산 projection. e2e 자동회귀.

---

## File Structure

신규/수정 (Phase 3):

```
CC_SAMPLING_TOOL_V2/
├── src/
│   ├── domain/
│   │   └── alternative.py                    # 신규: coverage_pct + verdict
│   │
│   ├── application/
│   │   ├── send_list_uc.py                   # 신규: 표본 → 발송명단 Excel
│   │   ├── match_response_uc.py              # 신규: PDF → Confirmation persist
│   │   ├── alternative_uc.py                 # 신규: 대체적 절차 등록·coverage 갱신
│   │   └── projection_uc.py                  # 신규: AR/AP PPS projection + persist
│   │
│   └── infrastructure/
│       ├── db/
│       │   ├── models.py                     # 수정: AlternativeProcedureRow + ProjectionRow 추가
│       │   └── repository.py                 # 수정: ConfirmationRepo/AltProcRepo/ProjectionRepo 추가
│       ├── pdf/                              # 신규 패키지
│       │   ├── __init__.py
│       │   ├── extractor.py                  # pdfplumber 텍스트 추출
│       │   └── amount_extractor.py           # 텍스트 → 거래처/금액 regex
│       └── excel_writer/                     # 신규 패키지
│           ├── __init__.py
│           ├── styles.py                     # tickmark·서식 토큰
│           └── sendlist.py                   # 발송명단 Excel
│
├── api/
│   ├── app.py                                # 수정: confirmations/alternative/projection blueprint 등록
│   └── routes/
│       ├── confirmations.py                  # 신규: sendlist download / PDF upload / list
│       ├── alternative.py                    # 신규: POST register / GET list
│       ├── projection.py                     # 신규: POST compute / GET result
│       └── state.py                          # 수정: confirmations/alternatives/projection 합산 노출
│
├── frontend/
│   ├── index.html                            # 수정: ④⑤⑥ 섹션 마크업 추가
│   ├── styles.css                            # 수정: verdict 컬러 토큰, 트래커 레이아웃
│   └── app.js                                # 수정: ④⑤⑥ 핸들러 + 좌측 패널 갱신
│
└── tests/
    ├── unit/
    │   └── test_alternative_domain.py        # 신규
    ├── integration/
    │   ├── test_pdf_extractor.py             # 신규
    │   ├── test_amount_extractor.py          # 신규
    │   ├── test_repository_phase3.py         # 신규: AltProc/Projection CRUD
    │   ├── test_sendlist_uc.py
    │   ├── test_match_response_uc.py
    │   ├── test_alternative_uc.py
    │   ├── test_projection_uc.py
    │   ├── test_confirmations_route.py
    │   ├── test_alternative_route.py
    │   ├── test_projection_route.py
    │   └── test_excel_sendlist.py
    └── e2e/
        ├── fixtures/
        │   └── build_dummy_pdfs.py           # 신규: 더미 PDF 회신 생성
        │   └── *.pdf                         # 생성된 더미 PDF (5건)
        └── test_drop_to_projection.py        # 신규: 전 라이프사이클 e2e
```

**책임 분리**:
- `domain/alternative.py` — 순수 함수: coverage_pct, ACCEPTABLE/INSUFFICIENT verdict
- `infrastructure/pdf/extractor.py` — pdfplumber 호출 + OCR optional (개념적 점선)
- `infrastructure/pdf/amount_extractor.py` — 추출된 텍스트에서 거래처명/금액 regex
- `infrastructure/excel_writer/` — 양식 Excel 생성 (Phase 4에서 C100/AA100 추가 예정)
- 각 UC: 도메인 + repository + 인프라 조합. application layer 의존만
- 라우트: HTTP 변환만

---

## 작업 순서

1. **Task 1**: domain `alternative.py` — coverage 계산
2. **Task 2**: DB models 확장 (AlternativeProcedureRow + ProjectionRow)
3. **Task 3**: Repository 확장 (ConfirmationRepo, AltProcRepo, ProjectionRepo)
4. **Task 4**: PDF 텍스트 추출 (pdfplumber)
5. **Task 5**: PDF 금액 추출 (regex/heuristic)
6. **Task 6**: 발송명단 Excel writer
7. **Task 7**: `send_list_uc` (표본 → Excel bytes)
8. **Task 8**: `match_response_uc` (PDF → Confirmation persist + judge_response)
9. **Task 9**: `alternative_uc` (대체적 절차 등록 + coverage)
10. **Task 10**: `projection_uc` (AR/AP PPS projection + persist)
11. **Task 11**: API route confirmations (sendlist GET + PDF POST + list)
12. **Task 12**: API route alternative
13. **Task 13**: API route projection + state 확장
14. **Task 14**: Frontend ④ 발송·회신 트래커
15. **Task 15**: Frontend ⑤ 대체적 절차
16. **Task 16**: Frontend ⑥ Projection
17. **Task 17**: 더미 PDF fixture 생성
18. **Task 18**: E2E 전 라이프사이클 + tag `cc-v2-phase3`

---

### Task 1: Domain helper — alternative coverage

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/domain/alternative.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/unit/test_alternative_domain.py`

설계 §5.7: `coverage_pct = covered_amt / non_response_total`, ACCEPTABLE if ≥ 0.75.

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_alternative_domain.py`:

```python
import pytest
from src.domain.alternative import coverage_verdict, COVERAGE_ACCEPTABLE_THRESHOLD


def test_coverage_acceptable_high():
    pct, verdict = coverage_verdict(covered_amt=800, non_response_total=1000)
    assert pct == pytest.approx(0.8)
    assert verdict == "ACCEPTABLE"


def test_coverage_insufficient_low():
    pct, verdict = coverage_verdict(covered_amt=500, non_response_total=1000)
    assert pct == 0.5
    assert verdict == "INSUFFICIENT"


def test_coverage_exact_threshold_acceptable():
    pct, verdict = coverage_verdict(
        covered_amt=750, non_response_total=1000)
    # 0.75 → ACCEPTABLE (>=)
    assert verdict == "ACCEPTABLE"


def test_coverage_zero_non_response_returns_acceptable():
    """미회신 0건이면 coverage 정의 X → ACCEPTABLE (모두 회신)."""
    pct, verdict = coverage_verdict(covered_amt=0, non_response_total=0)
    assert verdict == "ACCEPTABLE"
    assert pct == 1.0


def test_coverage_capped_at_one():
    # 증빙이 미회신액 초과해도 1.0 cap (over-coverage 안전)
    pct, verdict = coverage_verdict(
        covered_amt=2000, non_response_total=1000)
    assert pct == 1.0
    assert verdict == "ACCEPTABLE"


def test_coverage_threshold_constant():
    assert COVERAGE_ACCEPTABLE_THRESHOLD == 0.75
```

- [ ] **Step 2: 실패 확인**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/unit/test_alternative_domain.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/domain/alternative.py`:

```python
"""대체적 절차 coverage 계산.

설계서 §5.7. coverage_pct >= 0.75 이면 ACCEPTABLE.
"""
from __future__ import annotations
from typing import Literal


COVERAGE_ACCEPTABLE_THRESHOLD = 0.75


def coverage_verdict(
    covered_amt: float,
    non_response_total: float,
) -> tuple[float, Literal["ACCEPTABLE", "INSUFFICIENT"]]:
    """대체적 절차 증빙 비율 + 충분성 판정.

    Args:
        covered_amt: 대체적 절차로 증빙된 잔액 합계.
        non_response_total: 미회신 잔액 합계.

    Returns:
        (pct, verdict). pct는 [0, 1] 범위로 cap.
    """
    if non_response_total <= 0:
        # 미회신 0 → 정의 X. 모두 회신이므로 충분 처리.
        return 1.0, "ACCEPTABLE"
    pct = min(1.0, covered_amt / non_response_total)
    verdict = "ACCEPTABLE" if pct >= COVERAGE_ACCEPTABLE_THRESHOLD else "INSUFFICIENT"
    return pct, verdict
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_alternative_domain.py -v` → 6 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/alternative.py CC_SAMPLING_TOOL_V2/tests/unit/test_alternative_domain.py
git -C c:/Claude commit -m "feat(domain): alternative procedure coverage (0.75 threshold, capped at 1.0)"
```

---

### Task 2: DB models 확장 — AlternativeProcedureRow + ProjectionRow

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/models.py` (append 2 classes)
- Test: 기존 `tests/integration/test_repository_phase3.py`에서 확인

설계 §2.2: AlternativeProcedure(kind, party_id, type, evidence_sum, coverage_pct), ProjectionResult(kind, projected_ms, basic_precision, incremental, upper_limit, tolerable, verdict).

ProjectionRow는 strata snapshot도 JSON으로 저장 (Phase 2 carryover #4 해결).

- [ ] **Step 1: 모델 추가**

Read `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/models.py`. 끝에 다음을 append:

```python


class AlternativeProcedureRow(Base):
    __tablename__ = "alternative_procedures"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_altproc_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    procedure_type = Column(String(50), nullable=False)
    evidence_sum = Column(Float, nullable=False, default=0.0)
    coverage_pct = Column(Float, nullable=False, default=0.0)
    note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProjectionRow(Base):
    __tablename__ = "projections"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_projection_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    confidence = Column(Float, nullable=False)
    sampling_interval = Column(Float, nullable=False)
    tolerable = Column(Float, nullable=False)
    projected_misstatement = Column(Float, nullable=False)
    basic_precision = Column(Float, nullable=False)
    incremental_allowance = Column(Float, nullable=False)
    upper_limit = Column(Float, nullable=False)
    verdict = Column(String(30), nullable=False)
    strata_snapshot = Column(Text)  # JSON: [{low, high, n_required}, ...]
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 2: 통과 확인 (기존 회귀)**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/ -q`
Expected: 135 passed (기존). 새 모델은 다음 Task에서 사용.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/db/models.py
git -C c:/Claude commit -m "feat(infra): add AlternativeProcedureRow + ProjectionRow (with strata snapshot)"
```

---

### Task 3: Repository 확장 — Confirmation/AltProc/Projection

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py` (append 3 classes)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_repository_phase3.py`

각각 별도 클래스: ConfirmationRepo, AltProcRepo, ProjectionRepo.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_repository_phase3.py`:

```python
import pytest
from datetime import date, datetime
from src.domain.entities import (
    Account, Kind, SelectionReason, ResponseStatus, Verdict,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
    ConfirmationRepo, AltProcRepo, ProjectionRepo,
)


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_sample(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    acc = Account(party_id="P1", name="갑", gl_account="11200",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(
        pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    return pid


def test_confirmation_upsert(session, project_with_sample):
    pid = project_with_sample
    repo = ConfirmationRepo(session)
    repo.upsert(pid, Kind.AR, party_id="P1",
                expected=1000, confirmed=999,
                verdict=Verdict.MATCH, diff_reason=None,
                pdf_path="/tmp/conf.pdf",
                status=ResponseStatus.RECEIVED)
    rows = repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0].verdict == Verdict.MATCH
    assert rows[0].confirmed == 999


def test_confirmation_upsert_replaces(session, project_with_sample):
    pid = project_with_sample
    repo = ConfirmationRepo(session)
    repo.upsert(pid, Kind.AR, party_id="P1",
                expected=1000, confirmed=None,
                verdict=Verdict.NO_RESPONSE, diff_reason=None,
                pdf_path=None, status=ResponseStatus.PENDING)
    repo.upsert(pid, Kind.AR, party_id="P1",
                expected=1000, confirmed=950,
                verdict=Verdict.DISCREPANCY, diff_reason=None,
                pdf_path="/tmp/x.pdf", status=ResponseStatus.RECEIVED)
    rows = repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0].confirmed == 950


def test_altproc_persist_and_list(session, project_with_sample):
    pid = project_with_sample
    repo = AltProcRepo(session)
    repo.upsert(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수",
                evidence_sum=500, coverage_pct=0.5,
                note="회수증빙 확인")
    rows = repo.list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0]["procedure_type"] == "후속회수"
    assert rows[0]["evidence_sum"] == 500


def test_projection_persist_and_get(session, project_with_sample):
    pid = project_with_sample
    repo = ProjectionRepo(session)
    repo.upsert(pid, Kind.AR, confidence=0.95,
                sampling_interval=10_000, tolerable=500_000,
                projected_misstatement=1000,
                basic_precision=30_000,
                incremental_allowance=500,
                upper_limit=31_500,
                verdict="WITHIN_TOLERABLE",
                strata_snapshot=[{"low": 0, "high": 1000, "n_required": 5}])
    got = repo.get_latest(pid, Kind.AR)
    assert got is not None
    assert got["upper_limit"] == 31_500
    assert got["strata_snapshot"][0]["high"] == 1000


def test_projection_upsert_replaces(session, project_with_sample):
    pid = project_with_sample
    repo = ProjectionRepo(session)
    repo.upsert(pid, Kind.AR, confidence=0.95,
                sampling_interval=10_000, tolerable=500_000,
                projected_misstatement=1000, basic_precision=30_000,
                incremental_allowance=500, upper_limit=31_500,
                verdict="WITHIN_TOLERABLE", strata_snapshot=[])
    repo.upsert(pid, Kind.AR, confidence=0.95,
                sampling_interval=10_000, tolerable=500_000,
                projected_misstatement=5000, basic_precision=30_000,
                incremental_allowance=2000, upper_limit=37_000,
                verdict="WITHIN_TOLERABLE", strata_snapshot=[])
    got = repo.get_latest(pid, Kind.AR)
    assert got["projected_misstatement"] == 5000
```

- [ ] **Step 2: 실패 확인**

`python -m pytest tests/integration/test_repository_phase3.py -v` → ImportError.

- [ ] **Step 3: 구현**

Read `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py`. 상단 import에 추가:

```python
import json
from datetime import datetime
from src.domain.entities import ResponseStatus, Verdict
from src.infrastructure.db.models import (
    ProjectRow, AccountRow, SampleRow,
    ConfirmationRow, AlternativeProcedureRow, ProjectionRow,
)
```

(기존 import 합쳐서 정리)

파일 끝에 append:

```python


class ConfirmationRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, party_id: str,
               expected: float, confirmed: Optional[float],
               verdict: Optional[Verdict], diff_reason: Optional[str],
               pdf_path: Optional[str], status: ResponseStatus) -> None:
        # sample_id 매핑
        sample = (self.s.query(SampleRow, AccountRow)
                  .join(AccountRow, SampleRow.account_id == AccountRow.id)
                  .filter(SampleRow.project_id == project_id,
                          SampleRow.kind == kind.value,
                          AccountRow.party_id == party_id)
                  .first())
        if sample is None:
            raise ValueError(
                f"sample for project={project_id} kind={kind.value} party={party_id!r} not found")
        sample_row, acc_row = sample

        existing = (self.s.query(ConfirmationRow)
                    .filter(ConfirmationRow.project_id == project_id,
                            ConfirmationRow.sample_id == sample_row.id)
                    .first())
        diff = None if confirmed is None else (confirmed - expected)
        verdict_val = verdict.value if verdict is not None else None
        now = datetime.utcnow()

        if existing is None:
            row = ConfirmationRow(
                project_id=project_id, sample_id=sample_row.id,
                kind=kind.value, expected=expected,
                status=status.value, confirmed=confirmed, diff=diff,
                diff_reason=diff_reason, pdf_path=pdf_path,
                verdict=verdict_val,
                sent_at=None,
                extracted_at=now if confirmed is not None else None,
            )
            self.s.add(row)
        else:
            existing.expected = expected
            existing.status = status.value
            existing.confirmed = confirmed
            existing.diff = diff
            existing.diff_reason = diff_reason
            existing.pdf_path = pdf_path
            existing.verdict = verdict_val
            if confirmed is not None:
                existing.extracted_at = now
        self.s.commit()

    def list_by_project_kind(self, project_id: int, kind: Kind
                             ) -> list:
        """반환: list of 단순 객체 (party_id, expected, confirmed, diff, verdict, status, pdf_path, diff_reason)."""
        rows = (self.s.query(ConfirmationRow, AccountRow)
                .join(SampleRow, ConfirmationRow.sample_id == SampleRow.id)
                .join(AccountRow, SampleRow.account_id == AccountRow.id)
                .filter(ConfirmationRow.project_id == project_id,
                        ConfirmationRow.kind == kind.value)
                .all())
        out = []
        for conf, acc in rows:
            out.append(_ConfDTO(
                party_id=acc.party_id, name=acc.name,
                balance_krw=acc.balance_krw,
                expected=conf.expected, confirmed=conf.confirmed,
                diff=conf.diff, diff_reason=conf.diff_reason,
                verdict=Verdict(conf.verdict) if conf.verdict else None,
                status=ResponseStatus(conf.status),
                pdf_path=conf.pdf_path,
            ))
        return out


from dataclasses import dataclass


@dataclass
class _ConfDTO:
    party_id: str
    name: str
    balance_krw: float
    expected: float
    confirmed: Optional[float]
    diff: Optional[float]
    diff_reason: Optional[str]
    verdict: Optional[Verdict]
    status: ResponseStatus
    pdf_path: Optional[str]


class AltProcRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, party_id: str,
               procedure_type: str, evidence_sum: float,
               coverage_pct: float, note: Optional[str] = None) -> None:
        sample = (self.s.query(SampleRow, AccountRow)
                  .join(AccountRow, SampleRow.account_id == AccountRow.id)
                  .filter(SampleRow.project_id == project_id,
                          SampleRow.kind == kind.value,
                          AccountRow.party_id == party_id)
                  .first())
        if sample is None:
            raise ValueError(
                f"sample for project={project_id} party={party_id!r} not found")
        sample_row, _ = sample

        existing = (self.s.query(AlternativeProcedureRow)
                    .filter(AlternativeProcedureRow.project_id == project_id,
                            AlternativeProcedureRow.sample_id == sample_row.id)
                    .first())
        if existing is None:
            self.s.add(AlternativeProcedureRow(
                project_id=project_id, sample_id=sample_row.id,
                kind=kind.value, procedure_type=procedure_type,
                evidence_sum=evidence_sum, coverage_pct=coverage_pct,
                note=note,
            ))
        else:
            existing.procedure_type = procedure_type
            existing.evidence_sum = evidence_sum
            existing.coverage_pct = coverage_pct
            existing.note = note
        self.s.commit()

    def list_by_project_kind(self, project_id: int, kind: Kind
                             ) -> list[dict]:
        rows = (self.s.query(AlternativeProcedureRow, AccountRow)
                .join(SampleRow, AlternativeProcedureRow.sample_id == SampleRow.id)
                .join(AccountRow, SampleRow.account_id == AccountRow.id)
                .filter(AlternativeProcedureRow.project_id == project_id,
                        AlternativeProcedureRow.kind == kind.value)
                .all())
        return [{
            "party_id": acc.party_id, "name": acc.name,
            "procedure_type": ap.procedure_type,
            "evidence_sum": ap.evidence_sum,
            "coverage_pct": ap.coverage_pct,
            "note": ap.note,
        } for ap, acc in rows]


class ProjectionRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, confidence: float,
               sampling_interval: float, tolerable: float,
               projected_misstatement: float, basic_precision: float,
               incremental_allowance: float, upper_limit: float,
               verdict: str, strata_snapshot: list[dict]) -> None:
        snap = json.dumps(strata_snapshot, ensure_ascii=False)
        existing = (self.s.query(ProjectionRow)
                    .filter(ProjectionRow.project_id == project_id,
                            ProjectionRow.kind == kind.value)
                    .order_by(ProjectionRow.computed_at.desc())
                    .first())
        if existing is None:
            self.s.add(ProjectionRow(
                project_id=project_id, kind=kind.value,
                confidence=confidence,
                sampling_interval=sampling_interval,
                tolerable=tolerable,
                projected_misstatement=projected_misstatement,
                basic_precision=basic_precision,
                incremental_allowance=incremental_allowance,
                upper_limit=upper_limit, verdict=verdict,
                strata_snapshot=snap,
            ))
        else:
            existing.confidence = confidence
            existing.sampling_interval = sampling_interval
            existing.tolerable = tolerable
            existing.projected_misstatement = projected_misstatement
            existing.basic_precision = basic_precision
            existing.incremental_allowance = incremental_allowance
            existing.upper_limit = upper_limit
            existing.verdict = verdict
            existing.strata_snapshot = snap
            existing.computed_at = datetime.utcnow()
        self.s.commit()

    def get_latest(self, project_id: int, kind: Kind) -> Optional[dict]:
        row = (self.s.query(ProjectionRow)
               .filter(ProjectionRow.project_id == project_id,
                       ProjectionRow.kind == kind.value)
               .order_by(ProjectionRow.computed_at.desc())
               .first())
        if row is None:
            return None
        return {
            "kind": row.kind, "confidence": row.confidence,
            "sampling_interval": row.sampling_interval,
            "tolerable": row.tolerable,
            "projected_misstatement": row.projected_misstatement,
            "basic_precision": row.basic_precision,
            "incremental_allowance": row.incremental_allowance,
            "upper_limit": row.upper_limit, "verdict": row.verdict,
            "strata_snapshot": json.loads(row.strata_snapshot or "[]"),
            "computed_at": row.computed_at.isoformat()
                            if row.computed_at else None,
        }
```

NOTE: 기존 `from typing import Optional` 있는지 확인하고 없으면 추가.

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_repository_phase3.py -v` → 5 passed.

전체 회귀: `python -m pytest tests/ -q` → 140 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py CC_SAMPLING_TOOL_V2/tests/integration/test_repository_phase3.py
git -C c:/Claude commit -m "feat(infra): ConfirmationRepo + AltProcRepo + ProjectionRepo (upsert + DTOs)"
```

---

### Task 4: PDF text 추출 (pdfplumber)

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/__init__.py` (빈)
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/extractor.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_pdf_extractor.py`

설계 §6.1 [5]. pdfplumber 텍스트층 우선, OCR 옵셔널 (Phase 3 범위에서는 텍스트층만 강제).

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_pdf_extractor.py`:

```python
import pytest
from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text, PdfExtractError


def _make_test_pdf(path: Path, text: str) -> None:
    """간단한 텍스트층 PDF 생성 (reportlab 또는 pdfplumber로)."""
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    c = canvas.Canvas(str(path))
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()


def test_extract_text_from_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    _make_test_pdf(pdf, "Hello World\nLine 2")
    text = extract_text(pdf)
    assert "Hello World" in text
    assert "Line 2" in text


def test_extract_missing_file_raises(tmp_path):
    with pytest.raises(PdfExtractError):
        extract_text(tmp_path / "nonexistent.pdf")


def test_extract_empty_pdf_returns_empty(tmp_path):
    pdf = tmp_path / "empty.pdf"
    _make_test_pdf(pdf, "")
    text = extract_text(pdf)
    assert text == "" or text.strip() == ""
```

- [ ] **Step 2: requirements.txt 추가**

Read `c:/Claude/CC_SAMPLING_TOOL_V2/requirements.txt`. 추가:

```
reportlab>=4.0
```

설치: `python -m pip install reportlab`.

- [ ] **Step 3: 실패 확인**

`pytest tests/integration/test_pdf_extractor.py -v` → ImportError.

- [ ] **Step 4: 구현**

`src/infrastructure/pdf/__init__.py` (빈).

`src/infrastructure/pdf/extractor.py`:

```python
"""PDF 텍스트층 추출 (pdfplumber).

설계서 §6.1 [5]. OCR은 별도 모듈 (Phase 3 범위 밖).
"""
from __future__ import annotations
from pathlib import Path
import pdfplumber


class PdfExtractError(Exception):
    pass


def extract_text(path: Path) -> str:
    """텍스트층 합치기 (페이지 구분 \\n으로)."""
    p = Path(path)
    if not p.exists():
        raise PdfExtractError(f"file not found: {p}")
    try:
        with pdfplumber.open(p) as pdf:
            pages = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
            return "\n".join(pages)
    except Exception as e:
        raise PdfExtractError(f"pdfplumber failed on {p}: {e}") from e
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_pdf_extractor.py -v` → 3 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/ CC_SAMPLING_TOOL_V2/tests/integration/test_pdf_extractor.py CC_SAMPLING_TOOL_V2/requirements.txt
git -C c:/Claude commit -m "feat(infra): pdf text extractor (pdfplumber)"
```

---

### Task 5: PDF 금액 추출 (regex)

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/amount_extractor.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_amount_extractor.py`

회신서 텍스트에서 거래처명+금액 추출. 한국 회신서 양식 다양 — heuristic 사용.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_amount_extractor.py`:

```python
import pytest
from src.infrastructure.pdf.amount_extractor import (
    extract_party_amount, ExtractionResult,
)


def test_extract_simple_korean_format():
    text = """
    조회처: 고객사001
    잔액: 1,500,000원
    """
    r = extract_party_amount(text, candidate_parties=["고객사001", "고객사002"])
    assert r.matched_party == "고객사001"
    assert r.amount == 1_500_000


def test_extract_with_currency_suffix():
    text = "갑상사 잔액 ₩2,500,000"
    r = extract_party_amount(text, candidate_parties=["갑상사"])
    assert r.amount == 2_500_000


def test_extract_no_match_returns_none():
    text = "전혀 관련 없는 텍스트"
    r = extract_party_amount(text, candidate_parties=["갑상사"])
    assert r.matched_party is None
    assert r.amount is None


def test_extract_negative_balance():
    text = "공급사001 잔액 -500,000원"
    r = extract_party_amount(text, candidate_parties=["공급사001"])
    assert r.amount == -500_000


def test_extract_amount_without_comma():
    text = "고객사002 잔액 5000000"
    r = extract_party_amount(text, candidate_parties=["고객사002"])
    assert r.amount == 5_000_000


def test_extract_picks_largest_when_multiple():
    """텍스트에 숫자 여러 개 있을 때 가장 큰 값 채택."""
    text = "고객사001 거래일 2025-12-31 잔액 3,500,000원 (참고 1,000)"
    r = extract_party_amount(text, candidate_parties=["고객사001"])
    assert r.amount == 3_500_000
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_amount_extractor.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/infrastructure/pdf/amount_extractor.py`:

```python
"""PDF 텍스트 → 거래처/금액 추출 (heuristic).

설계서 §6.1 [5]. 한국 회신서 양식 다양 — 거래처 후보 list와 매칭.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExtractionResult:
    matched_party: Optional[str]
    amount: Optional[float]
    confidence: float = 0.0


_AMOUNT_RE = re.compile(r"[-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-]?\d+(?:\.\d+)?")


def extract_party_amount(
    text: str,
    candidate_parties: list[str],
) -> ExtractionResult:
    """텍스트에서 거래처명·금액 추출.

    전략:
    1. candidate_parties 중 텍스트에 등장한 첫 번째 거래처 선택
    2. 텍스트 내 가장 큰 |금액| 채택 (회신서는 잔액이 보통 최대 숫자)
    """
    matched = None
    for p in candidate_parties:
        if p in text:
            matched = p
            break

    amounts = []
    for m in _AMOUNT_RE.finditer(text):
        s = m.group(0).replace(",", "")
        try:
            amounts.append(float(s))
        except ValueError:
            continue

    if not amounts:
        return ExtractionResult(matched_party=matched, amount=None,
                                confidence=0.0)
    # 가장 절대값 큰 숫자
    best = max(amounts, key=abs)
    conf = 0.0
    if matched is not None:
        conf = 0.9 if abs(best) >= 1000 else 0.5
    return ExtractionResult(matched_party=matched, amount=best, confidence=conf)
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_amount_extractor.py -v` → 6 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/amount_extractor.py CC_SAMPLING_TOOL_V2/tests/integration/test_amount_extractor.py
git -C c:/Claude commit -m "feat(infra): pdf amount/party extractor (regex heuristic)"
```

---

### Task 6: 발송명단 Excel writer

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/__init__.py` (빈)
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/styles.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/sendlist.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_excel_sendlist.py`

설계 §6.1 [4]. 표본별 발송명단 Excel — kind/party_id/name/잔액/선정사유 컬럼.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_excel_sendlist.py`:

```python
import pytest
import io
import openpyxl
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.excel_writer.sendlist import build_sendlist


def _acc(pid, name, balance):
    return Account(party_id=pid, name=name, gl_account="11200",
                   balance_orig=balance, ccy="KRW", fx_rate=1.0,
                   balance_krw=balance)


def test_sendlist_builds_xlsx_bytes():
    selections = [
        (_acc("AR001", "고객사001", 1_000_000), SelectionReason.FORCED_RP),
        (_acc("AR002", "고객사002", 5_000_000), SelectionReason.FORCED_KEY),
    ]
    samples = {Kind.AR: selections, Kind.AP: []}
    blob = build_sendlist(client_name="ACME", period_end="2025-12-31",
                          samples=samples)
    assert isinstance(blob, (bytes, bytearray))
    assert len(blob) > 0

    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "발송명단" in wb.sheetnames


def test_sendlist_rows_present():
    selections = [
        (_acc("AR001", "고객사001", 1_000_000), SelectionReason.FORCED_RP),
    ]
    blob = build_sendlist(client_name="X", period_end="2025-12-31",
                          samples={Kind.AR: selections, Kind.AP: []})
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["발송명단"]
    # header + 1 row
    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) >= 2
    headers = rows[0]
    assert "거래처코드" in headers
    assert "거래처명" in headers


def test_sendlist_merges_ar_ap():
    ar = [(_acc("AR1", "ar", 100), SelectionReason.REP)]
    ap = [(_acc("AP1", "ap", 200), SelectionReason.REP)]
    blob = build_sendlist(client_name="X", period_end="2025-12-31",
                          samples={Kind.AR: ar, Kind.AP: ap})
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["발송명단"]
    rows = list(ws.iter_rows(values_only=True))[1:]
    party_ids = [r[1] for r in rows]
    assert "AR1" in party_ids and "AP1" in party_ids
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_excel_sendlist.py -v` → ImportError.

- [ ] **Step 3: styles.py**

`src/infrastructure/excel_writer/styles.py`:

```python
"""Excel 서식 토큰 — Phase 4까지 재사용."""
from __future__ import annotations
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


HEADER_FILL = PatternFill("solid", fgColor="1E3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_ALIGN = Alignment(horizontal="center", vertical="center")

BODY_FONT = Font(size=10)
NUM_ALIGN = Alignment(horizontal="right")
TEXT_ALIGN = Alignment(horizontal="left")

_thin = Side(style="thin", color="C0C0C0")
CELL_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
```

- [ ] **Step 4: sendlist.py**

`src/infrastructure/excel_writer/sendlist.py`:

```python
"""발송명단 Excel 생성."""
from __future__ import annotations
import io
from typing import Mapping
import openpyxl
from src.domain.entities import Account, Kind, SelectionReason
from src.infrastructure.excel_writer.styles import (
    HEADER_FILL, HEADER_FONT, HEADER_ALIGN,
    BODY_FONT, NUM_ALIGN, TEXT_ALIGN, CELL_BORDER,
)


COLUMNS = [
    ("종류", 8, "text"),
    ("거래처코드", 16, "text"),
    ("거래처명", 30, "text"),
    ("계정과목", 12, "text"),
    ("기말잔액(KRW)", 18, "num"),
    ("통화", 8, "text"),
    ("선정사유", 14, "text"),
]


def build_sendlist(
    client_name: str,
    period_end: str,
    samples: Mapping[Kind, list[tuple[Account, SelectionReason]]],
) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("발송명단")

    # 헤더 메타
    ws.append([f"회사명: {client_name}", f"평가기준일: {period_end}"])
    ws.append([])
    header_row_idx = 3

    # 헤더
    headers = [c[0] for c in COLUMNS]
    ws.append(headers)
    for col, (_, width, _) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row_idx, column=col)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
        ws.column_dimensions[cell.column_letter].width = width

    # 바디
    for kind in (Kind.AR, Kind.AP):
        for acc, reason in samples.get(kind, []):
            row = [
                kind.value, acc.party_id, acc.name, acc.gl_account,
                acc.balance_krw, acc.ccy, reason.value,
            ]
            ws.append(row)
            r_idx = ws.max_row
            for c_idx, (_, _, kind_t) in enumerate(COLUMNS, start=1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.font = BODY_FONT
                cell.alignment = NUM_ALIGN if kind_t == "num" else TEXT_ALIGN
                cell.border = CELL_BORDER
                if kind_t == "num":
                    cell.number_format = "#,##0"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_excel_sendlist.py -v` → 3 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/ CC_SAMPLING_TOOL_V2/tests/integration/test_excel_sendlist.py
git -C c:/Claude commit -m "feat(infra): excel sendlist writer (header styling + AR/AP merge)"
```

---

### Task 7: send_list_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/send_list_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_sendlist_uc.py`

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_sendlist_uc.py`:

```python
import pytest
import io
import openpyxl
from datetime import date
from src.application.send_list_uc import SendListUC
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


def test_sendlist_uc_builds_xlsx(session):
    pid = ProjectRepo(session).create(
        client="ACME", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    acc = Account(party_id="P1", name="갑", gl_account="11200",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs[0], SelectionReason.FORCED_RP)])

    uc = SendListUC(session)
    blob = uc.build(pid)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    rows = list(wb["발송명단"].iter_rows(values_only=True))
    body = [r for r in rows if r and r[0] in ("AR", "AP")]
    assert len(body) == 1
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_sendlist_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/send_list_uc.py`:

```python
"""SendListUC — 표본 → 발송명단 Excel."""
from __future__ import annotations
from src.domain.entities import Kind
from src.infrastructure.db.repository import ProjectRepo, SampleRepo
from src.infrastructure.excel_writer.sendlist import build_sendlist


class SendListUC:
    def __init__(self, session):
        self.s = session

    def build(self, project_id: int) -> bytes:
        proj = ProjectRepo(self.s).get(project_id)
        sample_repo = SampleRepo(self.s)
        samples = {
            Kind.AR: sample_repo.list_by_project_kind(project_id, Kind.AR),
            Kind.AP: sample_repo.list_by_project_kind(project_id, Kind.AP),
        }
        return build_sendlist(
            client_name=proj.client,
            period_end=proj.period_end.isoformat(),
            samples=samples,
        )
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_sendlist_uc.py -v` → 1 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/send_list_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_sendlist_uc.py
git -C c:/Claude commit -m "feat(application): send_list_uc (sample → xlsx bytes)"
```

---

### Task 8: match_response_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/match_response_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_match_response_uc.py`

PDF 한 건 → 추출 → judge_response (Phase 1 domain.matching) → ConfirmationRepo.upsert.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_match_response_uc.py`:

```python
import pytest
from pathlib import Path
from datetime import date
from src.application.match_response_uc import MatchResponseUC, MatchResult
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)


def _make_pdf(path, text):
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    c = canvas.Canvas(str(path))
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_sample(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="고객사001", gl_account="11200",
                  balance_orig=1_500_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_500_000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(
        pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    return pid


def test_match_response_persists_confirmation(session, project_with_sample, tmp_path):
    pdf = tmp_path / "conf.pdf"
    _make_pdf(pdf, "조회처: 고객사001\n잔액: 1,500,000원")
    uc = MatchResponseUC(session)
    result = uc.match_one(pid=project_with_sample, kind=Kind.AR, pdf_path=pdf)
    assert isinstance(result, MatchResult)
    assert result.matched_party == "고객사001"
    assert result.confirmed == 1_500_000
    assert result.verdict == Verdict.MATCH

    rows = ConfirmationRepo(session).list_by_project_kind(
        project_with_sample, Kind.AR)
    assert len(rows) == 1
    assert rows[0].verdict == Verdict.MATCH


def test_match_response_discrepancy(session, project_with_sample, tmp_path):
    pdf = tmp_path / "conf.pdf"
    _make_pdf(pdf, "조회처: 고객사001\n잔액: 1,100,000원")
    uc = MatchResponseUC(session)
    r = uc.match_one(project_with_sample, Kind.AR, pdf)
    assert r.verdict == Verdict.DISCREPANCY


def test_match_response_extract_failure(session, project_with_sample, tmp_path):
    pdf = tmp_path / "blank.pdf"
    _make_pdf(pdf, "")
    uc = MatchResponseUC(session)
    r = uc.match_one(project_with_sample, Kind.AR, pdf)
    assert r.confirmed is None
    assert r.verdict == Verdict.NO_RESPONSE
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_match_response_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/match_response_uc.py`:

```python
"""MatchResponseUC — PDF 1건 → 추출 + judge + persist."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from src.domain.entities import Kind, Verdict, ResponseStatus
from src.domain.matching import judge_response
from src.infrastructure.db.repository import (
    AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.infrastructure.pdf.extractor import extract_text, PdfExtractError
from src.infrastructure.pdf.amount_extractor import extract_party_amount


@dataclass
class MatchResult:
    matched_party: Optional[str]
    confirmed: Optional[float]
    verdict: Verdict
    extraction_confidence: float


class MatchResponseUC:
    def __init__(self, session):
        self.s = session

    def match_one(
        self, pid: int, kind: Kind, pdf_path: Path,
        diff_reason: Optional[str] = None,
    ) -> MatchResult:
        sample = SampleRepo(self.s).list_by_project_kind(pid, kind)
        candidates = [acc.name for acc, _ in sample]
        by_name = {acc.name: acc for acc, _ in sample}

        # 1) PDF 텍스트 추출
        try:
            text = extract_text(pdf_path)
        except PdfExtractError:
            text = ""

        # 2) 거래처/금액 추출
        extr = extract_party_amount(text, candidate_parties=candidates)

        # 3) 매칭 sample 찾기
        acc = by_name.get(extr.matched_party) if extr.matched_party else None
        if acc is None:
            return MatchResult(
                matched_party=None, confirmed=None,
                verdict=Verdict.NO_RESPONSE,
                extraction_confidence=0.0,
            )

        # 4) judge + persist
        verdict = judge_response(
            expected=acc.balance_krw,
            confirmed=extr.amount, diff_reason=diff_reason,
        )
        status = (ResponseStatus.RECEIVED
                  if extr.amount is not None else ResponseStatus.NO_RESPONSE)
        ConfirmationRepo(self.s).upsert(
            pid, kind, party_id=acc.party_id,
            expected=acc.balance_krw, confirmed=extr.amount,
            verdict=verdict, diff_reason=diff_reason,
            pdf_path=str(pdf_path), status=status,
        )
        return MatchResult(
            matched_party=acc.party_id, confirmed=extr.amount,
            verdict=verdict, extraction_confidence=extr.confidence,
        )
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_match_response_uc.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/match_response_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_match_response_uc.py
git -C c:/Claude commit -m "feat(application): match_response_uc (PDF → extract → judge → persist)"
```

---

### Task 9: alternative_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/alternative_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_alternative_uc.py`

대체적 절차 등록 + 미회신 총액 대비 coverage 계산 + persist.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_alternative_uc.py`:

```python
import pytest
from datetime import date
from src.application.alternative_uc import AlternativeUC, AltProcResult
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo, AltProcRepo,
)


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_no_response(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    accs = [
        Account(party_id="P1", name="갑", gl_account="x",
                balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000),
        Account(party_id="P2", name="을", gl_account="x",
                balance_orig=2000, ccy="KRW", fx_rate=1.0, balance_krw=2000),
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR, [
        (accs_db[0], SelectionReason.FORCED_RP),
        (accs_db[1], SelectionReason.FORCED_RP),
    ])
    conf = ConfirmationRepo(session)
    conf.upsert(pid, Kind.AR, party_id="P1", expected=1000, confirmed=None,
                verdict=Verdict.NO_RESPONSE, diff_reason=None,
                pdf_path=None, status=ResponseStatus.NO_RESPONSE)
    conf.upsert(pid, Kind.AR, party_id="P2", expected=2000, confirmed=None,
                verdict=Verdict.NO_RESPONSE, diff_reason=None,
                pdf_path=None, status=ResponseStatus.NO_RESPONSE)
    return pid


def test_register_increments_coverage(session, project_with_no_response):
    pid = project_with_no_response
    uc = AlternativeUC(session)
    r = uc.register(pid, Kind.AR, party_id="P1",
                    procedure_type="후속회수", evidence_sum=1000)
    # 미회신 총액 = 3000, P1 1000 증빙 → coverage=1000/3000≈0.333
    assert r.coverage_pct == pytest.approx(0.333, abs=0.01)
    assert r.verdict == "INSUFFICIENT"


def test_register_accumulated_acceptable(session, project_with_no_response):
    pid = project_with_no_response
    uc = AlternativeUC(session)
    uc.register(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수", evidence_sum=1000)
    r = uc.register(pid, Kind.AR, party_id="P2",
                    procedure_type="송장대조", evidence_sum=2000)
    # 누적 3000 / 3000 = 1.0
    assert r.coverage_pct >= 0.75
    assert r.verdict == "ACCEPTABLE"


def test_register_updates_existing(session, project_with_no_response):
    pid = project_with_no_response
    uc = AlternativeUC(session)
    uc.register(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수", evidence_sum=500)
    uc.register(pid, Kind.AR, party_id="P1",
                procedure_type="후속회수", evidence_sum=900)
    rows = AltProcRepo(session).list_by_project_kind(pid, Kind.AR)
    assert len(rows) == 1
    assert rows[0]["evidence_sum"] == 900
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_alternative_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/alternative_uc.py`:

```python
"""AlternativeUC — 대체적 절차 등록 + coverage 산정 + persist."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from src.domain.entities import Kind, Verdict
from src.domain.alternative import coverage_verdict
from src.infrastructure.db.repository import (
    ConfirmationRepo, AltProcRepo,
)


@dataclass
class AltProcResult:
    coverage_pct: float
    verdict: str
    covered_amt: float
    non_response_total: float


class AlternativeUC:
    def __init__(self, session):
        self.s = session

    def register(
        self,
        project_id: int,
        kind: Kind,
        *,
        party_id: str,
        procedure_type: str,
        evidence_sum: float,
        note: Optional[str] = None,
    ) -> AltProcResult:
        # 1) 해당 항목 alt-proc upsert (coverage는 임시 0)
        AltProcRepo(self.s).upsert(
            project_id, kind, party_id=party_id,
            procedure_type=procedure_type, evidence_sum=evidence_sum,
            coverage_pct=0.0, note=note,
        )

        # 2) 미회신 잔액 합계 (NO_RESPONSE / status PENDING도 미회신 취급)
        confirmations = ConfirmationRepo(self.s).list_by_project_kind(
            project_id, kind)
        non_response_total = sum(
            abs(c.expected) for c in confirmations
            if c.verdict == Verdict.NO_RESPONSE
        )

        # 3) 전체 alt-proc evidence 합계
        all_procs = AltProcRepo(self.s).list_by_project_kind(project_id, kind)
        covered_amt = sum(p["evidence_sum"] for p in all_procs)

        # 4) coverage 산정
        pct, verdict = coverage_verdict(covered_amt, non_response_total)

        # 5) 방금 등록한 항목의 coverage_pct 갱신
        AltProcRepo(self.s).upsert(
            project_id, kind, party_id=party_id,
            procedure_type=procedure_type, evidence_sum=evidence_sum,
            coverage_pct=pct, note=note,
        )

        return AltProcResult(
            coverage_pct=pct, verdict=verdict,
            covered_amt=covered_amt, non_response_total=non_response_total,
        )
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_alternative_uc.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/alternative_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_alternative_uc.py
git -C c:/Claude commit -m "feat(application): alternative_uc (register + coverage upsert)"
```

---

### Task 10: projection_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/projection_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_projection_uc.py`

설계 §6.1 [7]. Confirmation 중 DISCREPANCY 항목의 misstatement를 모아 ISA 530 PPS projection (Phase 1 domain.projection.pps 활용). AR/AP 각 독립 계산. strata는 Phase 2 design에서 사용한 것 재계산 (단, current population 기준).

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_projection_uc.py`:

```python
import pytest
from datetime import date
from src.application.projection_uc import ProjectionUC, ProjectionView
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo, ProjectionRepo,
)


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


@pytest.fixture
def project_with_discrepancy(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    # 모집단 100건, 잔액 균등
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                balance_krw=100_000)
        for i in range(100)
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    # 표본 10건
    SampleRepo(session).persist(pid, Kind.AR, [
        (a, SelectionReason.REP) for a in accs_db[:10]
    ])
    # 표본 중 2건 차이 (DISCREPANCY)
    conf = ConfirmationRepo(session)
    for i in range(10):
        if i < 2:
            conf.upsert(pid, Kind.AR, party_id=f"P{i:03d}",
                        expected=100_000, confirmed=80_000,
                        verdict=Verdict.DISCREPANCY, diff_reason=None,
                        pdf_path=None, status=ResponseStatus.RECEIVED)
        else:
            conf.upsert(pid, Kind.AR, party_id=f"P{i:03d}",
                        expected=100_000, confirmed=100_000,
                        verdict=Verdict.MATCH, diff_reason=None,
                        pdf_path=None, status=ResponseStatus.RECEIVED)
    return pid


def test_projection_computes(session, project_with_discrepancy):
    pid = project_with_discrepancy
    uc = ProjectionUC(session)
    view = uc.compute(pid, kind=Kind.AR, confidence=0.95)
    assert view.kind == Kind.AR
    assert view.projected_misstatement > 0
    assert view.upper_limit >= view.projected_misstatement
    assert view.verdict in ("WITHIN_TOLERABLE", "EXCEED")


def test_projection_persists(session, project_with_discrepancy):
    pid = project_with_discrepancy
    uc = ProjectionUC(session)
    uc.compute(pid, Kind.AR, confidence=0.95)
    got = ProjectionRepo(session).get_latest(pid, Kind.AR)
    assert got is not None
    assert got["verdict"] in ("WITHIN_TOLERABLE", "EXCEED")


def test_projection_no_discrepancy_returns_basic_only(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    accs = [Account(party_id=f"P{i}", name=str(i), gl_account="x",
                    balance_orig=10_000, ccy="KRW", fx_rate=1.0,
                    balance_krw=10_000) for i in range(20)]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs_db[0], SelectionReason.REP)])
    conf = ConfirmationRepo(session)
    conf.upsert(pid, Kind.AR, party_id="P0", expected=10_000, confirmed=10_000,
                verdict=Verdict.MATCH, diff_reason=None,
                pdf_path=None, status=ResponseStatus.RECEIVED)
    uc = ProjectionUC(session)
    view = uc.compute(pid, Kind.AR, confidence=0.95)
    assert view.projected_misstatement == 0
    assert view.upper_limit > 0  # basic precision만 있어도 양수
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_projection_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/projection_uc.py`:

```python
"""ProjectionUC — Confirmation → ISA 530 PPS projection + persist.

설계서 §6.1 [7], §5.8. Phase 1 domain.projection.pps 활용.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from src.domain.entities import Kind, Verdict
from src.domain.projection.pps import project_misstatement
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo, ProjectionRepo,
)


@dataclass
class ProjectionView:
    kind: Kind
    projected_misstatement: float
    basic_precision: float
    incremental_allowance: float
    upper_limit: float
    tolerable: float
    verdict: str
    sample_size: int
    sampling_interval: float


class ProjectionUC:
    def __init__(self, session):
        self.s = session

    def compute(
        self,
        project_id: int,
        kind: Kind,
        confidence: float = 0.95,
    ) -> ProjectionView:
        proj = ProjectRepo(self.s).get(project_id)
        accounts = AccountRepo(self.s).list_by_project_kind(project_id, kind)
        sample = SampleRepo(self.s).list_by_project_kind(project_id, kind)
        confirmations = ConfirmationRepo(self.s).list_by_project_kind(
            project_id, kind)

        population_bv = sum(abs(a.balance_krw) for a in accounts)
        n = max(1, len(sample))
        sampling_interval = population_bv / n if n > 0 else 0.0

        # DISCREPANCY 항목만 misstatement 입력으로
        ms_inputs: list[tuple[float, float]] = []
        for c in confirmations:
            if c.verdict == Verdict.DISCREPANCY and c.diff is not None:
                # ms = expected - confirmed (절대값으로 보수적 처리)
                ms = abs(c.expected - (c.confirmed or 0))
                ms_inputs.append((ms, abs(c.expected)))

        result = project_misstatement(
            kind=kind,
            confidence=confidence,
            sampling_interval=sampling_interval,
            tolerable=proj.tolerable,
            sampled_misstatements=ms_inputs,
        )

        # persist (strata snapshot — 현재는 단일 strata로 단순화; Phase 4에서 design strata 재호출)
        ProjectionRepo(self.s).upsert(
            project_id, kind, confidence=confidence,
            sampling_interval=sampling_interval,
            tolerable=proj.tolerable,
            projected_misstatement=result.projected_misstatement,
            basic_precision=result.basic_precision,
            incremental_allowance=result.incremental_allowance,
            upper_limit=result.upper_limit,
            verdict=result.verdict,
            strata_snapshot=[{"low": 0.0,
                              "high": max((abs(a.balance_krw) for a in accounts),
                                          default=0.0),
                              "n_required": n}],
        )

        return ProjectionView(
            kind=kind,
            projected_misstatement=result.projected_misstatement,
            basic_precision=result.basic_precision,
            incremental_allowance=result.incremental_allowance,
            upper_limit=result.upper_limit,
            tolerable=proj.tolerable,
            verdict=result.verdict,
            sample_size=n,
            sampling_interval=sampling_interval,
        )
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_projection_uc.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/projection_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_projection_uc.py
git -C c:/Claude commit -m "feat(application): projection_uc (ISA 530 PPS + persist with snapshot)"
```

---

### Task 11: API route — confirmations

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/confirmations.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/app.py` (register)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_confirmations_route.py`

3개 엔드포인트:
- `GET /api/projects/{pid}/sendlist` — 발송명단 Excel download
- `POST /api/projects/{pid}/confirmations/upload` — PDF 1개 업로드
- (state route에서 list는 노출됨)

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_confirmations_route.py`:

```python
import pytest
import io
from pathlib import Path
import openpyxl
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
)
from src.domain.entities import Account, Kind, SelectionReason


def _make_pdf_bytes(text):
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()
    return buf.getvalue()


@pytest.fixture
def client_with_sample():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="고객사001", gl_account="11200",
                  balance_orig=1_500_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_500_000)
    AccountRepo(s).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR, [(accs[0], SelectionReason.FORCED_RP)])
    s.close()
    return app.test_client(), pid


def test_sendlist_download(client_with_sample):
    c, pid = client_with_sample
    r = c.get(f"/api/projects/{pid}/sendlist")
    assert r.status_code == 200
    assert r.content_type.startswith("application/vnd.openxmlformats-officedocument")
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert "발송명단" in wb.sheetnames


def test_upload_confirmation_pdf(client_with_sample):
    c, pid = client_with_sample
    pdf_bytes = _make_pdf_bytes("조회처: 고객사001\n잔액: 1,500,000원")
    r = c.post(f"/api/projects/{pid}/confirmations/upload",
               data={"kind": "AR",
                     "pdf": (io.BytesIO(pdf_bytes), "conf.pdf")},
               content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["matched_party"] == "P1"
    assert body["verdict"] == "MATCH"


def test_upload_without_pdf_returns_400(client_with_sample):
    c, pid = client_with_sample
    r = c.post(f"/api/projects/{pid}/confirmations/upload",
               data={"kind": "AR"},
               content_type="multipart/form-data")
    assert r.status_code == 400
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_confirmations_route.py -v` → ImportError or 404.

- [ ] **Step 3: 구현**

`api/routes/confirmations.py`:

```python
"""Confirmations routes — sendlist download + PDF upload."""
from __future__ import annotations
import io
import tempfile
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file, g
from src.domain.entities import Kind
from src.application.send_list_uc import SendListUC
from src.application.match_response_uc import MatchResponseUC


bp = Blueprint("confirmations", __name__, url_prefix="/api/projects")


@bp.get("/<int:pid>/sendlist")
def download_sendlist(pid: int):
    try:
        blob = SendListUC(g.session).build(pid)
    except KeyError:
        return jsonify({"error": "project not found"}), 404
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"sendlist_{pid}.xlsx",
    )


@bp.post("/<int:pid>/confirmations/upload")
def upload_confirmation(pid: int):
    if "pdf" not in request.files:
        return jsonify({"error": "pdf file required"}), 400
    kind_str = request.form.get("kind", "AR")
    try:
        kind = Kind(kind_str)
    except ValueError:
        return jsonify({"error": "kind must be AR or AP"}), 400
    diff_reason = request.form.get("diff_reason") or None

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        pdf_path = Path(td) / "conf.pdf"
        request.files["pdf"].save(pdf_path)
        uc = MatchResponseUC(g.session)
        result = uc.match_one(pid, kind, pdf_path, diff_reason=diff_reason)
    return jsonify({
        "matched_party": result.matched_party,
        "confirmed": result.confirmed,
        "verdict": result.verdict.value if result.verdict else None,
        "extraction_confidence": result.extraction_confidence,
    })
```

- [ ] **Step 4: app.py 등록**

기존 blueprint 등록 블록에 추가:

```python
    from api.routes.confirmations import bp as confirmations_bp
    app.register_blueprint(confirmations_bp)
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_confirmations_route.py -v` → 3 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_confirmations_route.py
git -C c:/Claude commit -m "feat(api): confirmations route (sendlist download + PDF upload)"
```

---

### Task 12: API route — alternative

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/alternative.py`
- Modify: `api/app.py` (register)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_alternative_route.py`

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_alternative_route.py`:

```python
import pytest
import io
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)


@pytest.fixture
def client_setup():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(s).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR,
                          [(accs[0], SelectionReason.FORCED_RP)])
    ConfirmationRepo(s).upsert(
        pid, Kind.AR, party_id="P1", expected=1000, confirmed=None,
        verdict=Verdict.NO_RESPONSE, diff_reason=None,
        pdf_path=None, status=ResponseStatus.NO_RESPONSE)
    s.close()
    return app.test_client(), pid


def test_register_alternative(client_setup):
    c, pid = client_setup
    r = c.post(f"/api/projects/{pid}/alternative", json={
        "kind": "AR", "party_id": "P1",
        "procedure_type": "후속회수", "evidence_sum": 1000,
        "note": "회수증빙 확인",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["coverage_pct"] >= 0.75


def test_register_invalid_kind(client_setup):
    c, pid = client_setup
    r = c.post(f"/api/projects/{pid}/alternative", json={
        "kind": "INVALID", "party_id": "P1",
        "procedure_type": "X", "evidence_sum": 100,
    })
    assert r.status_code == 400
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_alternative_route.py -v` → ImportError or 404.

- [ ] **Step 3: api/routes/alternative.py**

```python
"""Alternative procedure route."""
from __future__ import annotations
from flask import Blueprint, request, jsonify, g
from src.domain.entities import Kind
from src.application.alternative_uc import AlternativeUC


bp = Blueprint("alternative", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/alternative")
def register_alternative(pid: int):
    data = request.get_json(force=True)
    try:
        kind = Kind(data["kind"])
    except (KeyError, ValueError):
        return jsonify({"error": "kind must be AR or AP"}), 400
    try:
        r = AlternativeUC(g.session).register(
            pid, kind,
            party_id=data["party_id"],
            procedure_type=data.get("procedure_type", "기타"),
            evidence_sum=float(data.get("evidence_sum", 0)),
            note=data.get("note"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "coverage_pct": r.coverage_pct,
        "verdict": r.verdict,
        "covered_amt": r.covered_amt,
        "non_response_total": r.non_response_total,
    })
```

- [ ] **Step 4: app.py 등록**

```python
    from api.routes.alternative import bp as alternative_bp
    app.register_blueprint(alternative_bp)
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_alternative_route.py -v` → 2 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_alternative_route.py
git -C c:/Claude commit -m "feat(api): alternative procedure route (POST register + coverage)"
```

---

### Task 13: API route — projection + state 확장

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/projection.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/state.py` (confirmations/alternatives/projection 합산 노출)
- Modify: `api/app.py` (register projection)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_projection_route.py`

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_projection_route.py`:

```python
import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.domain.entities import (
    Account, Kind, SelectionReason, Verdict, ResponseStatus,
)


@pytest.fixture
def client_with_discrepancy():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1_000_000, tolerable=500_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                balance_krw=100_000)
        for i in range(100)
    ]
    AccountRepo(s).bulk_insert(pid, Kind.AR, accs)
    accs_db = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR,
                          [(a, SelectionReason.REP) for a in accs_db[:10]])
    conf = ConfirmationRepo(s)
    conf.upsert(pid, Kind.AR, party_id="P000", expected=100_000,
                confirmed=80_000, verdict=Verdict.DISCREPANCY,
                diff_reason=None, pdf_path=None,
                status=ResponseStatus.RECEIVED)
    s.close()
    return app.test_client(), pid


def test_projection_compute(client_with_discrepancy):
    c, pid = client_with_discrepancy
    r = c.post(f"/api/projects/{pid}/projection", json={
        "kind": "AR", "confidence": 0.95,
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["projected_misstatement"] > 0
    assert body["upper_limit"] >= body["projected_misstatement"]
    assert body["verdict"] in ("WITHIN_TOLERABLE", "EXCEED")


def test_state_exposes_confirmations_and_projection(client_with_discrepancy):
    c, pid = client_with_discrepancy
    # projection compute 먼저
    c.post(f"/api/projects/{pid}/projection",
           json={"kind": "AR", "confidence": 0.95})
    r = c.get(f"/api/projects/{pid}/state")
    body = r.get_json()
    assert "confirmations" in body
    assert "alternatives" in body
    assert "projection" in body
    assert body["projection"]["AR"] is not None
    assert body["projection"]["AR"]["upper_limit"] > 0
    # confirmations에 DISCREPANCY 1건
    ar_confs = body["confirmations"]["AR"]
    assert any(c["verdict"] == "DISCREPANCY" for c in ar_confs)
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_projection_route.py -v` → ImportError or 404.

- [ ] **Step 3: api/routes/projection.py**

```python
"""Projection compute route."""
from __future__ import annotations
from flask import Blueprint, request, jsonify, g
from src.domain.entities import Kind
from src.application.projection_uc import ProjectionUC


bp = Blueprint("projection", __name__, url_prefix="/api/projects")


@bp.post("/<int:pid>/projection")
def compute_projection(pid: int):
    data = request.get_json(force=True) if request.is_json else {}
    try:
        kind = Kind(data.get("kind", "AR"))
    except ValueError:
        return jsonify({"error": "kind must be AR or AP"}), 400
    confidence = float(data.get("confidence", 0.95))
    try:
        view = ProjectionUC(g.session).compute(pid, kind, confidence)
    except KeyError:
        return jsonify({"error": "project not found"}), 404
    return jsonify({
        "kind": view.kind.value,
        "projected_misstatement": view.projected_misstatement,
        "basic_precision": view.basic_precision,
        "incremental_allowance": view.incremental_allowance,
        "upper_limit": view.upper_limit,
        "tolerable": view.tolerable,
        "verdict": view.verdict,
        "sample_size": view.sample_size,
        "sampling_interval": view.sampling_interval,
    })
```

- [ ] **Step 4: state.py 확장**

Read `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/state.py`. 전체 교체:

```python
"""Dashboard state — 좌측패널·테이블에 필요한 모든 정보 한방."""
from __future__ import annotations
from flask import Blueprint, jsonify, g
from src.domain.entities import Kind
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
    ConfirmationRepo, AltProcRepo, ProjectionRepo,
)


bp = Blueprint("state", __name__, url_prefix="/api/projects")


@bp.get("/<int:pid>/state")
def project_state(pid: int):
    proj_repo = ProjectRepo(g.session)
    acc_repo = AccountRepo(g.session)
    sample_repo = SampleRepo(g.session)
    conf_repo = ConfirmationRepo(g.session)
    alt_repo = AltProcRepo(g.session)
    proj_repo_e = ProjectionRepo(g.session)
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
        "populations": {}, "samples": {},
        "confirmations": {}, "alternatives": {}, "projection": {},
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
                    "party_id": a.party_id, "name": a.name,
                    "gl_account": a.gl_account,
                    "balance_krw": a.balance_krw, "ccy": a.ccy,
                    "selection_reason": r.value,
                    "is_related_party": a.is_related_party,
                    "is_bad_debt": a.is_bad_debt,
                }
                for a, r in sample
            ],
        }
        confs = conf_repo.list_by_project_kind(pid, k)
        out["confirmations"][k.value] = [
            {
                "party_id": c.party_id, "name": c.name,
                "expected": c.expected, "confirmed": c.confirmed,
                "diff": c.diff, "diff_reason": c.diff_reason,
                "verdict": c.verdict.value if c.verdict else None,
                "status": c.status.value,
                "pdf_path": c.pdf_path,
            }
            for c in confs
        ]
        out["alternatives"][k.value] = alt_repo.list_by_project_kind(pid, k)
        out["projection"][k.value] = proj_repo_e.get_latest(pid, k)
    return jsonify(out)
```

- [ ] **Step 5: app.py 등록**

```python
    from api.routes.projection import bp as projection_bp
    app.register_blueprint(projection_bp)
```

- [ ] **Step 6: 통과 확인**

`python -m pytest tests/integration/test_projection_route.py -v` → 2 passed.

전체 회귀: `python -m pytest tests/ -q` → 165+ passed.

- [ ] **Step 7: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_projection_route.py
git -C c:/Claude commit -m "feat(api): projection route + state expanded (confirmations/alternatives/projection)"
```

---

### Task 14: Frontend ④ 발송·회신 트래커

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` (append ④ section)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js` (add handlers)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css` (verdict tokens)

- [ ] **Step 1: index.html에 ④ 섹션 추가**

`c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` — `<section id="sampleTable">` 닫는 `</section>` 바로 다음에 삽입:

```html
    <!-- ④ 발송·회신 트래커 -->
    <section id="confirmationsPanel">
      <h2>④ 발송·회신 트래커</h2>
      <div class="actions">
        <a id="downloadSendlist" class="btn-link" href="#">발송명단 다운로드</a>
        <label class="upload-label">
          PDF 회신 업로드
          <input type="file" id="file-confirmation" accept=".pdf" multiple>
        </label>
        <select id="uploadKind"><option value="AR">AR</option><option value="AP">AP</option></select>
        <button id="uploadConfBtn">업로드·자동매칭</button>
      </div>
      <div id="confResult"></div>
      <table id="confirmationsTable">
        <thead>
          <tr>
            <th>종류</th><th>거래처</th><th>장부잔액</th><th>회신금액</th>
            <th>차이</th><th>판정</th><th>상태</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
```

- [ ] **Step 2: styles.css에 verdict 토큰 추가**

`c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css` 끝에 append:

```css
.verdict-tag {
  display: inline-block; padding: 1px 6px; border-radius: 10px;
  font-size: .7rem; font-weight: 600;
}
.verdict-tag.MATCH { background: #d1fae5; color: #047857; }
.verdict-tag.RECONCILED { background: #fef3c7; color: #b45309; }
.verdict-tag.DISCREPANCY { background: #fee2e2; color: #b91c1c; }
.verdict-tag.NO_RESPONSE { background: #f3f4f6; color: var(--color-muted); }

.btn-link {
  display: inline-block; padding: .35rem .75rem;
  background: var(--color-bg); color: var(--color-primary);
  border-radius: var(--radius); text-decoration: none;
  border: 1px solid var(--color-border);
}
.btn-link:hover { background: #eef2f7; }
.upload-label { padding: .35rem .75rem; border: 1px dashed var(--color-border);
                border-radius: var(--radius); font-size: .85rem;
                display: inline-flex; gap: .25rem; align-items: center; }
.upload-label input { font-size: .75rem; }
.actions { display: flex; gap: .5rem; align-items: center;
           margin-bottom: 1rem; flex-wrap: wrap; }
```

- [ ] **Step 3: app.js에 함수 추가**

`c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`의 `async function init()` **앞에** 추가:

```javascript
// ---- ④ Confirmations ----
function downloadSendlist(ev) {
  ev.preventDefault();
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  window.location.href = `${API}/projects/${currentProjectId}/sendlist`;
}

async function uploadConfirmations() {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const files = $("#file-confirmation").files;
  if (!files.length) { alert("PDF 1개 이상 선택"); return; }
  const kind = $("#uploadKind").value;
  const results = [];
  $("#confResult").textContent = "업로드 중...";
  for (const f of files) {
    const fd = new FormData();
    fd.append("pdf", f);
    fd.append("kind", kind);
    try {
      const r = await api("POST",
        `/projects/${currentProjectId}/confirmations/upload`, fd, true);
      results.push(`${f.name} → ${r.matched_party || "매칭실패"} (${r.verdict})`);
    } catch (e) {
      results.push(`${f.name} → 오류 ${e.message}`);
    }
  }
  $("#confResult").innerHTML = results.map(l => `<div>${l}</div>`).join("");
  await refreshState();
}

function renderConfirmationsTable() {
  const tbody = $("#confirmationsTable tbody");
  tbody.innerHTML = "";
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const c of (currentState.confirmations || {})[k] || []) {
      rows.push({ ...c, kind: k });
    }
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--color-muted);padding:2rem;">회신 없음 — PDF 업로드 필요</td></tr>`;
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");
    const diffStr = r.diff == null ? "—" : fmt(r.diff);
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.name} (${r.party_id})</td>
      <td class="num">${fmt(r.expected)}</td>
      <td class="num">${fmt(r.confirmed)}</td>
      <td class="num">${diffStr}</td>
      <td><span class="verdict-tag ${r.verdict || "NO_RESPONSE"}">${r.verdict || "—"}</span></td>
      <td>${r.status}</td>
    `;
    tbody.appendChild(tr);
  }
}
```

또한 `refreshState()` 안에서 `renderMergedTable()` 다음 줄에 `renderConfirmationsTable();` 추가.

`init()` 안에 listener 추가:

```javascript
  $("#downloadSendlist").addEventListener("click", downloadSendlist);
  $("#uploadConfBtn").addEventListener("click", uploadConfirmations);
```

또한 진행도 패널 갱신 (renderSidePanel 안 `setStep` 호출 부분에 추가):

```javascript
  const arRecv = (s.confirmations?.AR || []).filter(c => c.verdict).length;
  const apRecv = (s.confirmations?.AP || []).filter(c => c.verdict).length;
  setStep("send", s.samples.AR.count + s.samples.AP.count > 0 ? "done" : null);
  setStep("receive", (arRecv + apRecv) > 0 ? "done" : null);
```

기존 setStep("send", ...) 라인 교체.

- [ ] **Step 4: 수동 확인**

서버 띄워서 ④ 섹션 보임 확인 (자동 테스트 없음).

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/
git -C c:/Claude commit -m "feat(frontend): ④ confirmation tracker (sendlist download + PDF upload + table)"
```

---

### Task 15: Frontend ⑤ 대체적 절차

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`

- [ ] **Step 1: index.html — ④ 다음에 ⑤ 추가**

`<section id="confirmationsPanel">` 닫는 `</section>` 바로 다음에:

```html
    <!-- ⑤ 대체적 절차 -->
    <section id="alternativePanel">
      <h2>⑤ 대체적 절차</h2>
      <div class="actions">
        <input type="text" id="altPartyId" placeholder="거래처코드" style="width:120px;padding:.3rem;">
        <select id="altKind"><option value="AR">AR</option><option value="AP">AP</option></select>
        <select id="altType">
          <option>후속회수</option><option>송장대조</option><option>지급내역대조</option><option>기타</option>
        </select>
        <input type="number" id="altEvidence" placeholder="증빙금액" style="width:140px;padding:.3rem;">
        <input type="text" id="altNote" placeholder="비고" style="width:200px;padding:.3rem;">
        <button id="altRegisterBtn">등록</button>
      </div>
      <div id="altResult"></div>
      <table id="alternativesTable">
        <thead>
          <tr>
            <th>종류</th><th>거래처</th><th>절차유형</th>
            <th>증빙금액</th><th>비고</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
```

- [ ] **Step 2: app.js — alt 핸들러 + 렌더링**

`async function init()` 앞에 추가:

```javascript
// ---- ⑤ Alternative ----
async function registerAlternative() {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const partyId = $("#altPartyId").value.trim();
  if (!partyId) { alert("거래처코드 필수"); return; }
  const body = {
    kind: $("#altKind").value,
    party_id: partyId,
    procedure_type: $("#altType").value,
    evidence_sum: parseFloat($("#altEvidence").value || "0"),
    note: $("#altNote").value || null,
  };
  $("#altResult").textContent = "등록 중...";
  try {
    const r = await api("POST", `/projects/${currentProjectId}/alternative`, body);
    $("#altResult").innerHTML = `coverage ${pct(r.coverage_pct)} (${r.verdict}) · 누적증빙 ₩${fmt(r.covered_amt)}/${fmt(r.non_response_total)}`;
    await refreshState();
  } catch (e) {
    $("#altResult").textContent = "오류: " + e.message;
  }
}

function renderAlternativesTable() {
  const tbody = $("#alternativesTable tbody");
  tbody.innerHTML = "";
  const rows = [];
  for (const k of ["AR", "AP"]) {
    for (const a of (currentState.alternatives || {})[k] || []) {
      rows.push({ ...a, kind: k });
    }
  }
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--color-muted);padding:1.5rem;">대체적 절차 없음</td></tr>`;
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="kind-tag ${r.kind}">${r.kind}</span></td>
      <td>${r.name} (${r.party_id})</td>
      <td>${r.procedure_type}</td>
      <td class="num">${fmt(r.evidence_sum)}</td>
      <td>${r.note || "—"}</td>
    `;
    tbody.appendChild(tr);
  }
}
```

`refreshState()` 안 — `renderConfirmationsTable();` 다음 줄에:

```javascript
  renderAlternativesTable();
```

`init()` 안 — listener 추가:

```javascript
  $("#altRegisterBtn").addEventListener("click", registerAlternative);
```

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/
git -C c:/Claude commit -m "feat(frontend): ⑤ alternative procedure (register form + table)"
```

---

### Task 16: Frontend ⑥ Projection

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css`

- [ ] **Step 1: index.html — ⑤ 다음에 ⑥ 추가**

`<section id="alternativePanel">` 닫는 `</section>` 바로 다음에:

```html
    <!-- ⑥ Projection -->
    <section id="projectionPanel">
      <h2>⑥ Projection 결과 (ISA 530 PPS)</h2>
      <div class="actions">
        <select id="projConfidence">
          <option value="0.95">95%</option><option value="0.90">90%</option><option value="0.99">99%</option>
        </select>
        <button class="runProjection" data-kind="AR">AR 계산</button>
        <button class="runProjection" data-kind="AP">AP 계산</button>
      </div>
      <div id="projectionView">
        <div class="proj-card" data-kind="AR">
          <h3>채권 (AR)</h3>
          <div class="proj-content">—</div>
        </div>
        <div class="proj-card" data-kind="AP">
          <h3>채무 (AP)</h3>
          <div class="proj-content">—</div>
        </div>
        <div class="proj-card combined">
          <h3>합산</h3>
          <div class="proj-content" id="projectionCombined">—</div>
        </div>
      </div>
    </section>
```

- [ ] **Step 2: styles.css — projection 카드 스타일**

끝에 append:

```css
#projectionView { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }
.proj-card {
  background: var(--color-bg); padding: 1rem; border-radius: var(--radius);
  border: 1px solid var(--color-border);
}
.proj-card[data-kind="AR"] { border-top: 3px solid var(--color-ar); }
.proj-card[data-kind="AP"] { border-top: 3px solid var(--color-ap); }
.proj-card.combined { border-top: 3px solid var(--color-primary); }
.proj-card h3 { margin: 0 0 .5rem; font-size: .95rem; }
.proj-card .row { display: flex; justify-content: space-between;
                   font-size: .85rem; padding: .15rem 0; }
.proj-card .label { color: var(--color-muted); }
.proj-card .value { font-weight: 600; font-variant-numeric: tabular-nums; }
.proj-verdict.WITHIN_TOLERABLE { color: var(--color-rp); }
.proj-verdict.EXCEED { color: var(--color-bad); font-weight: 700; }
```

- [ ] **Step 3: app.js — projection 핸들러 + 렌더링**

`async function init()` 앞에 추가:

```javascript
// ---- ⑥ Projection ----
async function runProjection(ev) {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  const kind = ev.target.dataset.kind;
  const confidence = parseFloat($("#projConfidence").value);
  try {
    await api("POST", `/projects/${currentProjectId}/projection`,
              { kind, confidence });
    await refreshState();
  } catch (e) {
    alert("오류: " + e.message);
  }
}

function renderProjection() {
  const st = currentState;
  if (!st) return;
  const drawCard = (kind) => {
    const p = (st.projection || {})[kind];
    const card = document.querySelector(`.proj-card[data-kind="${kind}"] .proj-content`);
    if (!p) { card.textContent = "— (계산 전)"; return; }
    card.innerHTML = `
      <div class="row"><span class="label">신뢰수준</span><span class="value">${(p.confidence*100).toFixed(0)}%</span></div>
      <div class="row"><span class="label">표본간격</span><span class="value">₩${fmt(p.sampling_interval)}</span></div>
      <div class="row"><span class="label">추정 misstatement</span><span class="value">₩${fmt(p.projected_misstatement)}</span></div>
      <div class="row"><span class="label">basic precision</span><span class="value">₩${fmt(p.basic_precision)}</span></div>
      <div class="row"><span class="label">incremental</span><span class="value">₩${fmt(p.incremental_allowance)}</span></div>
      <div class="row"><span class="label">upper limit</span><span class="value">₩${fmt(p.upper_limit)}</span></div>
      <div class="row"><span class="label">tolerable</span><span class="value">₩${fmt(p.tolerable)}</span></div>
      <div class="row"><span class="label">판정</span><span class="value proj-verdict ${p.verdict}">${p.verdict}</span></div>
    `;
  };
  drawCard("AR");
  drawCard("AP");

  // 합산
  const ar = (st.projection || {}).AR;
  const ap = (st.projection || {}).AP;
  const combined = $("#projectionCombined");
  if (!ar && !ap) {
    combined.textContent = "— (각 계산 후 합산 표시)";
    return;
  }
  const sumProj = (ar?.projected_misstatement || 0) + (ap?.projected_misstatement || 0);
  const sumUpper = (ar?.upper_limit || 0) + (ap?.upper_limit || 0);
  const sumTol = (ar?.tolerable || 0) + (ap?.tolerable || 0);
  const verdict = sumUpper <= sumTol ? "WITHIN_TOLERABLE" : "EXCEED";
  combined.innerHTML = `
    <div class="row"><span class="label">AR+AP projected</span><span class="value">₩${fmt(sumProj)}</span></div>
    <div class="row"><span class="label">AR+AP upper limit</span><span class="value">₩${fmt(sumUpper)}</span></div>
    <div class="row"><span class="label">AR+AP tolerable</span><span class="value">₩${fmt(sumTol)}</span></div>
    <div class="row"><span class="label">합산 판정</span><span class="value proj-verdict ${verdict}">${verdict}</span></div>
    ${verdict === "EXCEED" ? '<div style="color:var(--color-bad);font-size:.8rem;margin-top:.5rem;">⚠ tolerable 초과 — 추가절차 필요</div>' : ""}
  `;
}
```

`refreshState()` 안 — `renderAlternativesTable();` 다음 줄에:

```javascript
  renderProjection();
```

`init()` 안 — listener:

```javascript
  $$(".runProjection").forEach(b => b.addEventListener("click", runProjection));
```

진행도 setStep — `setStep("projection", (s.projection?.AR || s.projection?.AP) ? "done" : null);` 로 기존 `setStep("projection", "disabled");` 교체.

- [ ] **Step 4: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/
git -C c:/Claude commit -m "feat(frontend): ⑥ projection panel (AR/AP cards + combined verdict)"
```

---

### Task 17: 더미 PDF fixture 생성

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/build_dummy_pdfs.py`

표본 거래처에 매칭되는 PDF 회신 5건 (그 중 1건 DISCREPANCY 1건 미회신). reportlab 사용.

- [ ] **Step 1: build_dummy_pdfs.py**

```python
"""더미 PDF 회신 생성. Task 12의 dummy_ledger 표본과 매칭.

실행: python tests/e2e/fixtures/build_dummy_pdfs.py
"""
from __future__ import annotations
from pathlib import Path

try:
    from reportlab.pdfgen import canvas
except ImportError:
    import sys
    print("reportlab 미설치 — skip")
    sys.exit(0)


OUT = Path(__file__).parent


def make_pdf(filename: str, text: str) -> None:
    c = canvas.Canvas(str(OUT / filename))
    for i, line in enumerate(text.split("\n")):
        c.drawString(50, 800 - i * 20, line)
    c.save()


# AR050~054 + AR055 (RP였던 AR000~004 중 하나)
# build_dummy.py 에서 AR050~052 = 부실/EXCLUDED 처리됨 → 표본 미포함
# AR000~004 = RP forced. AR055~119 = REP 가능
# 표본 안에 들어갈 후보로 RP 5건 + KEY (500만 이상) 사용

# match (정확)
make_pdf("conf_AR000_match.pdf",
         "회신서\n조회처: 고객사000\n잔액: 1,000,000원\n")
make_pdf("conf_AR001_match.pdf",
         "조회처: 고객사001\n2025-12-31 기준 잔액 500,000원")
# discrepancy
make_pdf("conf_AR002_disc.pdf",
         "조회처: 고객사002\n잔액 800,000원")  # 차이
# 미회신은 PDF 자체를 생성 안 함

print("dummy PDFs built at:", OUT)
```

NOTE: 이 fixture는 실제 ledger 데이터에 따라 거래처명/금액이 달라지므로, e2e 테스트(Task 18)에서 정확한 매칭은 _make_dynamic_pdf 헬퍼로 처리하는 게 더 안정적. 위 PDF는 참고용.

- [ ] **Step 2: 실행 (선택)**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python tests/e2e/fixtures/build_dummy_pdfs.py
```

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/build_dummy_pdfs.py CC_SAMPLING_TOOL_V2/tests/e2e/fixtures/*.pdf
git -C c:/Claude commit -m "test(e2e): dummy PDF fixtures (match/discrepancy/missing)"
```

---

### Task 18: E2E 전 라이프사이클 + tag

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/test_drop_to_projection.py`

전 흐름: ingest → design → sendlist download → PDF upload (dynamic 생성) → alternative register → projection. AR/AP 모두 거쳐 합산 판정 확인.

- [ ] **Step 1: 실패 테스트**

`tests/e2e/test_drop_to_projection.py`:

```python
"""E2E — Phase 3 마일스톤: 전 라이프사이클 (ingest → projection)."""
import pytest
import io
from pathlib import Path
from unittest.mock import MagicMock
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


FIXTURES = Path(__file__).parent / "fixtures"


def _dynamic_pdf(name: str, amount: float) -> bytes:
    """동적 PDF 생성 — 실제 ledger 데이터에 맞춰."""
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 800, f"회신서")
    c.drawString(50, 780, f"조회처: {name}")
    c.drawString(50, 760, f"잔액: {int(amount):,}원")
    c.save()
    return buf.getvalue()


@pytest.fixture(scope="module")
def fixtures_ready():
    for n in ("dummy_ledger", "dummy_fs", "dummy_rp", "dummy_allowance"):
        if not (FIXTURES / f"{n}.xlsx").exists():
            pytest.skip(f"fixture {n}.xlsx missing")


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


def test_e2e_drop_to_projection(client):
    # 1) 프로젝트 + ingest
    r = client.post("/api/projects", json={
        "client": "DUMMY_CLIENT", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 50_000_000, "tolerable": 25_000_000,
    })
    pid = r.get_json()["id"]
    client.post(f"/api/projects/{pid}/ingest", data={
        "ledger": _file("dummy_ledger"),
        "fs": _file("dummy_fs"),
        "rp": _file("dummy_rp"),
        "allowance": _file("dummy_allowance"),
    }, content_type="multipart/form-data")

    # 2) AR/AP 표본설계
    for kind in ("AR", "AP"):
        client.post(f"/api/projects/{pid}/sampling/design", json={
            "kind": kind, "confidence": 0.95, "expected_ms_pct": 0.0,
            "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
        })

    # 3) 발송명단 다운로드
    r = client.get(f"/api/projects/{pid}/sendlist")
    assert r.status_code == 200
    assert r.content_type.startswith("application/vnd.openxmlformats")

    # 4) 표본 일부에 대해 PDF 회신 업로드 (match)
    state = client.get(f"/api/projects/{pid}/state").get_json()
    ar_items = state["samples"]["AR"]["items"][:3]
    assert len(ar_items) >= 1
    for i, it in enumerate(ar_items):
        # 0번: match (실 잔액), 1번: discrepancy (10% 차이), 2번: 그대로
        amt = it["balance_krw"] if i != 1 else it["balance_krw"] * 0.9
        pdf_bytes = _dynamic_pdf(it["name"], amt)
        r = client.post(f"/api/projects/{pid}/confirmations/upload",
                        data={"kind": "AR",
                              "pdf": (io.BytesIO(pdf_bytes), f"conf{i}.pdf")},
                        content_type="multipart/form-data")
        assert r.status_code == 200

    # 5) 남은 표본 1건에 대체적 절차 등록
    if len(state["samples"]["AR"]["items"]) > 3:
        no_resp = state["samples"]["AR"]["items"][3]
        r = client.post(f"/api/projects/{pid}/alternative", json={
            "kind": "AR", "party_id": no_resp["party_id"],
            "procedure_type": "후속회수",
            "evidence_sum": no_resp["balance_krw"],
            "note": "수령증 확인",
        })
        assert r.status_code == 200

    # 6) AR projection
    r = client.post(f"/api/projects/{pid}/projection",
                    json={"kind": "AR", "confidence": 0.95})
    assert r.status_code == 200
    proj = r.get_json()
    assert proj["upper_limit"] >= proj["projected_misstatement"]
    assert proj["verdict"] in ("WITHIN_TOLERABLE", "EXCEED")

    # 7) AP projection
    r = client.post(f"/api/projects/{pid}/projection",
                    json={"kind": "AP", "confidence": 0.95})
    assert r.status_code == 200

    # 8) state 전체 확인 — 모든 단계 데이터 반영
    body = client.get(f"/api/projects/{pid}/state").get_json()
    assert body["confirmations"]["AR"]
    assert body["projection"]["AR"] is not None
    assert body["projection"]["AP"] is not None
    # alternatives는 등록 시에만
```

- [ ] **Step 2: 실행**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/e2e/test_drop_to_projection.py -v
```

Expected: PASS.

- [ ] **Step 3: Phase 3 전체 회귀**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/ -q
```

Expected: 모든 unit + integration + e2e 통과. Phase 2 135 + Phase 3 신규(~40+) = 175+.

- [ ] **Step 4: domain 순수성 재검증**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -c "
import ast, sys
from pathlib import Path
forbidden = {'flask', 'sqlalchemy', 'pandas', 'openpyxl', 'pdfplumber', 'requests', 'reportlab'}
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

- [ ] **Step 5: Phase 3 마무리 커밋 + tag**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/e2e/test_drop_to_projection.py
git -C c:/Claude commit -m "test(e2e): drop-to-projection full lifecycle + Phase 3 complete"
git -C c:/Claude tag cc-v2-phase3
```

---

## Phase 3 완료 기준

- `pytest tests/ -q` 전체 PASS (~175+ tests)
- domain 순수성 통과 (forbidden import 0)
- e2e 시나리오 (ingest → projection) 자동 회귀
- 단일 대시보드 ④⑤⑥ 작동
- `git tag cc-v2-phase3`

## Phase 4 예고

- C100·AA100 최종 통합 조서 Excel 생성 (감사조서시스템 import 호환)
- 조서 양식 YAML 확장 포인트
- WAT 통합 (헤더·푸터·디자인 토큰 표준)
- 별도 plan: `2026-05-28-cc-sampling-tool-v2-phase4.md`

## Phase 2·이전 이월 정리

다음 항목은 Phase 4 또는 maintenance에서:
- AAG-SAM Table A-4 rank-증분 정밀화 (현재 _INCREMENTAL_FACTOR 단순 근사)
- Strata 스냅샷 더 정밀히 (현재 단일 strata로 단순화)
- 매핑확인 UI (confidence < 0.95 차단)
- prompt() 모달 교체
- WAT FX 캐시 TTL
- 프로젝트 삭제 route
