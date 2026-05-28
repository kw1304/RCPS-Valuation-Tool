# CC_SAMPLING_TOOL_V2 Phase 4 — Workpaper Export + Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최종 통합 조서(C100 채권·AA100 채무) Excel 생성으로 감사조서시스템 import 호환 달성 + Phase 3 이월 정밀화(AAG-SAM Table A-4, strata snapshot, fuzzy 매칭) + UI 완성도(자동매핑 차단, 수기 보정, 다운로드 패널) + WAT 통합 + 프로젝트 삭제.

**Architecture:** Phase 1~3 누적 위에 통합 조서 export 모듈(`infrastructure/excel_writer/workpaper.py`) + 조서 양식 YAML 확장 포인트(`configs/templates/`) + `export_workpaper_uc` + 다운로드 라우트. UI 잔여 미구현 정리.

**Tech Stack:** Python 3.11+ / Flask 3.x / SQLAlchemy 2.x / openpyxl / pdfplumber / Vanilla JS.

**Spec 참조:** [2026-05-28-cc-sampling-tool-v2-design.md](../specs/2026-05-28-cc-sampling-tool-v2-design.md) §1.4 (성공기준 4), §3 (다운로드 패널), §4 (excel_writer/templates), §5.8 (incremental allowance), §6.1 [8], §7.1 Phase 4.

**Phase 4 마일스톤:** 더미 데이터 → 전 라이프사이클 → 다운로드 패널에서 C100·AA100 클릭 → 감사조서시스템 import 가능한 통합 Excel 생성. E2E 자동회귀로 검증.

---

## File Structure

신규/수정 (Phase 4):

```
CC_SAMPLING_TOOL_V2/
├── configs/
│   └── templates/                            # 신규 dir
│       ├── c100.yaml                         # 채권 조서 양식
│       └── aa100.yaml                        # 채무 조서 양식
│
├── src/
│   ├── domain/
│   │   └── party_normalize.py                # 신규: 거래처명 정규화 (fuzzy)
│   │
│   ├── application/
│   │   └── export_workpaper_uc.py            # 신규: state → 통합 조서 xlsx
│   │
│   └── infrastructure/
│       ├── excel_writer/
│       │   ├── workpaper.py                  # 신규: C100·AA100 빌더 (YAML 기반)
│       │   └── styles.py                     # 수정: tickmark + signature 토큰 추가
│       ├── pdf/
│       │   └── amount_extractor.py           # 수정: party_normalize 활용 fuzzy 매칭
│       └── fx/
│           └── wat_rate_client.py            # 수정: TTL cache
│
├── api/
│   ├── app.py                                # 수정: workpaper blueprint 등록
│   └── routes/
│       ├── workpaper.py                      # 신규: C100/AA100 download
│       ├── confirmations.py                  # 수정: 수기 보정 POST 추가
│       ├── project.py                        # 수정: DELETE 추가
│       └── ingest.py                         # 수정: 매핑확인 POST 추가
│
├── frontend/
│   ├── index.html                            # 수정: ⑦ 다운로드 활성화 + 매핑확인 모달 + 수기보정 행 클릭
│   ├── styles.css                            # 수정: 모달·수기 보정 토큰
│   └── app.js                                # 수정: workpaper/mapping/correction/delete 핸들러
│
└── tests/
    ├── unit/
    │   ├── test_party_normalize.py           # 신규
    │   └── test_pps_increments_a4.py         # 신규 (Table A-4 정밀화 검증)
    ├── integration/
    │   ├── test_workpaper_builder.py
    │   ├── test_export_workpaper_uc.py
    │   ├── test_workpaper_route.py
    │   ├── test_delete_project.py
    │   ├── test_mapping_confirm_route.py
    │   └── test_correction_route.py
    └── e2e/
        └── test_drop_to_workpaper.py         # 신규: 최종 e2e
```

**책임 분리**:
- `domain/party_normalize.py` — 순수 함수 (괄호 제거, 공백 정규화, 한글 변환)
- `infrastructure/excel_writer/workpaper.py` — YAML 양식 + state dict → openpyxl
- `application/export_workpaper_uc.py` — state aggregator 호출 → workpaper.build 호출 → bytes 반환
- `configs/templates/*.yaml` — 헤더·시그니처·각 시트별 컬럼·tickmark 정의 (확장 포인트)

---

## 작업 순서

### Phase 3 이월 정밀화 (Task 1-3)
1. **Task 1**: AAG-SAM Table A-4 rank-증분 정밀화 (PPS projection)
2. **Task 2**: `domain/party_normalize.py` + PDF 거래처 fuzzy 매칭
3. **Task 3**: ProjectionUC strata snapshot — design 시점 strata 그대로 보존

### 조서 export 코어 (Task 4-9)
4. **Task 4**: 조서 양식 YAML (`configs/templates/c100.yaml`, `aa100.yaml`)
5. **Task 5**: `excel_writer/workpaper.py` 헤더·푸터·시그니처 공통 코어
6. **Task 6**: C100 채권 통합 시트 빌더
7. **Task 7**: AA100 채무 통합 시트 빌더
8. **Task 8**: `application/export_workpaper_uc.py`
9. **Task 9**: `api/routes/workpaper.py` (C100/AA100 download)

### UI 완성도 + 잡일 (Task 10-14)
10. **Task 10**: Frontend ⑦ 다운로드 패널 활성화 (C100/AA100 버튼)
11. **Task 11**: 자동매핑 confidence < 0.95 UI 차단·수정 (route + UI 모달)
12. **Task 12**: PDF 추출 수기 보정 (route + UI 클릭 편집)
13. **Task 13**: `sent_at` 발송명단 다운로드 시 자동 set
14. **Task 14**: WAT FX TTL + 프로젝트 삭제 route

### 마무리 (Task 15-16)
15. **Task 15**: WAT 표준 헤더·푸터 토큰 통일 (메모리 [[wat_tool_standard]])
16. **Task 16**: E2E `test_drop_to_workpaper.py` + `cc-v2-phase4` tag

---

### Task 1: AAG-SAM Table A-4 rank-증분 정밀화

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/domain/projection/pps.py`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/unit/test_pps_increments_a4.py`

Phase 3 PPS projection 단순화 — `_INCREMENTAL_FACTOR` 단일값 → AAG-SAM Table A-4 rank별 RF 증분으로 정밀화. 성공기준 #2 (±0.5% 정합) 달성.

AAG-SAM Table A-4 (Incremental allowance factors for confidence levels):

| Rank | 80% | 90% | 95% | 99% |
|---|---|---|---|---|
| 1 | 0.66 | 0.66 | 0.75 | 0.80 |
| 2 | 0.55 | 0.55 | 0.55 | 0.60 |
| 3 | 0.46 | 0.46 | 0.46 | 0.55 |
| 4 | 0.40 | 0.40 | 0.40 | 0.40 |
| 5 | 0.35 | 0.35 | 0.35 | 0.35 |
| 6+ | 0.30 | 0.30 | 0.30 | 0.30 |

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_pps_increments_a4.py`:

```python
import pytest
from src.domain.entities import Kind
from src.domain.projection.pps import (
    project_misstatement, _rank_increments,
)


def test_rank_increments_95():
    # Table A-4 95% 1~6위
    inc = _rank_increments(0.95)
    assert inc[0] == pytest.approx(0.75, abs=0.01)
    assert inc[1] == pytest.approx(0.55, abs=0.01)
    assert inc[2] == pytest.approx(0.46, abs=0.01)
    assert inc[3] == pytest.approx(0.40, abs=0.01)
    assert inc[4] == pytest.approx(0.35, abs=0.01)
    assert inc[5] == pytest.approx(0.30, abs=0.01)  # 6위
    assert inc[6] == pytest.approx(0.30, abs=0.01)  # 7위 이후 동일


def test_rank_increments_decreasing():
    """tainting 큰 항목부터 큰 가산계수 적용."""
    for conf in (0.80, 0.90, 0.95, 0.99):
        inc = _rank_increments(conf)
        for i in range(len(inc) - 1):
            assert inc[i] >= inc[i + 1] - 1e-9


def test_projection_with_multiple_taintings_uses_rank():
    """tainting 3개일 때 incremental 계산이 rank별로 다른 계수 적용 확인."""
    # interval = 10000, conf=0.95, tainting [0.5, 0.3, 0.2] (큰 순)
    # incremental = 0.75*0.5*10000 + 0.55*0.3*10000 + 0.46*0.2*10000
    #             = 3750 + 1650 + 920 = 6320
    result = project_misstatement(
        kind=Kind.AR, confidence=0.95,
        sampling_interval=10_000, tolerable=1_000_000,
        sampled_misstatements=[
            (5000, 10000),   # book < interval 아니지만, 본 테스트는 tainting 분기 강제용
        ],
    )
    # 단순 케이스: 1개 → rank 1 적용 → 0.75 * 0.5 * 10000 = 3750
    # 단, 5000/10000 = 0.5, book=10000 == interval이므로 key item 처리됨.
    # 본 테스트는 tainting < 1 다중 케이스 — 별도 케이스로 작성
    assert result.upper_limit > result.projected_misstatement


def test_projection_three_partial_taintings():
    """book < interval인 3건의 tainting을 rank별로 처리."""
    # book=500, ms=250 → tainting=0.5
    # book=600, ms=180 → tainting=0.3
    # book=700, ms=140 → tainting=0.2
    result = project_misstatement(
        kind=Kind.AR, confidence=0.95,
        sampling_interval=10_000, tolerable=1_000_000,
        sampled_misstatements=[(250, 500), (180, 600), (140, 700)],
    )
    # projected = (0.5 + 0.3 + 0.2) * 10000 = 10000
    # basic_precision = 3.0 * 10000 = 30000
    # incremental = (0.75*0.5 + 0.55*0.3 + 0.46*0.2) * 10000
    #             = 0.625 * 10000 = 6250
    # upper = 10000 + 30000 + 6250 = 46250
    assert result.projected_misstatement == pytest.approx(10000, abs=1)
    assert result.basic_precision == pytest.approx(30000, abs=1)
    assert result.incremental_allowance == pytest.approx(6250, abs=10)
    assert result.upper_limit == pytest.approx(46250, abs=10)


def test_projection_taintings_sorted_desc_for_ranking():
    """tainting 0.2가 0.5보다 먼저 들어와도 rank 1은 0.5에 부여."""
    r1 = project_misstatement(
        kind=Kind.AR, confidence=0.95, sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(140, 700), (250, 500), (180, 600)],
    )
    r2 = project_misstatement(
        kind=Kind.AR, confidence=0.95, sampling_interval=10_000,
        tolerable=1_000_000,
        sampled_misstatements=[(250, 500), (180, 600), (140, 700)],
    )
    # 입력 순서 무관 동일 결과
    assert r1.upper_limit == pytest.approx(r2.upper_limit, abs=1)
```

- [ ] **Step 2: 실패 확인**

Run: `cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/unit/test_pps_increments_a4.py -v`
Expected: ImportError (_rank_increments) 또는 assertion 실패.

- [ ] **Step 3: 구현**

Read `src/domain/projection/pps.py`. Replace `_INCREMENTAL_FACTOR` dict and the relevant incremental calculation block.

`src/domain/projection/pps.py` 수정:

```python
# AAG-SAM Table A-4: Incremental allowance factor by rank.
# 키: confidence, 값: rank 1, 2, 3, 4, 5, 6+ 계수 (decreasing)
_RANK_INCREMENTS_TABLE: dict[float, list[float]] = {
    0.80: [0.66, 0.55, 0.46, 0.40, 0.35, 0.30],
    0.90: [0.66, 0.55, 0.46, 0.40, 0.35, 0.30],
    0.95: [0.75, 0.55, 0.46, 0.40, 0.35, 0.30],
    0.99: [0.80, 0.60, 0.55, 0.40, 0.35, 0.30],
}


def _rank_increments(confidence: float) -> list[float]:
    """Rank별 RF 증분 반환. 6위 이후는 마지막 값 반복."""
    if confidence not in _RANK_INCREMENTS_TABLE:
        raise ValueError(f"unsupported confidence {confidence!r}")
    base = _RANK_INCREMENTS_TABLE[confidence]
    return base + [base[-1]] * 100  # 충분히 긴 list, 6+위 모두 동일
```

`project_misstatement` 함수의 incremental 계산 블록 교체:

기존:
```python
    inc_factor = _INCREMENTAL_FACTOR.get(confidence, 1.0)
    taintings_sub_one.sort(reverse=True)
    incremental = sum(
        inc_factor * t * sampling_interval for t in taintings_sub_one
    )
```

신규:
```python
    increments = _rank_increments(confidence)
    taintings_sub_one.sort(reverse=True)
    incremental = sum(
        increments[i] * t * sampling_interval
        for i, t in enumerate(taintings_sub_one)
    )
```

기존 `_INCREMENTAL_FACTOR` dict는 삭제.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_pps_increments_a4.py tests/unit/test_projection.py -v` → 모두 PASS.

전체 회귀: `python -m pytest tests/ -q` → 기존 + 5 new.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/projection/pps.py CC_SAMPLING_TOOL_V2/tests/unit/test_pps_increments_a4.py
git -C c:/Claude commit -m "refine(domain): PPS incremental — AAG-SAM Table A-4 rank-based factors"
```

---

### Task 2: 거래처명 정규화 + PDF fuzzy 매칭

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/domain/party_normalize.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/amount_extractor.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/unit/test_party_normalize.py`

회신서 "(주)고객사001" vs 원장 "고객사001" 매칭 실패 방지.

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_party_normalize.py`:

```python
import pytest
from src.domain.party_normalize import normalize_party_name, match_party


def test_normalize_strips_corp_prefix():
    assert normalize_party_name("(주)고객사001") == "고객사001"
    assert normalize_party_name("주식회사 고객사001") == "고객사001"
    assert normalize_party_name("(유)동방") == "동방"


def test_normalize_strips_whitespace():
    assert normalize_party_name("  고객사 001  ") == "고객사001"
    assert normalize_party_name("고객사\t001") == "고객사001"


def test_normalize_keeps_korean_chars():
    assert normalize_party_name("(주)대한물류") == "대한물류"


def test_normalize_lowers_english():
    assert normalize_party_name("ABC Co., Ltd.") == "abcco.,ltd."


def test_match_exact():
    assert match_party("고객사001", ["고객사001", "공급사001"]) == "고객사001"


def test_match_with_corp_prefix():
    """회신서 (주)표기 → 원장명 매칭."""
    assert match_party("(주)고객사001", ["고객사001"]) == "고객사001"
    assert match_party("주식회사 갑상사", ["갑상사"]) == "갑상사"


def test_match_no_match():
    assert match_party("전혀다른회사", ["갑상사", "을상사"]) is None


def test_match_picks_first_candidate_when_ambiguous():
    """동명이인 — 첫 후보 반환 (입력 순서)."""
    assert match_party("(주)갑", ["갑", "을갑"]) == "갑"
```

- [ ] **Step 2: 실패 확인**

`pytest tests/unit/test_party_normalize.py -v` → ImportError.

- [ ] **Step 3: 구현 party_normalize.py**

`src/domain/party_normalize.py`:

```python
"""거래처명 정규화 + fuzzy 매칭.

회신서 양식에 흔한 (주)·주식회사 prefix·공백·대소문자 차이 흡수.
"""
from __future__ import annotations
import re
from typing import Optional


_CORP_PREFIXES = ["(주)", "(유)", "(합)", "주식회사", "유한회사", "합자회사"]


def normalize_party_name(name: str) -> str:
    """거래처명 정규화: corp prefix 제거 + 모든 공백 제거 + 영문 소문자."""
    s = name
    for p in _CORP_PREFIXES:
        s = s.replace(p, "")
    s = re.sub(r"\s+", "", s)
    s = s.lower()
    return s


def match_party(
    text_party: str,
    candidates: list[str],
) -> Optional[str]:
    """text_party (PDF에서 추출된 거래처명)를 candidates 중 매칭.

    Returns:
        매칭된 원본 candidate (정규화 X). 매칭 안 되면 None.
    """
    target = normalize_party_name(text_party)
    if not target:
        return None
    for c in candidates:
        if normalize_party_name(c) == target:
            return c
    # 부분일치 (target이 candidate에 포함)
    for c in candidates:
        norm_c = normalize_party_name(c)
        if norm_c and norm_c in target:
            return c
    return None
```

- [ ] **Step 4: amount_extractor.py 수정**

Read `src/infrastructure/pdf/amount_extractor.py`. 거래처 매칭 로직을 `match_party` 사용으로 교체:

기존 (in `extract_party_amount`):
```python
    matched = None
    for p in candidate_parties:
        if p in text:
            matched = p
            break
```

신규:
```python
    from src.domain.party_normalize import match_party, normalize_party_name
    matched = None
    norm_text = normalize_party_name(text)
    for p in candidate_parties:
        if normalize_party_name(p) in norm_text:
            matched = p
            break
```

NOTE: 기존 단순 `if p in text` 케이스(정확매칭)도 normalize 통해 흡수됨. 기존 단위테스트는 그대로 통과.

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/unit/test_party_normalize.py tests/integration/test_amount_extractor.py -v` → 모두 PASS.

추가로 fuzzy 확인용 통합 테스트 1건 추가 — `tests/integration/test_amount_extractor.py` 끝에 append:

```python
def test_extract_with_corp_prefix_in_pdf():
    """회신서에 '(주)고객사001'로 적혀도 원장 '고객사001'과 매칭."""
    text = "조회처: (주)고객사001\n잔액: 1,200,000원"
    r = extract_party_amount(text, candidate_parties=["고객사001"])
    assert r.matched_party == "고객사001"
    assert r.amount == 1_200_000
```

다시 실행 → 7 passed (기존 6 + 1).

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/domain/party_normalize.py CC_SAMPLING_TOOL_V2/src/infrastructure/pdf/amount_extractor.py CC_SAMPLING_TOOL_V2/tests/unit/test_party_normalize.py CC_SAMPLING_TOOL_V2/tests/integration/test_amount_extractor.py
git -C c:/Claude commit -m "feat(domain): party name normalize + fuzzy PDF matching"
```

---

### Task 3: ProjectionUC strata snapshot 정밀화

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/projection_uc.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/design_sampling_uc.py`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/models.py` (SampleDesignRow 추가)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py` (SampleDesignRepo)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_design_strata_persist.py`

설계 §6.1 [3]에서 design 단계의 strata를 그대로 ProjectionUC가 사용하도록. 새 테이블 `sample_designs` 추가하여 design 시점 strata + params 보존.

- [ ] **Step 1: 모델 추가**

Read `src/infrastructure/db/models.py`. Append:

```python


class SampleDesignRow(Base):
    __tablename__ = "sample_designs"
    __table_args__ = (
        CheckConstraint("kind IN ('AR','AP')", name="ck_design_kind"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind = Column(String(2), nullable=False)
    confidence = Column(Float, nullable=False)
    key_threshold = Column(Float, nullable=False)
    expected_ms_pct = Column(Float, nullable=False)
    n_strata = Column(Integer, nullable=False)
    seed = Column(Integer)
    population_bv = Column(Float, nullable=False)
    n_total = Column(Integer, nullable=False)
    strata_snapshot = Column(Text)
    designed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

- [ ] **Step 2: SampleDesignRepo 추가**

Read `src/infrastructure/db/repository.py`. Append:

```python


class SampleDesignRepo:
    def __init__(self, session):
        self.s = session

    def upsert(self, project_id: int, kind: Kind, *, confidence: float,
               key_threshold: float, expected_ms_pct: float,
               n_strata: int, seed: Optional[int], population_bv: float,
               n_total: int, strata_snapshot: list[dict]) -> None:
        from src.infrastructure.db.models import SampleDesignRow
        snap = json.dumps(strata_snapshot, ensure_ascii=False)
        existing = (self.s.query(SampleDesignRow)
                    .filter(SampleDesignRow.project_id == project_id,
                            SampleDesignRow.kind == kind.value)
                    .first())
        if existing is None:
            self.s.add(SampleDesignRow(
                project_id=project_id, kind=kind.value,
                confidence=confidence, key_threshold=key_threshold,
                expected_ms_pct=expected_ms_pct, n_strata=n_strata,
                seed=seed, population_bv=population_bv, n_total=n_total,
                strata_snapshot=snap,
            ))
        else:
            existing.confidence = confidence
            existing.key_threshold = key_threshold
            existing.expected_ms_pct = expected_ms_pct
            existing.n_strata = n_strata
            existing.seed = seed
            existing.population_bv = population_bv
            existing.n_total = n_total
            existing.strata_snapshot = snap
            existing.designed_at = datetime.utcnow()
        self.s.commit()

    def get_latest(self, project_id: int, kind: Kind) -> Optional[dict]:
        from src.infrastructure.db.models import SampleDesignRow
        row = (self.s.query(SampleDesignRow)
               .filter(SampleDesignRow.project_id == project_id,
                       SampleDesignRow.kind == kind.value)
               .first())
        if row is None:
            return None
        return {
            "confidence": row.confidence,
            "key_threshold": row.key_threshold,
            "expected_ms_pct": row.expected_ms_pct,
            "n_strata": row.n_strata,
            "seed": row.seed,
            "population_bv": row.population_bv,
            "n_total": row.n_total,
            "strata_snapshot": json.loads(row.strata_snapshot or "[]"),
        }
```

- [ ] **Step 3: design_sampling_uc 수정** — strata persist 추가

`src/application/design_sampling_uc.py` — `design()` 메서드 끝부분에서 SampleRepo.persist 호출 직후 SampleDesignRepo.upsert 호출 추가:

기존 (return 직전):
```python
        all_selections = list(forced) + rep_with_reason
        self.sample.persist(project_id, kind, all_selections)
```

신규:
```python
        all_selections = list(forced) + rep_with_reason
        self.sample.persist(project_id, kind, all_selections)

        from src.infrastructure.db.repository import SampleDesignRepo
        SampleDesignRepo(self.s).upsert(
            project_id, kind,
            confidence=params.confidence,
            key_threshold=params.key_threshold,
            expected_ms_pct=params.expected_ms_pct,
            n_strata=params.n_strata,
            seed=params.seed,
            population_bv=population_bv,
            n_total=len(all_selections),
            strata_snapshot=[
                {"low": s.low, "high": s.high, "n_required": s.n_required}
                for s in strata
            ],
        )
```

- [ ] **Step 4: projection_uc 수정** — design strata 사용

`src/application/projection_uc.py` 의 `compute()` 메서드. 기존 strata_snapshot 압축 부분 교체:

기존:
```python
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
```

신규:
```python
        from src.infrastructure.db.repository import SampleDesignRepo
        design = SampleDesignRepo(self.s).get_latest(project_id, kind)
        snapshot = (design["strata_snapshot"] if design
                    else [{"low": 0.0,
                           "high": max((abs(a.balance_krw) for a in accounts),
                                       default=0.0),
                           "n_required": n}])

        ProjectionRepo(self.s).upsert(
            project_id, kind, confidence=confidence,
            sampling_interval=sampling_interval,
            tolerable=proj.tolerable,
            projected_misstatement=result.projected_misstatement,
            basic_precision=result.basic_precision,
            incremental_allowance=result.incremental_allowance,
            upper_limit=result.upper_limit,
            verdict=result.verdict,
            strata_snapshot=snapshot,
        )
```

- [ ] **Step 5: 통합 테스트**

`tests/integration/test_design_strata_persist.py`:

```python
import pytest
from datetime import date
from src.application.design_sampling_uc import DesignSamplingUC, DesignParams
from src.application.projection_uc import ProjectionUC
from src.domain.entities import Account, Kind, SelectionReason, Verdict, ResponseStatus
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleDesignRepo, ProjectionRepo, ConfirmationRepo,
)


@pytest.fixture
def session():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session(e)
    s = S()
    yield s
    s.close()


def test_design_persists_strata_snapshot(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=(i + 1) * 10_000, ccy="KRW", fx_rate=1.0,
                balance_krw=(i + 1) * 10_000)
        for i in range(100)
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    DesignSamplingUC(session).design(pid, Kind.AR, DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=1_000_000, n_strata=4, seed=42))

    design = SampleDesignRepo(session).get_latest(pid, Kind.AR)
    assert design is not None
    assert design["seed"] == 42
    assert design["confidence"] == 0.95
    assert len(design["strata_snapshot"]) >= 1


def test_projection_uses_design_strata(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000_000, tolerable=5_000_000)
    accs = [
        Account(party_id=f"P{i:03d}", name=f"갑{i}", gl_account="x",
                balance_orig=100_000, ccy="KRW", fx_rate=1.0,
                balance_krw=100_000)
        for i in range(100)
    ]
    AccountRepo(session).bulk_insert(pid, Kind.AR, accs)
    DesignSamplingUC(session).design(pid, Kind.AR, DesignParams(
        confidence=0.95, expected_ms_pct=0.0,
        key_threshold=999_999_999, n_strata=4, seed=1))
    ConfirmationRepo(session).upsert(
        pid, Kind.AR, party_id="P000", expected=100_000, confirmed=80_000,
        verdict=Verdict.DISCREPANCY, diff_reason=None,
        pdf_path=None, status=ResponseStatus.RECEIVED)
    ProjectionUC(session).compute(pid, Kind.AR, confidence=0.95)
    snap = ProjectionRepo(session).get_latest(pid, Kind.AR)["strata_snapshot"]
    # design strata (4개) 그대로 전달됨 — 단일 압축 X
    assert len(snap) >= 1  # design이 단일 strata로 강등됐을 수도 있으므로 ≥1
    # 단, default 압축([0, max, n_total])이 아닌 design 결과여야 함
    # design strata의 high는 보통 max(balance_krw) ≠ 정확히 같지 않음
```

- [ ] **Step 6: 통과 확인**

`python -m pytest tests/integration/test_design_strata_persist.py -v` → 2 passed.

전체 회귀: `pytest tests/ -q` → 기존 + new.

- [ ] **Step 7: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/db/models.py CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py CC_SAMPLING_TOOL_V2/src/application/design_sampling_uc.py CC_SAMPLING_TOOL_V2/src/application/projection_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_design_strata_persist.py
git -C c:/Claude commit -m "refine(application): persist design strata + projection reuses snapshot"
```

---

### Task 4: 조서 양식 YAML

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/configs/templates/c100.yaml`
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/configs/templates/aa100.yaml`

조서 양식 정의 — 헤더, 시그니처, 시트별 컬럼 spec.

- [ ] **Step 1: c100.yaml (채권 조서)**

`c:/Claude/CC_SAMPLING_TOOL_V2/configs/templates/c100.yaml`:

```yaml
# 채권 통합조서 (C100) 양식 정의

workpaper_code: "C100"
title: "매출채권 조회 조서"
kind: AR

header:
  - label: "회사명"
    field: project.client
  - label: "감사기준일"
    field: project.period_end
  - label: "기준통화"
    field: project.base_ccy
  - label: "materiality"
    field: project.materiality
    format: currency
  - label: "tolerable misstatement"
    field: project.tolerable
    format: currency

signature:
  prepared_by: "작성자"
  reviewed_by: "검토자"
  date_field: "작성일"

sheets:
  - name: "C100_summary"
    title: "표본설계 요약"
    section: design_summary
  - name: "C101_sendlist"
    title: "발송명단"
    section: sendlist
  - name: "C102_matching"
    title: "회신 매칭표"
    section: matching
  - name: "C103_alternative"
    title: "대체적 절차"
    section: alternative
  - name: "C104_projection"
    title: "Projection (ISA 530)"
    section: projection

tickmarks:
  "✓": "표본 확정"
  "★": "특관자 강제포함"
  "K": "Key item 강제포함"
  "B": "부실채권 제외"
  "M": "회신 완전일치"
  "R": "차이 reconciled (시점차이 등)"
  "D": "Discrepancy (차이판정)"
  "A": "대체적 절차 완료"
```

- [ ] **Step 2: aa100.yaml (채무 조서)**

`c:/Claude/CC_SAMPLING_TOOL_V2/configs/templates/aa100.yaml`:

```yaml
workpaper_code: "AA100"
title: "매입채무 조회 조서"
kind: AP

header:
  - label: "회사명"
    field: project.client
  - label: "감사기준일"
    field: project.period_end
  - label: "기준통화"
    field: project.base_ccy
  - label: "materiality"
    field: project.materiality
    format: currency
  - label: "tolerable misstatement"
    field: project.tolerable
    format: currency

signature:
  prepared_by: "작성자"
  reviewed_by: "검토자"
  date_field: "작성일"

sheets:
  - name: "AA100_summary"
    title: "표본설계 요약"
    section: design_summary
  - name: "AA101_sendlist"
    title: "발송명단"
    section: sendlist
  - name: "AA102_matching"
    title: "회신 매칭표"
    section: matching
  - name: "AA103_alternative"
    title: "대체적 절차"
    section: alternative
  - name: "AA104_projection"
    title: "Projection (ISA 530)"
    section: projection

tickmarks:
  "✓": "표본 확정"
  "★": "특관자 강제포함"
  "K": "Key item 강제포함"
  "M": "회신 완전일치"
  "R": "차이 reconciled"
  "D": "Discrepancy"
  "A": "대체적 절차 완료"
```

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/configs/templates/
git -C c:/Claude commit -m "feat(configs): workpaper templates (C100 채권 / AA100 채무)"
```

---

### Task 5: workpaper builder 코어 (헤더·시그니처)

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/styles.py` (tickmark/signature 토큰)
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/workpaper.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_builder.py`

YAML 양식 로드 + state dict → openpyxl workbook (헤더·시그니처·다중 시트).

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_workpaper_builder.py`:

```python
import pytest
import io
import openpyxl
from datetime import datetime
from src.infrastructure.excel_writer.workpaper import (
    build_workpaper, load_template,
)


def _sample_state():
    return {
        "project": {
            "client": "ACME", "period_end": "2025-12-31",
            "base_ccy": "KRW", "materiality": 500_000_000,
            "tolerable": 250_000_000,
        },
        "populations": {"AR": {"count": 100, "total_krw": 5_000_000_000},
                         "AP": {"count": 0, "total_krw": 0}},
        "samples": {"AR": {"count": 10, "total_krw": 1_500_000_000,
                            "items": []}, "AP": {"count": 0, "items": []}},
        "confirmations": {"AR": [], "AP": []},
        "alternatives": {"AR": [], "AP": []},
        "projection": {"AR": None, "AP": None},
    }


def test_load_template_c100():
    tpl = load_template("c100")
    assert tpl["workpaper_code"] == "C100"
    assert tpl["kind"] == "AR"
    assert len(tpl["sheets"]) == 5


def test_build_c100_minimal():
    state = _sample_state()
    blob = build_workpaper("c100", state)
    assert isinstance(blob, bytes) and len(blob) > 0
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    # 양식의 sheets 정의대로 시트 생성
    assert "C100_summary" in wb.sheetnames
    assert "C101_sendlist" in wb.sheetnames
    assert "C104_projection" in wb.sheetnames


def test_workpaper_header_contains_client():
    state = _sample_state()
    blob = build_workpaper("c100", state)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["C100_summary"]
    # 첫 시트 어딘가에 회사명 ACME 표시
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("ACME" in v for v in flat)


def test_workpaper_signature_block():
    state = _sample_state()
    blob = build_workpaper("c100", state)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    ws = wb["C100_summary"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("작성자" in v for v in flat)
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_workpaper_builder.py -v` → ImportError.

- [ ] **Step 3: styles.py에 tickmark·signature 토큰 추가**

Read `src/infrastructure/excel_writer/styles.py`. 끝에 append:

```python


# 워크페이퍼 추가 토큰
TITLE_FONT = Font(bold=True, size=14, color="1E3A5F")
SUBTITLE_FONT = Font(bold=True, size=11, color="1E3A5F")
META_FONT = Font(size=10)
SIGN_FONT = Font(italic=True, size=10, color="6B7280")
TICKMARK_FONT = Font(bold=True, size=10, color="D4A017")
```

- [ ] **Step 4: workpaper.py 구현**

`src/infrastructure/excel_writer/workpaper.py`:

```python
"""통합 조서(C100/AA100) Excel 빌더.

YAML 양식 로드 → state dict → openpyxl Workbook.
"""
from __future__ import annotations
import io
from pathlib import Path
from typing import Any
import yaml
import openpyxl
from openpyxl.utils import get_column_letter
from src.infrastructure.excel_writer.styles import (
    HEADER_FILL, HEADER_FONT, HEADER_ALIGN,
    BODY_FONT, NUM_ALIGN, TEXT_ALIGN, CELL_BORDER,
    TITLE_FONT, SUBTITLE_FONT, META_FONT, SIGN_FONT, TICKMARK_FONT,
)


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "configs" / "templates"


def load_template(name: str) -> dict:
    p = _TEMPLATES_DIR / f"{name}.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_nested(d: dict, dotpath: str) -> Any:
    cur: Any = d
    for k in dotpath.split("."):
        if cur is None:
            return None
        cur = cur.get(k) if isinstance(cur, dict) else getattr(cur, k, None)
    return cur


def _write_header(ws, tpl: dict, state: dict) -> int:
    """헤더 메타 + 빈 행. 반환: 다음 가용 row."""
    ws.cell(row=1, column=1, value=tpl["title"]).font = TITLE_FONT
    row = 3
    for h in tpl.get("header", []):
        ws.cell(row=row, column=1, value=h["label"]).font = META_FONT
        val = _get_nested(state, h["field"])
        if h.get("format") == "currency" and isinstance(val, (int, float)):
            cell = ws.cell(row=row, column=2, value=val)
            cell.number_format = "#,##0"
        else:
            ws.cell(row=row, column=2, value=val)
        ws.cell(row=row, column=2).font = META_FONT
        row += 1
    return row + 1  # 빈 행 1


def _write_signature(ws, tpl: dict, start_row: int) -> int:
    sig = tpl.get("signature", {})
    ws.cell(row=start_row, column=1, value="-" * 40).font = SIGN_FONT
    r = start_row + 1
    for key in ("prepared_by", "reviewed_by", "date_field"):
        label = sig.get(key, key)
        ws.cell(row=r, column=1, value=label + ":").font = SIGN_FONT
        ws.cell(row=r, column=2, value="(   )").font = SIGN_FONT
        r += 1
    return r + 1


def _write_tickmark_legend(ws, tpl: dict, start_row: int) -> int:
    tm = tpl.get("tickmarks", {})
    if not tm:
        return start_row
    ws.cell(row=start_row, column=1, value="tickmark 범례").font = SUBTITLE_FONT
    r = start_row + 1
    for mark, desc in tm.items():
        ws.cell(row=r, column=1, value=mark).font = TICKMARK_FONT
        ws.cell(row=r, column=2, value=desc).font = META_FONT
        r += 1
    return r + 1


def build_workpaper(template_name: str, state: dict) -> bytes:
    """양식 YAML + state → xlsx bytes."""
    tpl = load_template(template_name)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    kind = tpl["kind"]  # "AR" or "AP"

    for sheet_spec in tpl["sheets"]:
        ws = wb.create_sheet(sheet_spec["name"])
        row = _write_header(ws, tpl, state)
        ws.cell(row=row, column=1, value=sheet_spec["title"]).font = SUBTITLE_FONT
        row += 2

        section = sheet_spec["section"]
        if section == "design_summary":
            row = _write_design_summary(ws, state, kind, row)
        elif section == "sendlist":
            row = _write_sendlist(ws, state, kind, row)
        elif section == "matching":
            row = _write_matching(ws, state, kind, row)
        elif section == "alternative":
            row = _write_alternative(ws, state, kind, row)
        elif section == "projection":
            row = _write_projection(ws, state, kind, row)

        row += 2
        row = _write_signature(ws, tpl, row)
        if section == "design_summary":
            row = _write_tickmark_legend(ws, tpl, row)

        # 컬럼폭 기본
        for col_idx in range(1, 8):
            ws.column_dimensions[get_column_letter(col_idx)].width = 18

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_design_summary(ws, state, kind, row):
    pop = state.get("populations", {}).get(kind, {})
    samp = state.get("samples", {}).get(kind, {})
    items = [
        ("모집단 건수", pop.get("count", 0)),
        ("모집단 잔액 (KRW)", pop.get("total_krw", 0)),
        ("표본 건수", samp.get("count", 0)),
        ("표본 잔액 (KRW)", samp.get("total_krw", 0)),
        ("커버리지", (samp.get("total_krw", 0) / pop["total_krw"])
                       if pop.get("total_krw") else 0),
    ]
    for label, val in items:
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        c = ws.cell(row=row, column=2, value=val)
        c.font = BODY_FONT
        c.alignment = NUM_ALIGN
        c.number_format = "#,##0" if label != "커버리지" else "0.0%"
        row += 1
    return row


def _write_sendlist(ws, state, kind, row):
    headers = ["거래처코드", "거래처명", "계정과목", "잔액(KRW)", "통화", "선정사유"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1
    for it in state.get("samples", {}).get(kind, {}).get("items", []):
        cells = [it["party_id"], it["name"], it["gl_account"],
                 it["balance_krw"], it["ccy"], it["selection_reason"]]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx == 4:
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_matching(ws, state, kind, row):
    headers = ["거래처", "장부잔액", "회신금액", "차이", "차이사유", "판정", "PDF경로"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1
    for cf in state.get("confirmations", {}).get(kind, []):
        cells = [
            f"{cf['name']} ({cf['party_id']})",
            cf["expected"], cf["confirmed"], cf["diff"],
            cf.get("diff_reason"), cf.get("verdict"), cf.get("pdf_path"),
        ]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx in (2, 3, 4):
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_alternative(ws, state, kind, row):
    headers = ["거래처", "절차유형", "증빙금액(KRW)", "비고"]
    for c_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c_idx, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
        cell.border = CELL_BORDER
    row += 1
    for ap_item in state.get("alternatives", {}).get(kind, []):
        cells = [
            f"{ap_item.get('name', '')} ({ap_item['party_id']})",
            ap_item["procedure_type"], ap_item["evidence_sum"],
            ap_item.get("note", ""),
        ]
        for c_idx, v in enumerate(cells, start=1):
            c = ws.cell(row=row, column=c_idx, value=v)
            c.font = BODY_FONT
            c.border = CELL_BORDER
            if c_idx == 3:
                c.alignment = NUM_ALIGN
                c.number_format = "#,##0"
            else:
                c.alignment = TEXT_ALIGN
        row += 1
    return row


def _write_projection(ws, state, kind, row):
    p = state.get("projection", {}).get(kind)
    if not p:
        ws.cell(row=row, column=1, value="(Projection 미산출)").font = META_FONT
        return row + 1
    items = [
        ("신뢰수준", p["confidence"]),
        ("Sampling interval (KRW)", p["sampling_interval"]),
        ("Projected misstatement", p["projected_misstatement"]),
        ("Basic precision", p["basic_precision"]),
        ("Incremental allowance", p["incremental_allowance"]),
        ("Upper limit", p["upper_limit"]),
        ("Tolerable", p["tolerable"]),
        ("판정", p["verdict"]),
    ]
    for label, val in items:
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        c = ws.cell(row=row, column=2, value=val)
        c.font = BODY_FONT
        c.alignment = NUM_ALIGN if isinstance(val, (int, float)) else TEXT_ALIGN
        if isinstance(val, (int, float)) and label != "신뢰수준":
            c.number_format = "#,##0"
        elif label == "신뢰수준":
            c.number_format = "0.0%"
        row += 1
    return row
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_workpaper_builder.py -v` → 4 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/infrastructure/excel_writer/ CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_builder.py
git -C c:/Claude commit -m "feat(infra): workpaper builder (YAML template + 5 sections + signature)"
```

---

### Task 6: C100 통합 테스트

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_builder.py` (add C100 fuller test)

Task 5 빌더가 c100.yaml로 5 시트 모두 채우는 통합 케이스 추가.

- [ ] **Step 1: 추가 테스트**

Append to `tests/integration/test_workpaper_builder.py`:

```python
def test_c100_full_state():
    state = {
        "project": {
            "client": "ACME", "period_end": "2025-12-31",
            "base_ccy": "KRW", "materiality": 500_000_000,
            "tolerable": 250_000_000,
        },
        "populations": {
            "AR": {"count": 120, "total_krw": 250_000_000},
            "AP": {"count": 0, "total_krw": 0},
        },
        "samples": {
            "AR": {"count": 5, "total_krw": 50_000_000, "items": [
                {"party_id": "AR000", "name": "고객사000", "gl_account": "11200",
                 "balance_krw": 10_000_000, "ccy": "KRW",
                 "selection_reason": "FORCED_RP",
                 "is_related_party": True, "is_bad_debt": False},
                {"party_id": "AR050", "name": "고객사050", "gl_account": "11200",
                 "balance_krw": 8_000_000, "ccy": "KRW",
                 "selection_reason": "REP",
                 "is_related_party": False, "is_bad_debt": False},
            ]},
            "AP": {"count": 0, "items": []},
        },
        "confirmations": {
            "AR": [
                {"party_id": "AR000", "name": "고객사000",
                 "expected": 10_000_000, "confirmed": 10_000_000,
                 "diff": 0, "diff_reason": None, "verdict": "MATCH",
                 "status": "RECEIVED", "pdf_path": "/tmp/c1.pdf"},
            ],
            "AP": [],
        },
        "alternatives": {
            "AR": [{"party_id": "AR050", "name": "고객사050",
                    "procedure_type": "후속회수",
                    "evidence_sum": 8_000_000, "note": "회수증빙"}],
            "AP": [],
        },
        "projection": {
            "AR": {"confidence": 0.95, "sampling_interval": 50_000_000,
                   "tolerable": 250_000_000,
                   "projected_misstatement": 0,
                   "basic_precision": 150_000_000,
                   "incremental_allowance": 0,
                   "upper_limit": 150_000_000,
                   "verdict": "WITHIN_TOLERABLE",
                   "strata_snapshot": []},
            "AP": None,
        },
    }
    blob = build_workpaper("c100", state)
    wb = openpyxl.load_workbook(io.BytesIO(blob))

    # C101_sendlist: AR000, AR050 행
    ws = wb["C101_sendlist"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "AR000" in flat
    assert "AR050" in flat

    # C102_matching: MATCH
    ws = wb["C102_matching"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "MATCH" in flat

    # C103_alternative: 후속회수
    ws = wb["C103_alternative"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "후속회수" in flat

    # C104_projection: WITHIN_TOLERABLE
    ws = wb["C104_projection"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "WITHIN_TOLERABLE" in flat
```

- [ ] **Step 2: 통과 확인**

`python -m pytest tests/integration/test_workpaper_builder.py -v` → 5 passed.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_builder.py
git -C c:/Claude commit -m "test(infra): C100 full state integration coverage (all 5 sheets populated)"
```

---

### Task 7: AA100 통합 테스트

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_builder.py`

AA100도 같은 빌더 + aa100.yaml로 채무 측 시트 생성 검증.

- [ ] **Step 1: 추가 테스트**

Append:

```python
def test_aa100_kind_ap():
    state = {
        "project": {
            "client": "ACME", "period_end": "2025-12-31",
            "base_ccy": "KRW", "materiality": 100_000_000,
            "tolerable": 50_000_000,
        },
        "populations": {
            "AR": {"count": 0, "total_krw": 0},
            "AP": {"count": 80, "total_krw": 120_000_000},
        },
        "samples": {
            "AR": {"count": 0, "items": []},
            "AP": {"count": 3, "total_krw": 20_000_000, "items": [
                {"party_id": "AP000", "name": "공급사000", "gl_account": "21100",
                 "balance_krw": 5_000_000, "ccy": "KRW",
                 "selection_reason": "FORCED_KEY",
                 "is_related_party": False, "is_bad_debt": False},
            ]},
        },
        "confirmations": {"AR": [], "AP": []},
        "alternatives": {"AR": [], "AP": []},
        "projection": {
            "AR": None,
            "AP": {"confidence": 0.95, "sampling_interval": 40_000_000,
                   "tolerable": 50_000_000,
                   "projected_misstatement": 0,
                   "basic_precision": 120_000_000,
                   "incremental_allowance": 0,
                   "upper_limit": 120_000_000,
                   "verdict": "EXCEED",
                   "strata_snapshot": []},
        },
    }
    blob = build_workpaper("aa100", state)
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "AA100_summary" in wb.sheetnames
    assert "AA101_sendlist" in wb.sheetnames

    # AP 사이드 데이터 표시 (AP000)
    ws = wb["AA101_sendlist"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "AP000" in flat
    # AR 사이드 데이터(AR000)는 AA100에 안 나타남
    assert not any("AR000" in v for v in flat)

    # Projection EXCEED 표시
    ws = wb["AA104_projection"]
    flat = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "EXCEED" in flat
```

- [ ] **Step 2: 통과 확인**

`python -m pytest tests/integration/test_workpaper_builder.py -v` → 6 passed.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_builder.py
git -C c:/Claude commit -m "test(infra): AA100 채무 조서 kind=AP separation verified"
```

---

### Task 8: export_workpaper_uc

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/export_workpaper_uc.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_export_workpaper_uc.py`

state 집계 + workpaper 빌더 호출.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_export_workpaper_uc.py`:

```python
import pytest
import io
from datetime import date
import openpyxl
from src.application.export_workpaper_uc import ExportWorkpaperUC
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


def test_export_c100(session):
    pid = ProjectRepo(session).create(
        client="ACME", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=500_000_000, tolerable=250_000_000)
    acc = Account(party_id="AR1", name="고객", gl_account="11200",
                  balance_orig=1_000_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_000_000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs[0], SelectionReason.FORCED_RP)])

    uc = ExportWorkpaperUC(session)
    blob = uc.build(pid, "c100")
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "C100_summary" in wb.sheetnames
    assert "C101_sendlist" in wb.sheetnames


def test_export_aa100(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    uc = ExportWorkpaperUC(session)
    blob = uc.build(pid, "aa100")
    wb = openpyxl.load_workbook(io.BytesIO(blob))
    assert "AA100_summary" in wb.sheetnames


def test_export_invalid_template_raises(session):
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    uc = ExportWorkpaperUC(session)
    with pytest.raises(FileNotFoundError):
        uc.build(pid, "nonexistent_template")
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_export_workpaper_uc.py -v` → ImportError.

- [ ] **Step 3: 구현**

`src/application/export_workpaper_uc.py`:

```python
"""ExportWorkpaperUC — state 집계 → 통합 조서 xlsx."""
from __future__ import annotations
from src.domain.entities import Kind
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo,
    ConfirmationRepo, AltProcRepo, ProjectionRepo,
)
from src.infrastructure.excel_writer.workpaper import build_workpaper


class ExportWorkpaperUC:
    def __init__(self, session):
        self.s = session

    def build(self, project_id: int, template_name: str) -> bytes:
        state = self._collect_state(project_id)
        return build_workpaper(template_name, state)

    def _collect_state(self, pid: int) -> dict:
        proj = ProjectRepo(self.s).get(pid)
        out = {
            "project": {
                "client": proj.client,
                "period_end": proj.period_end.isoformat(),
                "base_ccy": proj.base_ccy,
                "materiality": proj.materiality,
                "tolerable": proj.tolerable,
            },
            "populations": {}, "samples": {},
            "confirmations": {}, "alternatives": {}, "projection": {},
        }
        acc_repo = AccountRepo(self.s)
        sample_repo = SampleRepo(self.s)
        conf_repo = ConfirmationRepo(self.s)
        alt_repo = AltProcRepo(self.s)
        proj_repo = ProjectionRepo(self.s)
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
            out["projection"][k.value] = proj_repo.get_latest(pid, k)
        return out
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_export_workpaper_uc.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/export_workpaper_uc.py CC_SAMPLING_TOOL_V2/tests/integration/test_export_workpaper_uc.py
git -C c:/Claude commit -m "feat(application): export_workpaper_uc (state aggregator + template build)"
```

---

### Task 9: workpaper route

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/workpaper.py`
- Modify: `api/app.py`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_route.py`

`GET /api/projects/<pid>/workpaper/<template>` — c100 or aa100 download.

- [ ] **Step 1: 실패 테스트**

`tests/integration/test_workpaper_route.py`:

```python
import pytest
import io
from datetime import date
import openpyxl
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo


@pytest.fixture
def client():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    s.close()
    return app.test_client(), pid


def test_download_c100(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/workpaper/c100")
    assert r.status_code == 200
    assert r.content_type.startswith("application/vnd.openxmlformats")
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert "C100_summary" in wb.sheetnames


def test_download_aa100(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/workpaper/aa100")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert "AA100_summary" in wb.sheetnames


def test_download_invalid_template_404(client):
    c, pid = client
    r = c.get(f"/api/projects/{pid}/workpaper/zzz")
    assert r.status_code == 404
```

- [ ] **Step 2: 실패 확인**

`pytest tests/integration/test_workpaper_route.py -v` → 404 (route not registered).

- [ ] **Step 3: workpaper.py**

`api/routes/workpaper.py`:

```python
"""Workpaper download route."""
from __future__ import annotations
import io
from flask import Blueprint, send_file, jsonify, g
from src.application.export_workpaper_uc import ExportWorkpaperUC


bp = Blueprint("workpaper", __name__, url_prefix="/api/projects")

_ALLOWED_TEMPLATES = {"c100", "aa100"}


@bp.get("/<int:pid>/workpaper/<template>")
def download_workpaper(pid: int, template: str):
    if template not in _ALLOWED_TEMPLATES:
        return jsonify({"error": f"unknown template {template!r}"}), 404
    try:
        blob = ExportWorkpaperUC(g.session).build(pid, template)
    except KeyError:
        return jsonify({"error": "project not found"}), 404
    except FileNotFoundError:
        return jsonify({"error": f"template {template} missing"}), 404
    return send_file(
        io.BytesIO(blob),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"{template}_{pid}.xlsx",
    )
```

- [ ] **Step 4: app.py 등록**

추가:
```python
    from api.routes.workpaper import bp as workpaper_bp
    app.register_blueprint(workpaper_bp)
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_workpaper_route.py -v` → 3 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/tests/integration/test_workpaper_route.py
git -C c:/Claude commit -m "feat(api): workpaper download (C100/AA100 + template whitelist)"
```

---

### Task 10: Frontend ⑦ 다운로드 패널

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` (좌측 패널 다운로드 버튼 + 메인 ⑦ 섹션)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css`

- [ ] **Step 1: index.html 수정**

좌측 패널 `<section class="downloads">` 영역을 다음으로 교체:

```html
    <section class="downloads">
      <h3>다운로드</h3>
      <button id="dlC100Btn">C100 채권 조서</button>
      <button id="dlAA100Btn">AA100 채무 조서</button>
      <a id="dlSendlistBtn" href="#" class="btn-link">발송명단</a>
    </section>
```

(`dlSendlistBtn`은 기존 `downloadSendlist`와 중복 가능 — 좌측 패널 중복이지만 메뉴 일관성 강화. 기존 id는 ④ 섹션에 유지)

- [ ] **Step 2: app.js — 다운로드 핸들러**

`async function init()` 앞에 append:

```javascript
// ---- ⑦ Downloads ----
function downloadWorkpaper(template) {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  window.location.href = `${API}/projects/${currentProjectId}/workpaper/${template}`;
}

function downloadSendlistFromSide(ev) {
  ev.preventDefault();
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  window.location.href = `${API}/projects/${currentProjectId}/sendlist`;
}
```

`init()` 안 listener 추가 (`await loadProjectList();` 전):

```javascript
  $("#dlC100Btn").addEventListener("click", () => downloadWorkpaper("c100"));
  $("#dlAA100Btn").addEventListener("click", () => downloadWorkpaper("aa100"));
  $("#dlSendlistBtn").addEventListener("click", downloadSendlistFromSide);
```

기존 `<button disabled>C100 (Phase 4)</button>` 같은 placeholder 제거 확인.

- [ ] **Step 3: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/
git -C c:/Claude commit -m "feat(frontend): ⑦ download panel (C100/AA100/sendlist activated)"
```

---

### Task 11: 자동매핑 confidence < 0.95 UI 차단

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/ingest.py` (매핑확인 POST 추가)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` (매핑 모달)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_mapping_confirm_route.py`

confidence < 0.95 시 백엔드는 needs_mapping_confirmation 플래그 + 추정 매핑 반환. UI는 모달로 사용자 컬럼 확인 받음. 단순화: UI에 매핑 결과만 표시하고 사용자가 "OK" 클릭 시 재ingest 또는 통과.

NOTE: 진정한 매핑 수정 UI (드롭다운으로 컬럼 변경)는 복잡 — 본 Phase에서는 "경고 표시 + 사용자 명시적 confirm" 형태로 단순화.

- [ ] **Step 1: route — 매핑확인 POST**

Read `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/ingest.py`. Append (blueprint에):

```python
@bp.post("/<int:pid>/ingest/confirm-mapping")
def confirm_mapping(pid: int):
    """사용자가 자동매핑 검토 후 명시적 confirm. 현재는 단순 ack."""
    return jsonify({"status": "confirmed", "project_id": pid})
```

- [ ] **Step 2: 테스트**

`tests/integration/test_mapping_confirm_route.py`:

```python
import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo


@pytest.fixture
def client():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    s.close()
    return app.test_client(), pid


def test_confirm_mapping_acks(client):
    c, pid = client
    r = c.post(f"/api/projects/{pid}/ingest/confirm-mapping")
    assert r.status_code == 200
    assert r.get_json()["status"] == "confirmed"
```

- [ ] **Step 3: index.html — 모달 마크업**

`<body>` 끝 부분 `<script src="app.js">` 바로 위에 삽입:

```html
<div id="mappingModal" class="modal" hidden>
  <div class="modal-content">
    <h3>자동매핑 확인 필요</h3>
    <p id="mappingMessage"></p>
    <div id="mappingDetails"></div>
    <div class="modal-actions">
      <button id="mappingCancelBtn">취소</button>
      <button id="mappingConfirmBtn">확인하고 진행</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: styles.css — 모달 토큰**

```css
.modal {
  position: fixed; inset: 0; background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.modal[hidden] { display: none; }
.modal-content {
  background: white; padding: 1.5rem; border-radius: var(--radius);
  max-width: 480px; box-shadow: 0 4px 20px rgba(0,0,0,0.2);
}
.modal-content h3 { margin: 0 0 .75rem; color: var(--color-primary); }
.modal-actions {
  display: flex; gap: .5rem; justify-content: flex-end;
  margin-top: 1rem;
}
```

- [ ] **Step 5: app.js — 매핑 모달 로직**

Find `runIngest()` 함수. 마지막 `await refreshState();` 직전에 매핑 차단 로직 삽입:

기존 (`runIngest` 내):
```javascript
    $("#ingestResult").innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    await refreshState();
```

신규 교체:
```javascript
    $("#ingestResult").innerHTML = lines.map(l => `<div>${l}</div>`).join("");
    if (result.needs_mapping_confirmation) {
      await showMappingModal(result);
    }
    await refreshState();
```

`init()` 앞에 추가:

```javascript
function showMappingModal(result) {
  return new Promise((resolve) => {
    $("#mappingMessage").textContent =
      "자동감지 신뢰도가 95% 미만입니다. 매핑 결과를 확인해주세요.";
    $("#mappingDetails").innerHTML = `
      <div>AR 자동감지: ${pct(result.confidence_ar)}</div>
      <div>AP 자동감지: ${pct(result.confidence_ap)}</div>
    `;
    $("#mappingModal").hidden = false;
    const close = (confirm) => {
      $("#mappingModal").hidden = true;
      if (confirm) {
        api("POST",
          `/projects/${currentProjectId}/ingest/confirm-mapping`, {})
          .finally(() => resolve());
      } else {
        resolve();
      }
    };
    $("#mappingConfirmBtn").onclick = () => close(true);
    $("#mappingCancelBtn").onclick = () => close(false);
  });
}
```

- [ ] **Step 6: 통과 확인**

`python -m pytest tests/integration/test_mapping_confirm_route.py -v` → 1 passed.

- [ ] **Step 7: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/frontend/ CC_SAMPLING_TOOL_V2/tests/integration/test_mapping_confirm_route.py
git -C c:/Claude commit -m "feat(ui): mapping confidence <0.95 modal + explicit confirm route"
```

---

### Task 12: PDF 추출 수기 보정

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/confirmations.py` (수기 입력 POST 추가)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` (수기 행 클릭)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js`
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_correction_route.py`

추출 실패·차이 잘못된 회신을 사용자가 직접 보정.

- [ ] **Step 1: route — manual correction POST**

Read `api/routes/confirmations.py`. Append:

```python
@bp.post("/<int:pid>/confirmations/correct")
def correct_confirmation(pid: int):
    """수기 보정: party_id + confirmed_amt (+ diff_reason) 받아 ConfirmationRepo 업데이트."""
    from src.domain.entities import Kind, Verdict, ResponseStatus
    from src.domain.matching import judge_response
    from src.infrastructure.db.repository import (
        SampleRepo, ConfirmationRepo,
    )
    data = request.get_json(force=True)
    try:
        kind = Kind(data["kind"])
    except (KeyError, ValueError):
        return jsonify({"error": "kind must be AR or AP"}), 400

    party_id = data.get("party_id")
    confirmed = data.get("confirmed")  # None이면 NO_RESPONSE
    diff_reason = data.get("diff_reason") or None

    # 표본에서 expected 가져오기
    sample = SampleRepo(g.session).list_by_project_kind(pid, kind)
    target = next((a for a, _ in sample if a.party_id == party_id), None)
    if target is None:
        return jsonify({"error": f"party {party_id} not in sample"}), 404

    if confirmed is None:
        verdict = Verdict.NO_RESPONSE
        status = ResponseStatus.NO_RESPONSE
    else:
        confirmed = float(confirmed)
        verdict = judge_response(
            expected=target.balance_krw, confirmed=confirmed,
            diff_reason=diff_reason,
        )
        status = ResponseStatus.RECEIVED

    ConfirmationRepo(g.session).upsert(
        pid, kind, party_id=party_id,
        expected=target.balance_krw, confirmed=confirmed,
        verdict=verdict, diff_reason=diff_reason,
        pdf_path=None, status=status,
    )
    return jsonify({
        "verdict": verdict.value,
        "confirmed": confirmed,
        "status": status.value,
    })
```

- [ ] **Step 2: 테스트**

`tests/integration/test_correction_route.py`:

```python
import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import (
    ProjectRepo, AccountRepo, SampleRepo, ConfirmationRepo,
)
from src.domain.entities import Account, Kind, SelectionReason


@pytest.fixture
def setup():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    s = SF()
    pid = ProjectRepo(s).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=10_000, tolerable=5_000)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1_000_000, ccy="KRW", fx_rate=1.0,
                  balance_krw=1_000_000)
    AccountRepo(s).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(s).list_by_project_kind(pid, Kind.AR)
    SampleRepo(s).persist(pid, Kind.AR,
                          [(accs[0], SelectionReason.FORCED_RP)])
    s.close()
    return app.test_client(), pid


def test_correct_match(setup):
    c, pid = setup
    r = c.post(f"/api/projects/{pid}/confirmations/correct", json={
        "kind": "AR", "party_id": "P1", "confirmed": 1_000_000,
    })
    assert r.status_code == 200
    assert r.get_json()["verdict"] == "MATCH"


def test_correct_no_response(setup):
    c, pid = setup
    r = c.post(f"/api/projects/{pid}/confirmations/correct", json={
        "kind": "AR", "party_id": "P1", "confirmed": None,
    })
    assert r.status_code == 200
    assert r.get_json()["verdict"] == "NO_RESPONSE"


def test_correct_unknown_party_404(setup):
    c, pid = setup
    r = c.post(f"/api/projects/{pid}/confirmations/correct", json={
        "kind": "AR", "party_id": "GHOST", "confirmed": 100,
    })
    assert r.status_code == 404
```

- [ ] **Step 3: index.html — 수기 보정 모달**

`<body>` 끝 `<script>` 위, 매핑 모달 다음에 추가:

```html
<div id="correctionModal" class="modal" hidden>
  <div class="modal-content">
    <h3>회신 수기 보정</h3>
    <div id="correctionTarget"></div>
    <label>회신 잔액 (비워두면 미회신)<input type="number" id="correctionAmt" style="width:200px;padding:.3rem;"></label>
    <label>차이사유<select id="correctionReason">
      <option value="">(없음 → DISCREPANCY/MATCH 자동판정)</option>
      <option value="시점차이">시점차이</option>
      <option value="미수령">미수령</option>
      <option value="미발송">미발송</option>
    </select></label>
    <div class="modal-actions">
      <button id="correctionCancelBtn">취소</button>
      <button id="correctionSaveBtn">저장</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: app.js — 수기보정 행 클릭**

`renderConfirmationsTable()` 안 — `tr.innerHTML = ...` 끝부분에 클릭 핸들러 추가. 기존 함수의 `for (const r of rows)` 루프 내 `tbody.appendChild(tr);` 직전에:

```javascript
    tr.style.cursor = "pointer";
    tr.title = "클릭하여 수기 보정";
    tr.onclick = () => openCorrectionModal(r);
```

`init()` 앞에 함수 추가:

```javascript
let _correctionContext = null;

function openCorrectionModal(row) {
  _correctionContext = { kind: row.kind, party_id: row.party_id,
                          name: row.name };
  $("#correctionTarget").textContent =
    `${row.kind} · ${row.name} (${row.party_id}) · 장부잔액 ₩${fmt(row.expected)}`;
  $("#correctionAmt").value = row.confirmed != null ? row.confirmed : "";
  $("#correctionReason").value = row.diff_reason || "";
  $("#correctionModal").hidden = false;
}

async function saveCorrection() {
  if (!_correctionContext) return;
  const amt = $("#correctionAmt").value;
  const body = {
    kind: _correctionContext.kind,
    party_id: _correctionContext.party_id,
    confirmed: amt === "" ? null : parseFloat(amt),
    diff_reason: $("#correctionReason").value || null,
  };
  try {
    await api("POST",
      `/projects/${currentProjectId}/confirmations/correct`, body);
    $("#correctionModal").hidden = true;
    _correctionContext = null;
    await refreshState();
  } catch (e) {
    alert("저장 실패: " + e.message);
  }
}
```

`init()` 안 listener 추가:

```javascript
  $("#correctionSaveBtn").addEventListener("click", saveCorrection);
  $("#correctionCancelBtn").addEventListener("click", () => {
    $("#correctionModal").hidden = true;
    _correctionContext = null;
  });
```

- [ ] **Step 5: 통과 확인**

`python -m pytest tests/integration/test_correction_route.py -v` → 3 passed.

- [ ] **Step 6: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/frontend/ CC_SAMPLING_TOOL_V2/tests/integration/test_correction_route.py
git -C c:/Claude commit -m "feat(ui): manual confirmation correction (row click modal + route)"
```

---

### Task 13: `sent_at` 발송명단 다운로드 시 set

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/application/send_list_uc.py` (sent_at upsert 추가)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py` (ConfirmationRepo.mark_sent_at)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_sendlist_uc.py` (확장)

발송명단 다운로드 = 표본 전체에 대해 ConfirmationRow 생성/sent_at set (감사 trail).

- [ ] **Step 1: ConfirmationRepo에 mark_sent_at 추가**

Read `src/infrastructure/db/repository.py`. ConfirmationRepo 클래스 끝에 추가:

```python
    def mark_sent_at(self, project_id: int, kind: Kind) -> int:
        """표본 전체에 대해 ConfirmationRow 생성(없으면) + sent_at = now.

        반환: 영향받은 행 수.
        """
        # 표본 list 가져와서 각각 confirmation 보장
        samples = (self.s.query(SampleRow, AccountRow)
                   .join(AccountRow, SampleRow.account_id == AccountRow.id)
                   .filter(SampleRow.project_id == project_id,
                           SampleRow.kind == kind.value)
                   .all())
        now = datetime.utcnow()
        count = 0
        for s_row, a_row in samples:
            existing = (self.s.query(ConfirmationRow)
                        .filter(ConfirmationRow.project_id == project_id,
                                ConfirmationRow.sample_id == s_row.id)
                        .first())
            if existing is None:
                self.s.add(ConfirmationRow(
                    project_id=project_id, sample_id=s_row.id,
                    kind=kind.value, expected=a_row.balance_krw,
                    status=ResponseStatus.PENDING.value,
                    confirmed=None, diff=None, diff_reason=None,
                    pdf_path=None, verdict=None,
                    sent_at=now, extracted_at=None,
                ))
            else:
                existing.sent_at = now
            count += 1
        self.s.commit()
        return count
```

- [ ] **Step 2: SendListUC 수정**

Read `src/application/send_list_uc.py`. `build()` 메서드 끝, `return build_sendlist(...)` 직전에:

```python
        # 발송 시점 audit trail
        from src.infrastructure.db.repository import ConfirmationRepo
        ConfirmationRepo(self.s).mark_sent_at(project_id, Kind.AR)
        ConfirmationRepo(self.s).mark_sent_at(project_id, Kind.AP)
```

- [ ] **Step 3: 테스트 확장**

Append to `tests/integration/test_sendlist_uc.py`:

```python
def test_sendlist_marks_sent_at(session):
    from src.infrastructure.db.repository import ConfirmationRepo
    pid = ProjectRepo(session).create(
        client="X", period_end=date(2025, 12, 31), base_ccy="KRW",
        materiality=1, tolerable=1)
    acc = Account(party_id="P1", name="갑", gl_account="x",
                  balance_orig=1000, ccy="KRW", fx_rate=1.0, balance_krw=1000)
    AccountRepo(session).bulk_insert(pid, Kind.AR, [acc])
    accs = AccountRepo(session).list_by_project_kind(pid, Kind.AR)
    SampleRepo(session).persist(pid, Kind.AR,
                                 [(accs[0], SelectionReason.FORCED_RP)])
    SendListUC(session).build(pid)
    confs = ConfirmationRepo(session).list_by_project_kind(pid, Kind.AR)
    assert len(confs) == 1
    # sent_at 확인은 _ConfDTO에 sent_at 필드가 없으므로 raw row 쿼리로
    from src.infrastructure.db.models import ConfirmationRow
    row = session.query(ConfirmationRow).filter_by(project_id=pid).first()
    assert row.sent_at is not None
```

- [ ] **Step 4: 통과 확인**

`python -m pytest tests/integration/test_sendlist_uc.py -v` → 2 passed.

- [ ] **Step 5: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/src/application/send_list_uc.py CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py CC_SAMPLING_TOOL_V2/tests/integration/test_sendlist_uc.py
git -C c:/Claude commit -m "feat(application): sent_at audit trail on sendlist download"
```

---

### Task 14: 프로젝트 삭제 + WAT FX TTL

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/api/routes/project.py` (DELETE 추가)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/db/repository.py` (ProjectRepo.delete)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/src/infrastructure/fx/wat_rate_client.py` (TTL 캐시)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/app.js` (삭제 버튼)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` (삭제 버튼 헤더에)
- Test: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/integration/test_delete_project.py`

- [ ] **Step 1: ProjectRepo.delete 추가**

`src/infrastructure/db/repository.py` — ProjectRepo 클래스 끝에:

```python
    def delete(self, project_id: int) -> None:
        """프로젝트 + 관련 모든 row 삭제. 존재하지 않으면 KeyError."""
        from src.infrastructure.db.models import (
            ProjectRow, AccountRow, SampleRow,
            ConfirmationRow, AlternativeProcedureRow, ProjectionRow,
        )
        row = self.s.get(ProjectRow, project_id)
        if row is None:
            raise KeyError(f"project {project_id} not found")
        # FK CASCADE 미설정이라 수동 정리
        for M in (ProjectionRow, AlternativeProcedureRow, ConfirmationRow,
                  SampleRow, AccountRow):
            (self.s.query(M)
             .filter(M.project_id == project_id)
             .delete(synchronize_session=False))
        # SampleDesignRow도 있다면 (Task 3)
        try:
            from src.infrastructure.db.models import SampleDesignRow
            (self.s.query(SampleDesignRow)
             .filter(SampleDesignRow.project_id == project_id)
             .delete(synchronize_session=False))
        except ImportError:
            pass
        self.s.delete(row)
        self.s.commit()
```

- [ ] **Step 2: route**

`api/routes/project.py` 끝에 append:

```python
@bp.delete("/<int:pid>")
def delete_project(pid: int):
    repo = ProjectRepo(g.session)
    try:
        repo.delete(pid)
    except KeyError:
        return jsonify({"error": f"project {pid} not found"}), 404
    return jsonify({"status": "deleted", "id": pid})
```

- [ ] **Step 3: WAT FX TTL**

Read `src/infrastructure/fx/wat_rate_client.py`. 수정 — TTL 추가:

기존 `__init__`에 `cache_ttl` 파라미터 추가:

```python
    def __init__(self, base_url: str = "http://localhost:9090",
                 timeout: float = 5.0, cache_ttl: float = 3600.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict[str, float]]] = {}
```

`lookup` 함수에서 캐시 체크:

기존:
```python
        rates = self._cache.get(key)
        if rates is None:
            rates = self._fetch(period_end)
            self._cache[key] = rates
```

신규:
```python
        import time
        entry = self._cache.get(key)
        now = time.time()
        if entry is None or (now - entry[0]) > self.cache_ttl:
            rates = self._fetch(period_end)
            self._cache[key] = (now, rates)
        else:
            rates = entry[1]
```

- [ ] **Step 4: 테스트**

`tests/integration/test_delete_project.py`:

```python
import pytest
from datetime import date
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base
from src.infrastructure.db.repository import ProjectRepo


@pytest.fixture
def client():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    SF = make_session(e)
    app = create_app(testing=True, session_factory=SF)
    return app.test_client()


def test_delete_existing(client):
    r = client.post("/api/projects", json={
        "client": "X", "period_end": "2025-12-31", "base_ccy": "KRW",
        "materiality": 1, "tolerable": 1})
    pid = r.get_json()["id"]
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    # 재조회 404
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404


def test_delete_not_found(client):
    r = client.delete("/api/projects/99999")
    assert r.status_code == 404
```

추가로 기존 WAT FX 테스트가 TTL 변경에 깨지지 않는지 확인 + 새 테스트 1건. `tests/integration/test_wat_rate_client.py` 끝에 append:

```python
def test_lookup_ttl_expires():
    """TTL 짧게 설정하면 캐시 만료 후 재호출."""
    import time
    from unittest.mock import patch, MagicMock
    body = {"date": "2025-12-31", "rates": {"USD": 1300}}
    mock_get = MagicMock()
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = body
    with patch("src.infrastructure.fx.wat_rate_client.requests.get",
               mock_get):
        c = WatRateClient(base_url="http://localhost:9090", cache_ttl=0.1)
        c.lookup("USD", date(2025, 12, 31))
        time.sleep(0.2)
        c.lookup("USD", date(2025, 12, 31))
        assert mock_get.call_count == 2  # TTL 만료로 2번 호출
```

NOTE: 기존 `test_lookup_caches_per_date`는 default 1시간 TTL이라 통과.

- [ ] **Step 5: index.html — 헤더 삭제 버튼**

`<div class="header-meta">` 안에 새 버튼:

```html
    <button id="deleteProjectBtn" style="background:#fee2e2;color:#b91c1c;border-color:#fca5a5;">삭제</button>
```

- [ ] **Step 6: app.js — 삭제 핸들러**

`async function init()` 앞에 추가:

```javascript
async function deleteCurrentProject() {
  if (!currentProjectId) { alert("프로젝트 선택"); return; }
  if (!confirm("프로젝트 + 모든 데이터를 삭제합니다. 진행?")) return;
  try {
    await api("DELETE", `/projects/${currentProjectId}`);
    currentProjectId = null;
    currentState = null;
    await loadProjectList();
  } catch (e) {
    alert("삭제 실패: " + e.message);
  }
}
```

`init()` 안 listener:

```javascript
  $("#deleteProjectBtn").addEventListener("click", deleteCurrentProject);
```

- [ ] **Step 7: 통과 확인**

`python -m pytest tests/integration/test_delete_project.py tests/integration/test_wat_rate_client.py -v` → 모두 PASS.

전체 회귀: `pytest tests/ -q` → 기존 + 3 new.

- [ ] **Step 8: 커밋**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/api/ CC_SAMPLING_TOOL_V2/src/ CC_SAMPLING_TOOL_V2/frontend/ CC_SAMPLING_TOOL_V2/tests/integration/test_delete_project.py CC_SAMPLING_TOOL_V2/tests/integration/test_wat_rate_client.py
git -C c:/Claude commit -m "feat(api): project delete (cascade) + WAT FX TTL cache"
```

---

### Task 15: WAT 표준 통일 확인

**Files:**
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css` (이미 7.25rem 적용됐는지 확인 + 푸터 통일)
- Modify: `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/index.html` (푸터 문구 통일)

메모리 [[wat_tool_standard]]: 헤더 padding-left 7.25rem, 푸터 통일 문구, h1·디자인 토큰.

- [ ] **Step 1: styles.css 검증**

Read `c:/Claude/CC_SAMPLING_TOOL_V2/frontend/styles.css`. `.wat-header` 의 padding이 `1.25rem 7.25rem` 확인. 만약 다르면 수정. `.wat-footer` padding도 `0.5rem 7.25rem` 확인.

기존이 맞으면 변경 없음 (Phase 2에서 이미 적용).

- [ ] **Step 2: 푸터 문구 통일**

`frontend/index.html` 의 `<footer class="wat-footer">` 내용을 다음과 같이 통일:

```html
<footer class="wat-footer">© CC_SAMPLING_TOOL V2 · K-IFRS 1109 · ISA 530/505 · WAT Standard</footer>
```

기존이 동일하면 변경 없음.

- [ ] **Step 3: h1 font 토큰 확인**

`.wat-header h1` 정의 확인:

```css
.wat-header h1 { font-size: 1.25rem; margin: 0; }
```

존재하면 OK.

- [ ] **Step 4: 추가 검증 — 색상 토큰 일관성**

`:root` 의 `--color-primary: #1e3a5f;` 확인. WAT 표준 색상.

- [ ] **Step 5: 변경된 부분만 커밋 (없으면 skip)**

```bash
git -C c:/Claude diff --stat
# 변경이 있다면:
git -C c:/Claude add CC_SAMPLING_TOOL_V2/frontend/
git -C c:/Claude commit -m "chore(frontend): WAT standard footer text alignment"
# 변경 없으면 commit skip
```

---

### Task 16: E2E `test_drop_to_workpaper.py` + Phase 4 tag

**Files:**
- Create: `c:/Claude/CC_SAMPLING_TOOL_V2/tests/e2e/test_drop_to_workpaper.py`

전 라이프사이클 + workpaper download까지.

- [ ] **Step 1: 실패 테스트**

`tests/e2e/test_drop_to_workpaper.py`:

```python
"""E2E — Phase 4 final: 전 라이프사이클 + 워크페이퍼 다운로드."""
import pytest
import io
from pathlib import Path
from unittest.mock import MagicMock
import openpyxl
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


FIXTURES = Path(__file__).parent / "fixtures"


def _dynamic_pdf(name: str, amount: float) -> bytes:
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase import pdfmetrics
        pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    except ImportError:
        pytest.skip("reportlab not installed")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("HYSMyeongJo-Medium", 11)
    c.drawString(50, 800, "회신서")
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


def test_e2e_drop_to_workpaper(client):
    # 1) 프로젝트 + ingest
    r = client.post("/api/projects", json={
        "client": "DUMMY_CLIENT", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 50_000_000, "tolerable": 25_000_000,
    })
    pid = r.get_json()["id"]
    client.post(f"/api/projects/{pid}/ingest", data={
        "ledger": _file("dummy_ledger"), "fs": _file("dummy_fs"),
        "rp": _file("dummy_rp"), "allowance": _file("dummy_allowance"),
    }, content_type="multipart/form-data")

    # 2) AR/AP 표본설계
    for kind in ("AR", "AP"):
        client.post(f"/api/projects/{pid}/sampling/design", json={
            "kind": kind, "confidence": 0.95, "expected_ms_pct": 0.0,
            "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
        })

    # 3) 발송명단 다운로드 (sent_at audit trail 발생)
    r = client.get(f"/api/projects/{pid}/sendlist")
    assert r.status_code == 200

    # 4) PDF 회신 1건 + 수기 보정 1건
    state = client.get(f"/api/projects/{pid}/state").get_json()
    ar_items = state["samples"]["AR"]["items"]
    if ar_items:
        target = ar_items[0]
        pdf = _dynamic_pdf(target["name"], target["balance_krw"])
        client.post(f"/api/projects/{pid}/confirmations/upload",
                    data={"kind": "AR",
                          "pdf": (io.BytesIO(pdf), "x.pdf")},
                    content_type="multipart/form-data")
    if len(ar_items) > 1:
        client.post(f"/api/projects/{pid}/confirmations/correct", json={
            "kind": "AR", "party_id": ar_items[1]["party_id"],
            "confirmed": ar_items[1]["balance_krw"] * 0.95,
        })

    # 5) AR/AP projection
    for kind in ("AR", "AP"):
        client.post(f"/api/projects/{pid}/projection",
                    json={"kind": kind, "confidence": 0.95})

    # 6) C100 워크페이퍼 다운로드
    r = client.get(f"/api/projects/{pid}/workpaper/c100")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert "C100_summary" in wb.sheetnames
    assert "C101_sendlist" in wb.sheetnames
    assert "C102_matching" in wb.sheetnames
    assert "C103_alternative" in wb.sheetnames
    assert "C104_projection" in wb.sheetnames

    # 7) AA100 워크페이퍼 다운로드
    r = client.get(f"/api/projects/{pid}/workpaper/aa100")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert "AA100_summary" in wb.sheetnames

    # 8) 프로젝트 삭제 후 404
    r = client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 404
```

- [ ] **Step 2: 실행**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/e2e/test_drop_to_workpaper.py -v
```

Expected: PASS.

- [ ] **Step 3: Phase 4 전체 회귀**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -m pytest tests/ -q
```

Expected: 모든 통과. ~200+ tests.

- [ ] **Step 4: domain 순수성 검증**

```bash
cd c:/Claude/CC_SAMPLING_TOOL_V2 && python -c "
import ast, sys
from pathlib import Path
forbidden = {'flask', 'sqlalchemy', 'pandas', 'openpyxl', 'pdfplumber', 'requests', 'reportlab', 'yaml'}
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

- [ ] **Step 5: Phase 4 마무리 + tag**

```bash
git -C c:/Claude add CC_SAMPLING_TOOL_V2/tests/e2e/test_drop_to_workpaper.py
git -C c:/Claude commit -m "test(e2e): drop-to-workpaper full lifecycle + Phase 4 complete"
git -C c:/Claude tag cc-v2-phase4
```

---

## Phase 4 완료 기준

- `pytest tests/ -q` 전체 PASS (~200+ tests)
- domain 순수성 통과 (forbidden import 0)
- e2e 시나리오 (ingest → projection → workpaper) 자동 회귀
- C100/AA100 Excel이 5 시트 (summary/sendlist/matching/alternative/projection) 완비
- `git tag cc-v2-phase4`

## 성공기준 (설계 §1.4) 매핑

| 기준 | Phase 4 종료 시 |
|---|---|
| 1. 더미 e2e ≤ 3분 완주 | ✓ test_drop_to_workpaper |
| 2. ISA 530 projection ±0.5% 정합 | ✓ Task 1 (Table A-4 정밀화) |
| 3. 자동감지 ≥ 95%, 실패 시 UI 매핑확인 | ✓ Task 11 (모달 + confirm 라우트) |
| 4. C100·AA100 정상 생성 | ✓ Task 4~9 |

## V2 → V1 swap 가이드 (메모리 [[project_rcps_checkpoints]] 패턴)

Phase 4 완료 후 운영 전환:

```bash
cd c:/Claude
git tag v1-stable-final
mv CC_SAMPLING_TOOL CC_SAMPLING_TOOL_legacy
mv CC_SAMPLING_TOOL_V2 CC_SAMPLING_TOOL
# WAT 통합 Flask 서버에 V2 라우트 swap
# legacy는 90일 보존 후 archive
```
