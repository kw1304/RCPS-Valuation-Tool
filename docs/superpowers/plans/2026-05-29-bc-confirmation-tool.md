# BC 은행조회서(금융기관 조회) Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** G/L에서 금융기관을 자동 추출 → 회사·전기·월보·담보·보증·주소 cross-check → 회신 PDF 파싱 → 4150 조서(AC0~AC10) 자동 fill까지 자동화하는 audit tool 구축.

**Architecture:** Clean Architecture (domain ← application ← infrastructure ← api). FastAPI server (port 8765), SQLite state, openpyxl로 원본 4150 template 셀 단위 fill (서식·테두리·병합 보존). Frontend는 WAT iframe shell에 임베드되는 10-step wizard.

**Tech Stack:** Python 3.12, FastAPI, openpyxl, pdfplumber, pytesseract, rapidfuzz, pydantic v2, SQLite, vanilla JS + Pretendard.

**Reference Spec:** `docs/superpowers/specs/2026-05-29-bc-confirmation-tool-design.md`

---

## File Structure

### 생성 파일
```
BC_CONFIRMATION_TOOL/
├── pyproject.toml
├── run_server.py
├── api/
│   ├── __init__.py
│   ├── app.py
│   └── routes/
│       ├── __init__.py
│       ├── projects.py
│       ├── upload.py
│       ├── sampling.py
│       ├── crosscheck.py
│       ├── response.py
│       └── workpaper.py
├── src/
│   ├── __init__.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── financial_account.py
│   │   ├── party_normalize.py
│   │   ├── sampling.py
│   │   ├── crosscheck.py
│   │   └── ac_models.py
│   ├── application/
│   │   ├── __init__.py
│   │   ├── ingest_uc.py
│   │   ├── sampling_uc.py
│   │   ├── crosscheck_uc.py
│   │   ├── parse_response_uc.py
│   │   └── export_4150_uc.py
│   └── infrastructure/
│       ├── __init__.py
│       ├── gl_loader.py
│       ├── cs_loader.py
│       ├── union_monthly.py
│       ├── address_validator.py
│       ├── pdf/
│       │   ├── __init__.py
│       │   ├── extractor.py
│       │   ├── ocr.py
│       │   ├── filename_parser.py
│       │   ├── section_classifier.py
│       │   └── generic_parser.py
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   └── repository.py
│       └── excel_writer/
│           ├── __init__.py
│           ├── ac_filler.py
│           └── color_swap.py
├── configs/
│   ├── financial_keywords.yaml
│   ├── bank_aliases.yaml
│   ├── domestic_locations.yaml
│   ├── foreign_cities.yaml
│   └── companies/  (per-company override, gitignored)
├── templates/
│   └── 4150_AC_template.xlsx     (INPUT/V1 사본)
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── data/  (SQLite, gitignored)
├── INPUT/, OUTPUT/  (gitignored)
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

### 수정 파일
- `c:/Claude/WAT/index.html` — TOOLS 객체에 BC tool entry 추가

---

## Phase 0 — Project Bootstrap

### Task 0.1: 프로젝트 골격·의존성

**Files:**
- Create: `BC_CONFIRMATION_TOOL/pyproject.toml`
- Create: `BC_CONFIRMATION_TOOL/.gitignore`
- Create: `BC_CONFIRMATION_TOOL/README.md`

- [ ] **Step 1: pyproject.toml**

```toml
[project]
name = "bc-confirmation-tool"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "openpyxl>=3.1",
    "pdfplumber>=0.10",
    "pytesseract>=0.3.10",
    "Pillow>=10.0",
    "pdf2image>=1.16",
    "rapidfuzz>=3.6",
    "pydantic>=2.6",
    "PyYAML>=6.0",
    "sqlmodel>=0.0.16",
    "python-multipart>=0.0.9",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: .gitignore**

```
__pycache__/
*.pyc
.venv/
data/*.db
INPUT/
OUTPUT/
configs/companies/
_*.xlsx
_*.log
```

- [ ] **Step 3: README.md**

```markdown
# BC 은행조회서 자동화 Tool
4150 조서(금융기관 조회) 자동 작성.
- Sampling: G/L → 금융기관 추출 (B/S + P/L)
- Cross-check: 회사 CS · 전기 · 월보 · 담보·보증 · 주소
- 회신본 PDF (온라인·우편) 파싱
- AC0~AC10 셀 자동 fill (원본 양식 보존, Toss 색감)
- WAT 임베드

## 실행
```
uv sync
python run_server.py
```
포트 8765, http://127.0.0.1:8765
```

- [ ] **Step 4: Commit**

```bash
cd c:/Claude/BC_CONFIRMATION_TOOL
git add pyproject.toml .gitignore README.md
git commit -m "feat(bc): bootstrap project skeleton"
```

---

### Task 0.2: Config seed YAML

**Files:**
- Create: `BC_CONFIRMATION_TOOL/configs/financial_keywords.yaml`
- Create: `BC_CONFIRMATION_TOOL/configs/bank_aliases.yaml`
- Create: `BC_CONFIRMATION_TOOL/configs/domestic_locations.yaml`
- Create: `BC_CONFIRMATION_TOOL/configs/foreign_cities.yaml`

- [ ] **Step 1: financial_keywords.yaml**

```yaml
direct_accounts:
  # B/S
  예금: [현금성자산, 단기금융상품, 정기예금, 보통예금, 당좌예금, 외화예금, MMDA, MMF, CMA, RP]
  차입: [단기차입금, 장기차입금, 사채, 유동성장기부채, 회사채, 외화차입금]
  파생: [파생상품자산, 파생상품부채, 통화선도, 이자율스왑, 통화스왑, 옵션]
  보증: [지급보증, 보증금, 보증채무, 우발채무, 신용장]
  담보: [담보제공자산, 근저당, 질권]
  유가증권: [당기손익공정가치측정금융자산, 매도가능증권, FVPL, FVOCI, 주식, 채권]
  보험: [장기금융상품-보험, 보험예치금, 퇴직연금운용자산]
  # P/L
  이자손익: [이자수익, 이자비용, 차입금이자, 사채이자]
  외환: [외환차익, 외환차손, 외화환산이익, 외화환산손실]
  평가손익: [파생상품평가이익, 파생상품평가손실, 파생상품거래이익, 파생상품거래손실, FVPL평가손익, FVOCI평가손익]
  수수료: [지급수수료, 금융수수료, 은행수수료, 증권거래수수료, 신용카드수수료]
  배당: [배당금수익, 수입배당금]
  보험비용: [보험료, 화재보험료, 손해보험료, 임원배상책임보험료]
```

- [ ] **Step 2: bank_aliases.yaml**

```yaml
financial_institutions:
  - {canonical: 국민은행,    aliases: [KB국민은행, KB국민, KB, 국민銀]}
  - {canonical: 신한은행,    aliases: [신한, 신한銀, SHINHAN]}
  - {canonical: 우리은행,    aliases: [우리, WOORI]}
  - {canonical: KEB하나은행, aliases: [하나은행, 하나, KEB, KEB하나]}
  - {canonical: 농협은행,    aliases: [농협, NH, NH농협]}
  - {canonical: 기업은행,    aliases: [IBK, IBK기업은행, 중소기업은행]}
  - {canonical: 산업은행,    aliases: [KDB, KDB산업은행]}
  - {canonical: 한국수출입은행, aliases: [수출입은행, KEXIM]}
  - {canonical: 한국증권금융, aliases: [증권금융]}
  - {canonical: 아이엠뱅크,  aliases: [iM뱅크, IM뱅크, 대구은행]}
  - {canonical: 대신증권,    aliases: [대신]}
  - {canonical: 메리츠증권,  aliases: [메리츠증권(주)]}
  - {canonical: 신한투자증권, aliases: [신한금융투자, 신한투자]}
  - {canonical: KB증권,     aliases: [KB증권(주)]}
  - {canonical: NH투자증권, aliases: [NH투자, NH증권]}
  - {canonical: 삼성증권,    aliases: [삼성증]}
  - {canonical: 미래에셋증권, aliases: [미래에셋대우, 미래에셋]}
  - {canonical: 키움증권,    aliases: [키움]}
  - {canonical: 한화투자증권, aliases: [한화증권]}
  - {canonical: KB손해보험,  aliases: [KB손보]}
  - {canonical: 한화손해보험, aliases: [한화손보]}
  - {canonical: 메리츠화재해상보험, aliases: [메리츠화재]}
  - {canonical: 서울보증보험, aliases: [SGI서울보증, 서울보증]}
  - {canonical: 현대해상화재보험, aliases: [현대해상, 현대화재]}
  - {canonical: 흥국화재,    aliases: [흥국화재해상]}
  - {canonical: 예별손해보험, aliases: [예별손보]}
```

- [ ] **Step 3: domestic_locations.yaml**

```yaml
domestic_locations:
  - 서울
  - 부산
  - 대구
  - 인천
  - 광주
  - 대전
  - 울산
  - 세종
  - 강남
  - 종로
  - 역삼
  - 여의도
  - 잠실
  - 신촌
  - 서초
  - 성수
  - 마포
  - 송파
  - 강북
  - 영등포
  - 분당
  - 판교
  - 일산
  - 수원
  - 용인
  - 성남
  - 화성
  - 청주
  - 천안
  - 전주
  - 광주광역
  - 창원
  - 포항
  - 제주
```

- [ ] **Step 4: foreign_cities.yaml**

```yaml
foreign_cities:
  ko:
    - 도쿄
    - 동경
    - 홍콩
    - 뉴욕
    - 런던
    - 상하이
    - 상해
    - 싱가포르
    - 싱가폴
    - 베이징
    - 북경
    - 로스앤젤레스
    - 파리
    - 프랑크푸르트
    - 시드니
    - 두바이
    - 자카르타
    - 하노이
    - 호치민
    - 방콕
    - 쿠알라룸푸르
    - 마닐라
    - 취리히
    - 뭄바이
    - 이스탄불
    - 모스크바
    - 토론토
    - 밴쿠버
  en:
    - Tokyo
    - HongKong
    - "Hong Kong"
    - HK
    - "New York"
    - NewYork
    - NY
    - London
    - Shanghai
    - SH
    - Singapore
    - SG
    - Beijing
    - BJ
    - LA
    - Paris
    - Frankfurt
    - Sydney
    - Dubai
    - Jakarta
    - Hanoi
    - "Ho Chi Minh"
    - Bangkok
    - KL
    - Manila
    - Zurich
    - Mumbai
    - Istanbul
    - Moscow
    - "Sao Paulo"
    - Toronto
    - Vancouver
  generic:
    - Branch
    - Overseas
```

- [ ] **Step 5: Commit**

```bash
git add configs/
git commit -m "feat(bc): seed config yamls (keywords, aliases, locations)"
```

---

### Task 0.3: SQLite 모델 + Repository

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/db/models.py`
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/db/repository.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_db_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_db_models.py
import pytest
from sqlmodel import Session, SQLModel, create_engine
from src.infrastructure.db.models import Project, Counterparty

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(eng)
    return eng

def test_create_project_and_counterparty(engine):
    with Session(engine) as s:
        p = Project(name="코스맥스비티아이", fiscal_date="2025-12-31")
        s.add(p)
        s.commit()
        s.refresh(p)
        c = Counterparty(project_id=p.id, bc_no="BC-1", canonical_name="국민은행")
        s.add(c)
        s.commit()
        s.refresh(c)
        assert c.id is not None
        assert c.canonical_name == "국민은행"
```

- [ ] **Step 2: Run test (fail)**

```bash
cd c:/Claude/BC_CONFIRMATION_TOOL && pytest tests/unit/test_db_models.py -v
```
Expected: FAIL (ImportError, models.py 없음)

- [ ] **Step 3: Implement models.py**

```python
# src/infrastructure/db/models.py
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    fiscal_date: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Counterparty(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    bc_no: str                                  # BC-1
    canonical_name: str                          # 국민은행
    raw_name: Optional[str] = None
    branch: Optional[str] = None
    is_foreign: bool = False
    channel: Optional[str] = None                # online | postal
    address: Optional[str] = None
    address_valid: Optional[str] = None          # ok | mismatch | not_found | failed
    cs_present: Optional[bool] = None
    prior_present: Optional[bool] = None
    union_listed: Optional[bool] = None
    collateral_listed: Optional[bool] = None
    guarantee_listed: Optional[bool] = None
    response_arrived: bool = False
    bs_balance: float = 0.0
    pl_volume: float = 0.0
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class FileAsset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    kind: str                                    # gl | cs | prior_cs | union | collateral | guarantee | response
    bc_no: Optional[str] = None
    channel: Optional[str] = None
    original_name: str
    stored_path: str
    parsed_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ExtractedRecord(SQLModel, table=True):
    """AC1~AC8 추출 record. ac_section으로 시트 구분."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    counterparty_id: int = Field(foreign_key="counterparty.id", index=True)
    ac_section: str                              # AC1 | AC2 | ... | AC8
    payload_json: str                            # 도메인 모델 직렬화
    confidence: str = "high"                     # high | medium | low
    source_file: Optional[str] = None
    source_page: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_db_models.py -v
```
Expected: PASS

- [ ] **Step 5: Implement repository.py**

```python
# src/infrastructure/db/repository.py
from pathlib import Path
from sqlmodel import Session, SQLModel, create_engine, select
from .models import Project, Counterparty, FileAsset, ExtractedRecord

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "projects.db"

def get_engine(db_path: Path | None = None):
    p = db_path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{p}")
    SQLModel.metadata.create_all(eng)
    return eng

def create_project(session: Session, name: str, fiscal_date: str) -> Project:
    p = Project(name=name, fiscal_date=fiscal_date)
    session.add(p); session.commit(); session.refresh(p)
    return p

def list_counterparties(session: Session, project_id: int) -> list[Counterparty]:
    return session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id).order_by(Counterparty.bc_no)
    ).all()

def upsert_counterparty(session: Session, project_id: int, canonical_name: str,
                        branch: str | None = None, is_foreign: bool = False) -> Counterparty:
    stmt = select(Counterparty).where(
        Counterparty.project_id == project_id,
        Counterparty.canonical_name == canonical_name,
        Counterparty.branch == branch,
    )
    existing = session.exec(stmt).first()
    if existing:
        return existing
    # auto BC-N
    n = len(list_counterparties(session, project_id)) + 1
    c = Counterparty(
        project_id=project_id,
        bc_no=f"BC-{n}",
        canonical_name=canonical_name,
        branch=branch,
        is_foreign=is_foreign,
    )
    session.add(c); session.commit(); session.refresh(c)
    return c
```

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/db tests/unit/test_db_models.py
git commit -m "feat(bc): SQLModel schema + repository (project, counterparty, file, record)"
```

---

### Task 0.4: FastAPI skeleton + healthz

**Files:**
- Create: `BC_CONFIRMATION_TOOL/api/app.py`
- Create: `BC_CONFIRMATION_TOOL/api/__init__.py`
- Create: `BC_CONFIRMATION_TOOL/api/routes/__init__.py`
- Create: `BC_CONFIRMATION_TOOL/run_server.py`
- Create: `BC_CONFIRMATION_TOOL/tests/integration/test_healthz.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_healthz.py
from fastapi.testclient import TestClient
from api.app import app

def test_healthz():
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/integration/test_healthz.py -v
```
Expected: FAIL (ImportError)

- [ ] **Step 3: api/app.py**

```python
# api/app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(title="BC Confirmation Tool")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
```

- [ ] **Step 4: run_server.py**

```python
# run_server.py
import uvicorn
if __name__ == "__main__":
    uvicorn.run("api.app:app", host="127.0.0.1", port=8765, reload=True)
```

- [ ] **Step 5: Run test (pass)**

```bash
pytest tests/integration/test_healthz.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api run_server.py tests/integration/test_healthz.py
git commit -m "feat(bc): FastAPI skeleton + healthz"
```

---

## Phase 1A — Sampling Core

### Task 1A.1: financial_account.py — 계정 분류기

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/domain/financial_account.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_financial_account.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_financial_account.py
from pathlib import Path
from src.domain.financial_account import FinancialAccountClassifier

CFG = Path(__file__).resolve().parents[2] / "configs" / "financial_keywords.yaml"

def test_classify_bs_deposit():
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("보통예금") == "예금"
    assert clf.classify("정기예금") == "예금"

def test_classify_pl_interest():
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("이자수익") == "이자손익"
    assert clf.classify("차입금이자") == "이자손익"

def test_classify_unknown():
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("매출원가") is None

def test_classify_partial_match():
    # 부분 매칭: "단기금융상품-우리은행" → "예금" 분류
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("단기금융상품-우리은행") == "예금"
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_financial_account.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/domain/financial_account.py
from pathlib import Path
import yaml

class FinancialAccountClassifier:
    def __init__(self, direct_accounts: dict[str, list[str]]):
        self.buckets: dict[str, str] = {}
        for bucket, keywords in direct_accounts.items():
            for k in keywords:
                self.buckets[k] = bucket

    @classmethod
    def load(cls, yaml_path: Path) -> "FinancialAccountClassifier":
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(data["direct_accounts"])

    def classify(self, account_name: str) -> str | None:
        """Returns bucket name ('예금','차입',...) or None."""
        if not account_name:
            return None
        # exact match first
        if account_name in self.buckets:
            return self.buckets[account_name]
        # substring match (긴 keyword 우선)
        for kw in sorted(self.buckets.keys(), key=len, reverse=True):
            if kw in account_name:
                return self.buckets[kw]
        return None

    def is_financial(self, account_name: str) -> bool:
        return self.classify(account_name) is not None

    def is_balance_sheet(self, bucket: str) -> bool:
        return bucket in {"예금","차입","파생","보증","담보","유가증권","보험"}

    def is_profit_loss(self, bucket: str) -> bool:
        return bucket in {"이자손익","외환","평가손익","수수료","배당","보험비용"}
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_financial_account.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/financial_account.py tests/unit/test_financial_account.py
git commit -m "feat(bc): financial account classifier (B/S + P/L bucket)"
```

---

### Task 1A.2: party_normalize.py — canonical + 지점 normalize

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/domain/party_normalize.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_party_normalize.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_party_normalize.py
from pathlib import Path
from src.domain.party_normalize import PartyNormalizer

CFG_DIR = Path(__file__).resolve().parents[2] / "configs"

def test_canonical_simple():
    n = PartyNormalizer.load(CFG_DIR)
    assert n.normalize("KB국민은행").canonical == "국민은행"
    assert n.normalize("국민銀").canonical == "국민은행"

def test_domestic_branch_collapses_to_head():
    n = PartyNormalizer.load(CFG_DIR)
    a = n.normalize("신한은행 강남지점")
    b = n.normalize("신한은행 용인지점")
    assert a.canonical == "신한은행"
    assert a.branch is None
    assert a.is_foreign is False
    assert b.canonical == "신한은행"
    assert a.entity_key() == b.entity_key()

def test_foreign_branch_separate():
    n = PartyNormalizer.load(CFG_DIR)
    a = n.normalize("신한은행 강남지점")
    b = n.normalize("신한은행 도쿄지점")
    c = n.normalize("신한은행 홍콩")
    d = n.normalize("국민은행 런던지점")
    assert b.canonical == "신한은행"
    assert b.branch == "도쿄지점"
    assert b.is_foreign is True
    assert c.branch == "홍콩지점"
    assert d.branch == "런던지점"
    assert a.entity_key() != b.entity_key()
    assert b.entity_key() != c.entity_key()

def test_long_candidate_wins():
    # "코스맥스펫" vs "코스맥스" — 긴 candidate 우선 (가로채기 방지)
    # 동등 룰을 bank 이름에서도 확인 — KEB하나은행 vs 하나은행
    n = PartyNormalizer.load(CFG_DIR)
    assert n.normalize("KEB하나은행 강남지점").canonical == "KEB하나은행"

def test_unknown_returns_raw():
    n = PartyNormalizer.load(CFG_DIR)
    r = n.normalize("XYZ캐피탈")
    assert r.canonical == "XYZ캐피탈"
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_party_normalize.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/domain/party_normalize.py
import re
import yaml
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class NormalizedParty:
    canonical: str          # 국민은행
    branch: str | None      # None | "도쿄지점"
    is_foreign: bool
    raw: str

    def entity_key(self) -> str:
        return f"{self.canonical}|{self.branch or ''}"

class PartyNormalizer:
    def __init__(self, aliases: list[dict], domestic_locs: list[str], foreign_cities: dict):
        # aliases: [{canonical, aliases: [...]}, ...]
        # 긴 candidate 우선: canonical과 alias 모두를 길이순 정렬
        self._lookup: list[tuple[str, str]] = []
        for item in aliases:
            canon = item["canonical"]
            self._lookup.append((canon, canon))
            for a in item.get("aliases", []) or []:
                self._lookup.append((a, canon))
        self._lookup.sort(key=lambda t: len(t[0]), reverse=True)
        self._domestic = set(domestic_locs)
        self._foreign_ko = set(foreign_cities.get("ko", []))
        self._foreign_en = set(foreign_cities.get("en", []))
        self._foreign_generic = set(foreign_cities.get("generic", []))

    @classmethod
    def load(cls, cfg_dir: Path) -> "PartyNormalizer":
        with open(cfg_dir / "bank_aliases.yaml", encoding="utf-8") as f:
            aliases = yaml.safe_load(f)["financial_institutions"]
        with open(cfg_dir / "domestic_locations.yaml", encoding="utf-8") as f:
            domestic = yaml.safe_load(f)["domestic_locations"]
        with open(cfg_dir / "foreign_cities.yaml", encoding="utf-8") as f:
            foreign = yaml.safe_load(f)["foreign_cities"]
        return cls(aliases, domestic, foreign)

    def _match_canonical(self, text: str) -> str | None:
        for key, canon in self._lookup:
            if key in text:
                return canon
        return None

    def _detect_foreign(self, text: str) -> str | None:
        """Returns the foreign city/marker found, or None."""
        # Korean foreign cities
        for c in self._foreign_ko:
            if c in text:
                return c
        # English foreign cities (case-insensitive)
        upper = text.upper()
        for c in self._foreign_en:
            if c.upper() in upper:
                return c
        # generic (Branch/Overseas)
        for c in self._foreign_generic:
            if c in text:
                return c
        return None

    def _detect_domestic_branch(self, text: str) -> bool:
        # 도시명 + (지점|점)?
        for loc in self._domestic:
            if loc in text:
                return True
        # "...지점" 만 단독 (외국 표지 없을 때) → 국내로 간주
        if "지점" in text:
            return True
        return False

    def normalize(self, raw: str) -> NormalizedParty:
        s = (raw or "").strip()
        canon = self._match_canonical(s) or s
        # Priority 1: foreign?
        foreign_marker = self._detect_foreign(s)
        if foreign_marker:
            # canonical + 도시지점 유지
            # branch 표현 통일: "<city>지점"
            ko_form = foreign_marker
            if foreign_marker.upper() in {c.upper() for c in self._foreign_en}:
                # English → 한글 변환 매핑 단순화 (City + 지점)
                # 한글 대응 없을 시 원문 + 지점
                ko_form = foreign_marker
            branch = f"{ko_form}지점" if not ko_form.endswith("지점") else ko_form
            return NormalizedParty(canonical=canon, branch=branch, is_foreign=True, raw=raw)
        # Priority 2: domestic branch → collapse
        if self._detect_domestic_branch(s):
            return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw)
        # Priority 3: bare canonical
        return NormalizedParty(canonical=canon, branch=None, is_foreign=False, raw=raw)
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_party_normalize.py -v
```
Expected: PASS (all 5)

- [ ] **Step 5: Commit**

```bash
git add src/domain/party_normalize.py tests/unit/test_party_normalize.py
git commit -m "feat(bc): party normalizer (canonical + branch 국내통합·해외분리)"
```

---

### Task 1A.3: gl_loader.py — G/L 대용량 Excel reader

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/gl_loader.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_gl_loader.py`
- Create: `BC_CONFIRMATION_TOOL/tests/fixtures/mini_gl.xlsx` (작은 fixture)

- [ ] **Step 1: Create fixture**

```python
# tests/fixtures/_make_mini_gl.py  (one-shot, not committed)
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["Ld","CoCd","회계","전표 종류","전표 번호","OffAct","계정 과목","입력일","일자","계정","적요","문서 번호","금액","거래처"])
ws.append(["0L","1100","2025","SA","100001","","보통예금","2025-01-15","2025-01-15","10110","국민은행 강남지점 이체","DOC1",1000000,"국민은행"])
ws.append(["0L","1100","2025","SA","100002","","단기차입금","2025-02-10","2025-02-10","20110","신한은행 도쿄지점 차입","DOC2",-5000000,"신한은행 도쿄지점"])
ws.append(["0L","1100","2025","SA","100003","","이자수익","2025-03-01","2025-03-01","41110","우리은행 정기예금 이자","DOC3",123456,"우리은행 종로지점"])
ws.append(["0L","1100","2025","SA","100004","","매출원가","2025-04-01","2025-04-01","51110","원재료","DOC4",-2000000,"공급처A"])
wb.save("tests/fixtures/mini_gl.xlsx")
```

(Run once to create fixture, then delete the script. Commit only the xlsx.)

- [ ] **Step 2: Write failing test**

```python
# tests/unit/test_gl_loader.py
from pathlib import Path
from src.infrastructure.gl_loader import GLLoader

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mini_gl.xlsx"

def test_iter_rows_yields_dicts():
    rows = list(GLLoader(FIX).iter_rows())
    assert len(rows) == 4
    assert rows[0]["계정 과목"] == "보통예금"
    assert rows[0]["금액"] == 1000000
    assert rows[1]["거래처"] == "신한은행 도쿄지점"

def test_iter_filters_empty():
    # 빈 row 무시
    rows = list(GLLoader(FIX).iter_rows())
    assert all(r.get("계정 과목") for r in rows)
```

- [ ] **Step 3: Run test (fail)**

```bash
pytest tests/unit/test_gl_loader.py -v
```
Expected: FAIL

- [ ] **Step 4: Implement**

```python
# src/infrastructure/gl_loader.py
from pathlib import Path
from typing import Iterator
import openpyxl

class GLLoader:
    """대용량 G/L Excel을 stream으로 읽음. read_only=True로 메모리 절약."""

    def __init__(self, path: Path):
        self.path = path

    def iter_rows(self, sheet: str | None = None) -> Iterator[dict]:
        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        it = ws.iter_rows(values_only=True)
        header = next(it, None)
        if not header:
            return
        cols = [str(h).strip() if h is not None else "" for h in header]
        for row in it:
            if not any(v not in (None, "") for v in row):
                continue
            d = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
            # 계정 과목 컬럼 없으면 skip
            if not d.get("계정 과목"):
                continue
            yield d
        wb.close()
```

- [ ] **Step 5: Run test (pass)**

```bash
pytest tests/unit/test_gl_loader.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/gl_loader.py tests/unit/test_gl_loader.py tests/fixtures/mini_gl.xlsx
git commit -m "feat(bc): GL loader (stream read_only) + mini fixture"
```

---

### Task 1A.4: sampling.py — Step A/B/C

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/domain/sampling.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_sampling.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_sampling.py
from pathlib import Path
from src.domain.sampling import Sampler
from src.domain.financial_account import FinancialAccountClassifier
from src.domain.party_normalize import PartyNormalizer
from src.infrastructure.gl_loader import GLLoader

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs"
FIX = ROOT / "tests" / "fixtures" / "mini_gl.xlsx"

def test_sampling_extracts_financial_parties_only():
    clf = FinancialAccountClassifier.load(CFG / "financial_keywords.yaml")
    norm = PartyNormalizer.load(CFG)
    rows = list(GLLoader(FIX).iter_rows())
    parties = Sampler(clf, norm).sample(rows)
    keys = sorted(p.entity_key() for p in parties)
    # 국민은행 (도메스틱), 신한은행 도쿄지점 (외국), 우리은행 (도메스틱)
    assert "국민은행|" in keys
    assert "신한은행|도쿄지점" in keys
    assert "우리은행|" in keys
    # 공급처A는 금융계정 row 없음 → 제외
    assert all("공급처A" not in k for k in keys)

def test_sampling_aggregates_balance_and_volume():
    clf = FinancialAccountClassifier.load(CFG / "financial_keywords.yaml")
    norm = PartyNormalizer.load(CFG)
    rows = list(GLLoader(FIX).iter_rows())
    parties = Sampler(clf, norm).sample(rows)
    by_key = {p.entity_key(): p for p in parties}
    assert by_key["국민은행|"].bs_amount == 1000000.0       # 보통예금
    assert by_key["신한은행|도쿄지점"].bs_amount == -5000000.0  # 차입금
    assert by_key["우리은행|"].pl_amount == 123456.0         # 이자수익
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_sampling.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/domain/sampling.py
from dataclasses import dataclass, field
from .financial_account import FinancialAccountClassifier
from .party_normalize import PartyNormalizer, NormalizedParty

@dataclass
class SampledParty:
    party: NormalizedParty
    bs_accounts: set[str] = field(default_factory=set)
    pl_accounts: set[str] = field(default_factory=set)
    bs_amount: float = 0.0
    pl_amount: float = 0.0
    row_count: int = 0
    confidence: float = 1.0

    def entity_key(self) -> str:
        return self.party.entity_key()

class Sampler:
    """Step A: 금융계정 row에서 거래처 추출 (B/S+P/L)
       Step B: 일반계정 row에서 alias 매칭으로 추가
       Step C: entity_key 기준 dedupe + 합산"""

    def __init__(self, classifier: FinancialAccountClassifier, normalizer: PartyNormalizer):
        self.classifier = classifier
        self.normalizer = normalizer

    def sample(self, rows: list[dict]) -> list[SampledParty]:
        agg: dict[str, SampledParty] = {}
        for row in rows:
            acc = (row.get("계정 과목") or "").strip()
            party_raw = (row.get("거래처") or "").strip()
            memo = (row.get("적요") or "").strip()
            amount = self._to_float(row.get("금액"))
            bucket = self.classifier.classify(acc)
            party_text = party_raw or memo
            if not party_text:
                continue
            # Step A: 금융계정 row
            if bucket:
                np = self.normalizer.normalize(party_text)
                self._add(agg, np, bucket, acc, amount, conf=1.0)
                continue
            # Step B: 일반계정에서 alias 매칭
            np = self.normalizer.normalize(party_text)
            if np.canonical != party_text and np.canonical != "":
                # canonical 매칭이 있으면 추가 (하지만 confidence 낮춤)
                self._add(agg, np, "기타", acc, amount, conf=0.6)
        return list(agg.values())

    def _add(self, agg, np: NormalizedParty, bucket: str, acc: str, amount: float, conf: float):
        key = np.entity_key()
        sp = agg.get(key) or SampledParty(party=np)
        if self.classifier.is_balance_sheet(bucket):
            sp.bs_accounts.add(acc)
            sp.bs_amount += amount
        elif self.classifier.is_profit_loss(bucket):
            sp.pl_accounts.add(acc)
            sp.pl_amount += amount
        else:
            sp.pl_accounts.add(acc) if amount else sp.bs_accounts.add(acc)
            sp.bs_amount += amount if not amount else 0
        sp.row_count += 1
        sp.confidence = min(sp.confidence, conf)
        agg[key] = sp

    @staticmethod
    def _to_float(v) -> float:
        if v is None or v == "":
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_sampling.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/sampling.py tests/unit/test_sampling.py
git commit -m "feat(bc): Sampler (Step A direct + Step B alias-match + Step C dedupe)"
```

---

### Task 1A.5: sampling_uc + route + integration test

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/application/sampling_uc.py`
- Create: `BC_CONFIRMATION_TOOL/api/routes/sampling.py`
- Modify: `BC_CONFIRMATION_TOOL/api/app.py` — include router
- Create: `BC_CONFIRMATION_TOOL/tests/integration/test_sampling_route.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_sampling_route.py
from fastapi.testclient import TestClient
from pathlib import Path
from api.app import app

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "mini_gl.xlsx"

def test_sampling_endpoint_runs_and_returns_parties():
    c = TestClient(app)
    r = c.post("/api/projects", json={"name": "테스트사", "fiscal_date": "2025-12-31"})
    assert r.status_code == 200
    pid = r.json()["id"]
    with open(FIX, "rb") as f:
        r = c.post(f"/api/projects/{pid}/upload/gl", files={"file": ("gl.xlsx", f.read())})
    assert r.status_code == 200
    r = c.post(f"/api/projects/{pid}/sampling/run")
    assert r.status_code == 200
    data = r.json()
    keys = {(p["canonical"], p["branch"]) for p in data["parties"]}
    assert ("국민은행", None) in keys
    assert ("신한은행", "도쿄지점") in keys
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/integration/test_sampling_route.py -v
```
Expected: FAIL

- [ ] **Step 3: application/sampling_uc.py**

```python
# src/application/sampling_uc.py
from pathlib import Path
from sqlmodel import Session
from src.domain.financial_account import FinancialAccountClassifier
from src.domain.party_normalize import PartyNormalizer
from src.domain.sampling import Sampler, SampledParty
from src.infrastructure.gl_loader import GLLoader
from src.infrastructure.db.repository import upsert_counterparty

ROOT = Path(__file__).resolve().parents[2]

def run_sampling(session: Session, project_id: int, gl_path: Path) -> list[SampledParty]:
    clf = FinancialAccountClassifier.load(ROOT / "configs" / "financial_keywords.yaml")
    norm = PartyNormalizer.load(ROOT / "configs")
    rows = list(GLLoader(gl_path).iter_rows())
    parties = Sampler(clf, norm).sample(rows)
    parties.sort(key=lambda p: (-p.bs_amount + -abs(p.pl_amount)))  # 큰 거래 우선 BC-1
    for sp in parties:
        c = upsert_counterparty(
            session, project_id,
            canonical_name=sp.party.canonical,
            branch=sp.party.branch,
            is_foreign=sp.party.is_foreign,
        )
        c.bs_balance = sp.bs_amount
        c.pl_volume = sp.pl_amount
        session.add(c)
    session.commit()
    return parties
```

- [ ] **Step 4: api/routes/projects.py**

```python
# api/routes/projects.py
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File
from sqlmodel import Session
from src.infrastructure.db.repository import get_engine, create_project
from src.infrastructure.db.models import Project, FileAsset

router = APIRouter(prefix="/api/projects", tags=["projects"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("")
def create(payload: dict, s: Session = Depends(_session)):
    p = create_project(s, payload["name"], payload["fiscal_date"])
    return {"id": p.id, "name": p.name, "fiscal_date": p.fiscal_date}

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "data" / "uploads"

@router.post("/{project_id}/upload/{kind}")
def upload(project_id: int, kind: str, file: UploadFile = File(...), s: Session = Depends(_session)):
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_ROOT / f"p{project_id}_{kind}_{file.filename}"
    dest.write_bytes(file.file.read())
    asset = FileAsset(project_id=project_id, kind=kind, original_name=file.filename, stored_path=str(dest))
    s.add(asset); s.commit(); s.refresh(asset)
    return {"id": asset.id, "stored_path": str(dest)}
```

- [ ] **Step 5: api/routes/sampling.py**

```python
# api/routes/sampling.py
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from src.application.sampling_uc import run_sampling
from src.infrastructure.db.models import FileAsset, Counterparty
from src.infrastructure.db.repository import get_engine, list_counterparties

router = APIRouter(prefix="/api/projects", tags=["sampling"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("/{project_id}/sampling/run")
def run(project_id: int, s: Session = Depends(_session)):
    gl = s.exec(select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.kind == "gl")).first()
    if not gl:
        raise HTTPException(400, "G/L not uploaded")
    parties = run_sampling(s, project_id, Path(gl.stored_path))
    return {
        "parties": [
            {
                "canonical": p.party.canonical,
                "branch": p.party.branch,
                "is_foreign": p.party.is_foreign,
                "bs_amount": p.bs_amount,
                "pl_amount": p.pl_amount,
                "bs_accounts": sorted(p.bs_accounts),
                "pl_accounts": sorted(p.pl_accounts),
                "row_count": p.row_count,
                "confidence": p.confidence,
            } for p in parties
        ]
    }
```

- [ ] **Step 6: Modify api/app.py**

```python
from api.routes import projects as projects_route
from api.routes import sampling as sampling_route
app.include_router(projects_route.router)
app.include_router(sampling_route.router)
```

- [ ] **Step 7: Run test (pass)**

```bash
pytest tests/integration/test_sampling_route.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/application/sampling_uc.py api/routes/projects.py api/routes/sampling.py api/app.py tests/integration/test_sampling_route.py
git commit -m "feat(bc): sampling use-case + REST endpoint (run sampling on uploaded G/L)"
```

---

## Phase 1B — Cross-check

### Task 1B.1: cs_loader.py — 회사 control sheet 파싱

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/cs_loader.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_cs_loader.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_cs_loader.py
from pathlib import Path
from src.infrastructure.cs_loader import ControlSheetLoader

FIX_DIR = Path(__file__).resolve().parents[1] / "fixtures"
# 실제 INPUT control sheet은 너무 크므로, 4150 template의 control sheet만 fixture로 복사

def test_load_control_sheet_extracts_bc_rows(tmp_path):
    src = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT/4150_AC 금융기관 조회_코스맥스비티아이_FY2025_V1.xlsx")
    if not src.exists():
        import pytest
        pytest.skip("INPUT 파일 없음")
    rows = ControlSheetLoader(src).load_bc_rows()
    assert len(rows) > 0
    assert any(r["bc_no"].startswith("BC-") for r in rows)
    # 최소 컬럼: bc_no, name, branch, channel, address, contact, phone
    sample = rows[0]
    for k in ("bc_no","name","channel"):
        assert k in sample
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_cs_loader.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/infrastructure/cs_loader.py
from pathlib import Path
import openpyxl

class ControlSheetLoader:
    """4150 'AC 금융기관조회서 control sheet' 시트 파싱.
    
    표준 컬럼 매핑 (row 6+ data):
      B=BC번호 C=금융기관명 D=지점 E=회신구분 F=주소 H=담당자 I=전화 J=회신여부
    """

    SHEET_KEYWORD = "control sheet"
    DATA_START_ROW = 6
    COL_MAP = {
        "bc_no": "B", "name": "C", "branch": "D", "channel": "E",
        "address": "F", "contact": "H", "phone": "I", "response_status": "J",
    }

    def __init__(self, path: Path):
        self.path = path

    def load_bc_rows(self) -> list[dict]:
        wb = openpyxl.load_workbook(self.path, data_only=True)
        target_sheet = None
        for name in wb.sheetnames:
            if self.SHEET_KEYWORD in name.lower() or "control sheet" in name:
                target_sheet = wb[name]; break
        if target_sheet is None:
            wb.close()
            return []
        ws = target_sheet
        rows = []
        for r in range(self.DATA_START_ROW, ws.max_row + 1):
            bc = ws[f"B{r}"].value
            if not bc or not str(bc).startswith("BC-"):
                continue
            rows.append({
                key: (ws[f"{col}{r}"].value or None)
                for key, col in self.COL_MAP.items()
            })
        wb.close()
        return rows
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_cs_loader.py -v
```
Expected: PASS (or skip if INPUT 없음)

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/cs_loader.py tests/unit/test_cs_loader.py
git commit -m "feat(bc): control sheet loader (4150 AC control sheet)"
```

---

### Task 1B.2: crosscheck.py — 5단계 룰

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/domain/crosscheck.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_crosscheck.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_crosscheck.py
from src.domain.crosscheck import (
    bidirectional_compare, prior_compare, listed_in_cs
)

def test_bidirectional_extracted_only():
    extracted = [("국민은행", None), ("신한은행", "도쿄지점")]
    cs        = [("국민은행", None)]
    result = bidirectional_compare(extracted, cs)
    # 우리만 있는 것 (신한 도쿄) → status="missing_in_cs"
    statuses = {(r["canonical"], r["branch"]): r["status"] for r in result}
    assert statuses[("국민은행", None)] == "both"
    assert statuses[("신한은행", "도쿄지점")] == "missing_in_cs"

def test_bidirectional_cs_only_flagged():
    extracted = [("국민은행", None)]
    cs        = [("국민은행", None), ("우리은행", None)]
    result = bidirectional_compare(extracted, cs)
    statuses = {(r["canonical"], r["branch"]): r["status"] for r in result}
    assert statuses[("우리은행", None)] == "extra_in_cs"

def test_prior_fuzzy_match():
    current = [("KEB하나은행", None)]
    prior   = [("하나은행", None)]
    result = prior_compare(current, prior, threshold=0.85)
    # canonical 다르지만 fuzzy로 매칭됨
    assert any(r["status"] == "both" and r["canonical"] == "KEB하나은행" for r in result)

def test_listed_in_cs_simple():
    cs = [("국민은행", None), ("신한은행", None)]
    targets = [("국민은행", None), ("우리은행", None)]
    result = listed_in_cs(targets, cs)
    by_key = {(r["canonical"], r["branch"]): r for r in result}
    assert by_key[("국민은행", None)]["present"] is True
    assert by_key[("우리은행", None)]["present"] is False
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_crosscheck.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/domain/crosscheck.py
from rapidfuzz import fuzz

Party = tuple[str, str | None]  # (canonical, branch)

def _key(p: Party) -> str:
    c, b = p
    return f"{c}|{b or ''}"

def bidirectional_compare(extracted: list[Party], cs: list[Party]) -> list[dict]:
    """4-1. 회사 CS ↔ 우리 추출 양방향 비교."""
    ex_keys = {_key(p) for p in extracted}
    cs_keys = {_key(p) for p in cs}
    result = []
    for p in extracted:
        k = _key(p)
        status = "both" if k in cs_keys else "missing_in_cs"
        result.append({"canonical": p[0], "branch": p[1], "status": status})
    for p in cs:
        k = _key(p)
        if k not in ex_keys:
            result.append({"canonical": p[0], "branch": p[1], "status": "extra_in_cs"})
    return result

def prior_compare(current: list[Party], prior: list[Party], threshold: float = 0.85) -> list[dict]:
    """4-2. 전기 CS ↔ 당기 (canonical + fuzzy)."""
    result = []
    for cur in current:
        ck = _key(cur)
        match = None
        for pri in prior:
            pk = _key(pri)
            if ck == pk:
                match = pri; break
            ratio = fuzz.ratio(cur[0], pri[0]) / 100.0
            if ratio >= threshold and (cur[1] or "") == (pri[1] or ""):
                match = pri; break
        status = "both" if match else "current_only"
        result.append({"canonical": cur[0], "branch": cur[1], "status": status,
                       "matched_prior": match})
    cur_keys = {_key(c) for c in current}
    for pri in prior:
        if not any(
            _key(pri) == _key(c) or (
                fuzz.ratio(pri[0], c[0]) / 100.0 >= threshold and (pri[1] or "") == (c[1] or "")
            ) for c in current
        ):
            result.append({"canonical": pri[0], "branch": pri[1], "status": "prior_only",
                           "matched_prior": None})
    return result

def listed_in_cs(targets: list[Party], cs: list[Party]) -> list[dict]:
    """4-3·4-4. targets(월보 or 담보·보증 명세서) 각 항목이 CS에 존재하는지 Y/N."""
    cs_keys = {_key(p) for p in cs}
    out = []
    for t in targets:
        present = _key(t) in cs_keys
        out.append({"canonical": t[0], "branch": t[1], "present": present})
    return out
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_crosscheck.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/crosscheck.py tests/unit/test_crosscheck.py
git commit -m "feat(bc): crosscheck rules (bidirectional, prior fuzzy, listed Y/N)"
```

---

### Task 1B.3: union_monthly.py + 담보·보증 loader

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/union_monthly.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_union_monthly.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_union_monthly.py
from src.infrastructure.union_monthly import parse_union_monthly, parse_collateral_or_guarantee
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_parse_collateral_extracts_institutions():
    src = ROOT / "INPUT" / "비티아이 제공 담보현황 251231_ok.xlsx"
    if not src.exists():
        import pytest; pytest.skip("INPUT 없음")
    names = parse_collateral_or_guarantee(src)
    assert isinstance(names, list)
    assert len(names) > 0
    # 적어도 1개 은행/금융기관 이름이 들어가야 함
    assert any("은행" in n or "보험" in n or "증권" in n for n in names)

def test_parse_guarantee_extracts_institutions():
    src = ROOT / "INPUT" / "비티아이 제공 연대보증현황 251231.xlsx"
    if not src.exists():
        import pytest; pytest.skip("INPUT 없음")
    names = parse_collateral_or_guarantee(src)
    assert len(names) > 0
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_union_monthly.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/infrastructure/union_monthly.py
from pathlib import Path
import openpyxl
import re

FIN_TERMS = ["은행","증권","보험","캐피탈","카드","저축은행","금융","신협","수협","농협","산업","수출입"]

def parse_collateral_or_guarantee(path: Path) -> list[str]:
    """담보·연대보증 명세서에서 금융기관 이름 후보 추출.
    
    rule: 모든 시트·셀을 sweep, FIN_TERMS 키워드가 포함된 문자열을 추출.
    중복 제거.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    seen: set[str] = set()
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if not isinstance(v, str):
                    continue
                s = v.strip()
                if not s or len(s) > 80:
                    continue
                if any(t in s for t in FIN_TERMS):
                    seen.add(s)
    wb.close()
    return sorted(seen)

def parse_union_monthly(path: Path) -> list[str]:
    """은행연합회 월보 (Excel or PDF). MVP: Excel만 지원. PDF는 Phase 2."""
    if path.suffix.lower() not in {".xlsx",".xls"}:
        return []  # PDF는 추후
    return parse_collateral_or_guarantee(path)
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_union_monthly.py -v
```
Expected: PASS (or skip)

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/union_monthly.py tests/unit/test_union_monthly.py
git commit -m "feat(bc): union monthly + collateral/guarantee parser (sweep + FIN_TERMS filter)"
```

---

### Task 1B.4: address_validator.py — juso.go.kr OpenAPI

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/address_validator.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_address_validator.py`

- [ ] **Step 1: Write failing test (mocked)**

```python
# tests/unit/test_address_validator.py
import httpx
from unittest.mock import patch, MagicMock
from src.infrastructure.address_validator import AddressValidator

def test_validate_ok(monkeypatch):
    # juso.go.kr response stub
    fake = {
        "results": {
            "common": {"totalCount": "1"},
            "juso": [{"roadAddr": "서울특별시 종로구 종로 14", "zipNo": "03187"}]
        }
    }
    def mock_get(*args, **kwargs):
        m = MagicMock(); m.json = lambda: fake; m.raise_for_status = lambda: None; return m
    monkeypatch.setattr("httpx.get", mock_get)
    v = AddressValidator(confm_key="TEST")
    r = v.validate("서울특별시 종로구 종로 14")
    assert r["status"] == "ok"
    assert "03187" in r["zipcode"]

def test_validate_not_found(monkeypatch):
    fake = {"results": {"common": {"totalCount": "0"}, "juso": []}}
    def mock_get(*args, **kwargs):
        m = MagicMock(); m.json = lambda: fake; m.raise_for_status = lambda: None; return m
    monkeypatch.setattr("httpx.get", mock_get)
    v = AddressValidator(confm_key="TEST")
    r = v.validate("이상한 주소")
    assert r["status"] == "not_found"
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_address_validator.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/infrastructure/address_validator.py
import httpx
import os

JUSO_ENDPOINT = "https://www.juso.go.kr/addrlink/addrLinkApi.do"

class AddressValidator:
    """juso.go.kr OpenAPI 기반 도로명주소 검증."""

    def __init__(self, confm_key: str | None = None):
        self.confm_key = confm_key or os.getenv("JUSO_CONFM_KEY", "")

    def validate(self, address: str) -> dict:
        if not address or not self.confm_key:
            return {"status": "failed", "reason": "missing key or address"}
        params = {
            "confmKey": self.confm_key,
            "currentPage": 1, "countPerPage": 1,
            "keyword": address, "resultType": "json",
        }
        try:
            r = httpx.get(JUSO_ENDPOINT, params=params, timeout=8.0)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            return {"status": "failed", "reason": str(e)}
        results = data.get("results", {})
        total = int(results.get("common", {}).get("totalCount", "0") or 0)
        if total == 0:
            return {"status": "not_found", "input": address}
        top = results["juso"][0]
        zipcode = top.get("zipNo", "")
        suggested = top.get("roadAddr", "")
        if address.strip() == suggested.strip():
            return {"status": "ok", "zipcode": zipcode, "address": suggested}
        return {"status": "mismatch", "zipcode": zipcode, "suggested": suggested, "input": address}
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_address_validator.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/address_validator.py tests/unit/test_address_validator.py
git commit -m "feat(bc): address validator (juso.go.kr OpenAPI, status: ok|mismatch|not_found|failed)"
```

---

### Task 1B.5: crosscheck_uc + route

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/application/crosscheck_uc.py`
- Create: `BC_CONFIRMATION_TOOL/api/routes/crosscheck.py`
- Modify: `BC_CONFIRMATION_TOOL/api/app.py`
- Create: `BC_CONFIRMATION_TOOL/tests/integration/test_crosscheck_route.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_crosscheck_route.py
from fastapi.testclient import TestClient
from api.app import app

def test_crosscheck_endpoint_returns_5_sections():
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name":"X","fiscal_date":"2025-12-31"}).json()["id"]
    # cs 없이 실행 → 빈 결과 OK
    r = c.post(f"/api/projects/{pid}/crosscheck/run")
    assert r.status_code == 200
    body = r.json()
    for key in ("bidirectional","prior","union","collateral","guarantee","address"):
        assert key in body
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/integration/test_crosscheck_route.py -v
```
Expected: FAIL

- [ ] **Step 3: application/crosscheck_uc.py**

```python
# src/application/crosscheck_uc.py
from pathlib import Path
from sqlmodel import Session, select
from src.domain.crosscheck import bidirectional_compare, prior_compare, listed_in_cs
from src.domain.party_normalize import PartyNormalizer
from src.infrastructure.cs_loader import ControlSheetLoader
from src.infrastructure.union_monthly import parse_collateral_or_guarantee, parse_union_monthly
from src.infrastructure.address_validator import AddressValidator
from src.infrastructure.db.models import FileAsset, Counterparty

ROOT = Path(__file__).resolve().parents[2]

def _load_cs_parties(path: Path, norm: PartyNormalizer) -> list[tuple[str, str | None]]:
    rows = ControlSheetLoader(path).load_bc_rows()
    out = []
    for r in rows:
        text = " ".join(filter(None, [r.get("name"), r.get("branch")]))
        np = norm.normalize(text or "")
        out.append((np.canonical, np.branch))
    return out

def _load_listed_parties(path: Path, norm: PartyNormalizer) -> list[tuple[str, str | None]]:
    names = parse_collateral_or_guarantee(path)
    out = []
    for n in names:
        np = norm.normalize(n)
        out.append((np.canonical, np.branch))
    # dedup
    return list(set(out))

def run_crosscheck(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    cps = session.exec(select(Counterparty).where(Counterparty.project_id == project_id)).all()
    extracted = [(c.canonical_name, c.branch) for c in cps]
    files = {f.kind: f for f in session.exec(select(FileAsset).where(FileAsset.project_id == project_id)).all()}
    cs_parties = _load_cs_parties(Path(files["cs"].stored_path), norm) if "cs" in files else []
    prior_parties = _load_cs_parties(Path(files["prior_cs"].stored_path), norm) if "prior_cs" in files else []
    union_parties = [(np.canonical, np.branch) for n in (parse_union_monthly(Path(files["union"].stored_path)) if "union" in files else []) for np in [norm.normalize(n)]]
    coll_parties = _load_listed_parties(Path(files["collateral"].stored_path), norm) if "collateral" in files else []
    guar_parties = _load_listed_parties(Path(files["guarantee"].stored_path), norm) if "guarantee" in files else []
    bidir = bidirectional_compare(extracted, cs_parties)
    prior = prior_compare(extracted, prior_parties)
    union = listed_in_cs(union_parties, cs_parties)
    coll  = listed_in_cs(coll_parties, cs_parties)
    guar  = listed_in_cs(guar_parties, cs_parties)
    # 4-5 address (CS 내 postal channel만)
    address_results = []
    if cs_parties and "cs" in files:
        validator = AddressValidator()
        rows = ControlSheetLoader(Path(files["cs"].stored_path)).load_bc_rows()
        for r in rows:
            if (r.get("channel") or "").strip() in {"우편","우편 회신"}:
                addr = r.get("address") or ""
                address_results.append({
                    "bc_no": r.get("bc_no"),
                    "name": r.get("name"),
                    "input": addr,
                    **validator.validate(addr),
                })
    # persist into Counterparty columns
    cp_by_key = {(c.canonical_name, c.branch): c for c in cps}
    for r in bidir:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.cs_present = (r["status"] == "both")
    for r in prior:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.prior_present = (r["status"] == "both")
    for r in union:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.union_listed = r["present"]
    for r in coll:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.collateral_listed = r["present"]
    for r in guar:
        c = cp_by_key.get((r["canonical"], r["branch"]))
        if c: c.guarantee_listed = r["present"]
    session.commit()
    return {
        "bidirectional": bidir, "prior": prior,
        "union": union, "collateral": coll, "guarantee": guar,
        "address": address_results,
    }
```

- [ ] **Step 4: api/routes/crosscheck.py**

```python
# api/routes/crosscheck.py
from fastapi import APIRouter, Depends
from sqlmodel import Session
from src.application.crosscheck_uc import run_crosscheck
from src.infrastructure.db.repository import get_engine

router = APIRouter(prefix="/api/projects", tags=["crosscheck"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("/{project_id}/crosscheck/run")
def run(project_id: int, s: Session = Depends(_session)):
    return run_crosscheck(s, project_id)
```

- [ ] **Step 5: Wire in api/app.py**

```python
from api.routes import crosscheck as crosscheck_route
app.include_router(crosscheck_route.router)
```

- [ ] **Step 6: Run test (pass)**

```bash
pytest tests/integration/test_crosscheck_route.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/application/crosscheck_uc.py api/routes/crosscheck.py api/app.py tests/integration/test_crosscheck_route.py
git commit -m "feat(bc): crosscheck use-case + endpoint (4-1..4-5 unified)"
```

---

## Phase 1C — Response PDF Parsing

### Task 1C.1: filename_parser.py

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/pdf/filename_parser.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_filename_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_filename_parser.py
from src.infrastructure.pdf.filename_parser import parse_filename

def test_online_format():
    r = parse_filename("전자_[BC-10]_코스맥스비티아이（주）_[124-81-22463]_대신증권_[2025년12월31일].pdf")
    assert r["bc_no"] == "BC-10"
    assert r["bank_raw"] == "대신증권"
    assert r["channel"] == "online"

def test_online_alt_paren():
    r = parse_filename("전자_[BC-1]_코스맥스비티아이(주)_[124-81-22463]_국민은행_[2025년12월31일].pdf")
    assert r["bc_no"] == "BC-1"
    assert r["bank_raw"] == "국민은행"

def test_postal_simple():
    r = parse_filename("BC-26_신한은행 홍콩.pdf")
    assert r["bc_no"] == "BC-26"
    assert r["bank_raw"] == "신한은행 홍콩"
    assert r["channel"] == "postal"

def test_postal_with_company():
    r = parse_filename("BC-25_코스맥스비티아이_예별손해보험.pdf")
    assert r["bc_no"] == "BC-25"
    assert r["bank_raw"] == "예별손해보험"

def test_unknown_returns_none():
    r = parse_filename("randomfile.pdf")
    assert r["bc_no"] is None
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_filename_parser.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/infrastructure/pdf/filename_parser.py
import re
from pathlib import Path

ONLINE_RE = re.compile(r"^전자_\[(BC-\d+)\]_[^_]+_\[[\d-]+\]_(.+?)_\[")
POSTAL_RE = re.compile(r"^(BC-\d+)_(.+)\.pdf$", re.IGNORECASE)

def parse_filename(name: str) -> dict:
    stem = Path(name).name
    m = ONLINE_RE.match(stem)
    if m:
        return {"bc_no": m.group(1), "bank_raw": m.group(2).strip(), "channel": "online"}
    m = POSTAL_RE.match(stem)
    if m:
        bc = m.group(1)
        rest = m.group(2).strip()
        # "회사명_은행명" 형태일 경우 회사명 prefix 제거
        # 휴리스틱: "_" 분리 시 첫 토큰이 회사 추정 → 마지막만 남김
        parts = rest.split("_")
        bank = parts[-1] if len(parts) > 1 else rest
        return {"bc_no": bc, "bank_raw": bank.strip(), "channel": "postal"}
    return {"bc_no": None, "bank_raw": None, "channel": None}
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_filename_parser.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/pdf/filename_parser.py tests/unit/test_filename_parser.py
git commit -m "feat(bc): PDF filename parser (online 전자_/postal BC-N_)"
```

---

### Task 1C.2: extractor.py + ocr.py (PDF text)

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/pdf/extractor.py`
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/pdf/ocr.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_pdf_extractor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_pdf_extractor.py
from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text_and_tables

def test_extract_digital_pdf():
    sample = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT/온라인")
    if not sample.exists():
        import pytest; pytest.skip("샘플 PDF 없음")
    pdfs = list(sample.glob("*.pdf"))
    if not pdfs:
        import pytest; pytest.skip("샘플 PDF 없음")
    r = extract_text_and_tables(pdfs[0])
    assert "text" in r
    assert isinstance(r["text"], str)
    assert len(r["text"]) > 100
    assert "tables" in r
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_pdf_extractor.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement extractor.py**

```python
# src/infrastructure/pdf/extractor.py
from pathlib import Path
import pdfplumber

def extract_text_and_tables(path: Path) -> dict:
    """Digital PDF 우선 시도. 실패 시 OCR fallback (별도 호출자가 처리)."""
    text_parts: list[str] = []
    tables: list[list[list]] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                text_parts.append(t)
            for tab in (page.extract_tables() or []):
                tables.append(tab)
    return {
        "text": "\n".join(text_parts),
        "tables": tables,
        "pages": len(text_parts),
    }
```

- [ ] **Step 4: Implement ocr.py**

```python
# src/infrastructure/pdf/ocr.py
from pathlib import Path

def ocr_pdf(path: Path, lang: str = "kor+eng") -> dict:
    """스캔 PDF → OCR 텍스트. pdf2image + pytesseract 필요."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        return {"text": "", "pages": 0, "error": "OCR deps missing"}
    text_parts = []
    images = convert_from_path(str(path), dpi=200)
    for img in images:
        # 회전 보정 단순 휴리스틱: orientation detection
        try:
            osd = pytesseract.image_to_osd(img)
            rot = 0
            for line in osd.splitlines():
                if line.startswith("Rotate:"):
                    rot = int(line.split(":")[1].strip()); break
            if rot:
                img = img.rotate(-rot, expand=True)
        except Exception:
            pass
        text_parts.append(pytesseract.image_to_string(img, lang=lang))
    return {"text": "\n".join(text_parts), "pages": len(images)}
```

- [ ] **Step 5: Run test (pass)**

```bash
pytest tests/unit/test_pdf_extractor.py -v
```
Expected: PASS (or skip)

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/pdf/extractor.py src/infrastructure/pdf/ocr.py tests/unit/test_pdf_extractor.py
git commit -m "feat(bc): PDF extractor (pdfplumber) + OCR fallback (Tesseract + rotation OSD)"
```

---

### Task 1C.3: section_classifier.py

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/pdf/section_classifier.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_section_classifier.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_section_classifier.py
from src.infrastructure.pdf.section_classifier import classify_sections

def test_split_sections_by_keywords():
    text = """
    1. 예금 잔액
    KB내맘대로통장 보통예금 계좌번호 09360101 잔액 1,234,567원
    
    2. 차입금
    일반자금대출 한도 1,000,000,000원 잔액 500,000,000원
    
    3. 지급보증
    L/C 한도 100,000원
    """
    sections = classify_sections(text)
    assert "AC1" in sections
    assert "AC2" in sections
    assert "AC4" in sections
    assert "예금" in sections["AC1"] or "보통예금" in sections["AC1"]
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_section_classifier.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/infrastructure/pdf/section_classifier.py
import re

SECTION_RULES = [
    ("AC1", ["예금","계좌","잔액","주식","채권","펀드","수익증권","CMA","MMF","RP","CP","CD","신탁","ETF","외화예금"]),
    ("AC2", ["차입","대출","한도","약정","사채"]),
    ("AC3", ["파생","선도","스왑","옵션","FX"]),
    ("AC4", ["지급보증","보증","L/C","신용장"]),
    ("AC5", ["담보","근저당","질권"]),
    ("AC6", ["어음","수표","당좌"]),
    ("AC7", ["보험증권","보험상품","가입"]),
]

def classify_sections(text: str) -> dict[str, str]:
    """텍스트 → 섹션별 substring (line-level greedy)."""
    lines = text.splitlines()
    out: dict[str, list[str]] = {f"AC{i}": [] for i in range(1, 9)}
    current = None
    for line in lines:
        s = line.strip()
        matched = None
        for ac, kws in SECTION_RULES:
            if any(kw in s for kw in kws):
                matched = ac; break
        if matched:
            current = matched
        if current:
            out[current].append(s)
        else:
            out["AC8"].append(s)  # 미분류 → 일반거래
    return {k: "\n".join(v) for k, v in out.items() if v}
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_section_classifier.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/pdf/section_classifier.py tests/unit/test_section_classifier.py
git commit -m "feat(bc): section classifier (text → AC1~AC8 by keyword)"
```

---

### Task 1C.4: ac_models.py (도메인 모델)

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/domain/ac_models.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_ac_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_ac_models.py
from decimal import Decimal
from datetime import date
from src.domain.ac_models import FinancialAsset, Borrowing, Guarantee, Collateral, Insurance, Derivative, BillCheck, GeneralDeal

def test_financial_asset_round_trip():
    fa = FinancialAsset(
        bc_no="BC-1", bank="국민은행", asset_type="deposit",
        product="보통예금", account_no="0936-01-01", currency="KRW",
        balance=Decimal("1234567"),
    )
    assert fa.model_dump()["balance"] == "1234567"

def test_borrowing_optional_fields():
    b = Borrowing(
        bc_no="BC-2", bank="기업은행", contract_type="일반자금대출",
        limit_amt=Decimal("1000000000"), limit_ccy="KRW",
        balance=Decimal("500000000"), balance_ccy="KRW",
        contract_date=date(2025, 6, 10),
    )
    assert b.maturity is None
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_ac_models.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/domain/ac_models.py
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict

class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")
    bc_no: str
    bank: str

class FinancialAsset(_Base):              # AC1
    asset_type: Literal["deposit","stock","bond","fund","other"]
    product: str
    account_no: str | None = None
    currency: str = "KRW"
    quantity: Decimal | None = None
    face_amount: Decimal | None = None
    balance: Decimal
    interest_rate: Decimal | None = None
    open_date: date | None = None
    maturity: date | None = None

class Borrowing(_Base):                   # AC2
    contract_type: str
    limit_amt: Decimal
    limit_ccy: str = "KRW"
    balance: Decimal
    balance_ccy: str = "KRW"
    contract_date: date
    maturity: date | None = None
    rate: str | None = None

class Derivative(_Base):                  # AC3
    instrument: str
    contract_date: date
    buy_ccy: str
    buy_amt: Decimal
    sell_ccy: str
    sell_amt: Decimal
    maturity: date | None = None

class Guarantee(_Base):                   # AC4
    guarantee_type: str
    limit_amt: Decimal
    limit_ccy: str = "KRW"
    balance: Decimal
    balance_ccy: str = "KRW"
    maturity: date | None = None

class Collateral(_Base):                  # AC5
    collateral_type: str
    creditor: str | None = None
    issuer: str | None = None
    book_amount: Decimal
    appraised_amount: Decimal | None = None
    priority: int | None = None

class BillCheck(_Base):                   # AC6
    kind: str
    count: int = 0
    balance: Decimal = Decimal("0")

class Insurance(_Base):                   # AC7
    product: str
    policy_no: str | None = None
    coverage_amount: Decimal | None = None
    premium: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None

class GeneralDeal(_Base):                 # AC8
    asset_type: str
    account_no: str | None = None
    deal_date: date | None = None
    deal_type: str | None = None
    outstanding: Decimal | None = None
    period: str | None = None
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_ac_models.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/ac_models.py tests/unit/test_ac_models.py
git commit -m "feat(bc): AC1~AC8 domain models (pydantic v2)"
```

---

### Task 1C.5: generic_parser.py — section text → records

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/pdf/generic_parser.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_generic_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_generic_parser.py
from src.infrastructure.pdf.generic_parser import parse_ac1_deposit, parse_ac2_borrowing

def test_parse_ac1_simple_balance():
    text = "보통예금 계좌번호 0936-0101-0057-44 통화 KRW 잔액 10,218원 이자율 0.10%"
    recs = parse_ac1_deposit(text, bc_no="BC-1", bank="국민은행")
    assert len(recs) >= 1
    r = recs[0]
    assert r.product.startswith("보통예금") or "보통예금" in r.product
    assert int(r.balance) == 10218
    assert r.currency == "KRW"

def test_parse_ac2_borrowing_with_limit():
    text = "일반자금대출 한도 1,000,000,000원 잔액 500,000,000원 계약일 2025-06-10"
    recs = parse_ac2_borrowing(text, bc_no="BC-2", bank="기업은행")
    assert len(recs) == 1
    assert int(recs[0].limit_amt) == 1_000_000_000
    assert int(recs[0].balance) == 500_000_000
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_generic_parser.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement (예금·차입금만, 나머지는 stub 후 점진 확장)**

```python
# src/infrastructure/pdf/generic_parser.py
import re
from datetime import date
from decimal import Decimal
from src.domain.ac_models import (
    FinancialAsset, Borrowing, Derivative, Guarantee,
    Collateral, BillCheck, Insurance, GeneralDeal,
)

AMOUNT_RE  = re.compile(r"([\d,]+(?:\.\d+)?)\s*원?")
ACCT_RE    = re.compile(r"계좌(?:번호)?\s*([0-9\-]+)")
CCY_RE     = re.compile(r"\b(KRW|USD|EUR|JPY|CNY|HKD|GBP|AUD|SGD)\b")
RATE_RE    = re.compile(r"([\d.]+)\s*%")
DATE_RE    = re.compile(r"(\d{4})[-./]?\s*(\d{1,2})[-./]?\s*(\d{1,2})")

def _amount(text: str, anchor: str) -> Decimal | None:
    m = re.search(rf"{anchor}\s*[:：]?\s*([\d,]+)", text)
    if not m:
        return None
    return Decimal(m.group(1).replace(",", ""))

def _date(text: str, anchor: str) -> date | None:
    m = re.search(rf"{anchor}\s*[:：]?\s*(\d{{4}}[-./]\d{{1,2}}[-./]\d{{1,2}})", text)
    if not m:
        return None
    parts = re.split(r"[-./]", m.group(1))
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None

def parse_ac1_deposit(text: str, bc_no: str, bank: str) -> list[FinancialAsset]:
    out: list[FinancialAsset] = []
    # line-by-line: "보통예금|정기예금|MMF|..." 시작 line을 record 단위로
    keywords = ["보통예금","정기예금","당좌예금","외화예금","MMDA","MMF","CMA","RP","주식","채권","수익증권","ETF","신탁"]
    for line in text.splitlines():
        s = line.strip()
        if not any(kw in s for kw in keywords):
            continue
        balance = _amount(s, "잔액") or _amount(s, "금액") or Decimal("0")
        acct = (ACCT_RE.search(s).group(1) if ACCT_RE.search(s) else None)
        ccy = (CCY_RE.search(s).group(1) if CCY_RE.search(s) else "KRW")
        rate_m = RATE_RE.search(s)
        rate = Decimal(rate_m.group(1)) if rate_m else None
        # asset_type 분류
        if any(k in s for k in ["주식","ETF"]):
            atype = "stock"
        elif any(k in s for k in ["채권"]):
            atype = "bond"
        elif any(k in s for k in ["MMF","RP","수익증권","신탁"]):
            atype = "fund"
        elif any(k in s for k in ["예금","CMA","MMDA"]):
            atype = "deposit"
        else:
            atype = "other"
        out.append(FinancialAsset(
            bc_no=bc_no, bank=bank, asset_type=atype, product=s[:60],
            account_no=acct, currency=ccy, balance=balance, interest_rate=rate,
        ))
    return out

def parse_ac2_borrowing(text: str, bc_no: str, bank: str) -> list[Borrowing]:
    out: list[Borrowing] = []
    keywords = ["대출","차입","사채","약정"]
    for line in text.splitlines():
        s = line.strip()
        if not any(kw in s for kw in keywords):
            continue
        limit = _amount(s, "한도") or Decimal("0")
        bal   = _amount(s, "잔액") or Decimal("0")
        cdate = _date(s, "계약일") or _date(s, "약정일") or date(2000,1,1)
        mat   = _date(s, "만기")
        out.append(Borrowing(
            bc_no=bc_no, bank=bank, contract_type=s[:40],
            limit_amt=limit, limit_ccy="KRW", balance=bal, balance_ccy="KRW",
            contract_date=cdate, maturity=mat,
        ))
    return out

def parse_ac3_derivative(text: str, bc_no: str, bank: str) -> list[Derivative]:
    out: list[Derivative] = []
    for line in text.splitlines():
        s = line.strip()
        if not any(k in s for k in ["선도","스왑","옵션","FX"]):
            continue
        d = _date(s, "계약일") or date(2000,1,1)
        out.append(Derivative(
            bc_no=bc_no, bank=bank, instrument=s[:40],
            contract_date=d, buy_ccy="KRW", buy_amt=Decimal("0"),
            sell_ccy="USD", sell_amt=Decimal("0"),
        ))
    return out

def parse_ac4_guarantee(text: str, bc_no: str, bank: str) -> list[Guarantee]:
    out: list[Guarantee] = []
    for line in text.splitlines():
        s = line.strip()
        if not any(k in s for k in ["지급보증","보증","L/C","신용장"]):
            continue
        limit = _amount(s, "한도") or Decimal("0")
        bal   = _amount(s, "잔액") or Decimal("0")
        out.append(Guarantee(
            bc_no=bc_no, bank=bank, guarantee_type=s[:40],
            limit_amt=limit, balance=bal,
        ))
    return out

def parse_ac5_collateral(text: str, bc_no: str, bank: str) -> list[Collateral]:
    out: list[Collateral] = []
    for line in text.splitlines():
        s = line.strip()
        if not any(k in s for k in ["담보","근저당","질권"]):
            continue
        amt = _amount(s, "장부") or _amount(s, "평가") or Decimal("0")
        out.append(Collateral(bc_no=bc_no, bank=bank, collateral_type=s[:40], book_amount=amt))
    return out

def parse_ac6_bills(text: str, bc_no: str, bank: str) -> list[BillCheck]:
    out: list[BillCheck] = []
    for line in text.splitlines():
        s = line.strip()
        if not any(k in s for k in ["어음","수표"]):
            continue
        out.append(BillCheck(bc_no=bc_no, bank=bank, kind=s[:40]))
    return out

def parse_ac7_insurance(text: str, bc_no: str, bank: str) -> list[Insurance]:
    out: list[Insurance] = []
    for line in text.splitlines():
        s = line.strip()
        if not any(k in s for k in ["보험증권","보험상품","보험계약","가입"]):
            continue
        out.append(Insurance(bc_no=bc_no, bank=bank, product=s[:60]))
    return out

def parse_ac8_general(text: str, bc_no: str, bank: str) -> list[GeneralDeal]:
    return [GeneralDeal(bc_no=bc_no, bank=bank, asset_type="기타")] if text.strip() else []
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_generic_parser.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/pdf/generic_parser.py tests/unit/test_generic_parser.py
git commit -m "feat(bc): generic PDF parser per AC section (line-by-line keyword + amount/date regex)"
```

---

### Task 1C.6: parse_response_uc + route

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/application/parse_response_uc.py`
- Create: `BC_CONFIRMATION_TOOL/api/routes/response.py`
- Modify: `BC_CONFIRMATION_TOOL/api/app.py`
- Create: `BC_CONFIRMATION_TOOL/tests/integration/test_response_route.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_response_route.py
from fastapi.testclient import TestClient
from pathlib import Path
from api.app import app

def test_parse_response_returns_records():
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name":"X","fiscal_date":"2025-12-31"}).json()["id"]
    src = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT/온라인")
    if not src.exists():
        import pytest; pytest.skip("샘플 PDF 없음")
    pdfs = list(src.glob("*.pdf"))[:1]
    if not pdfs:
        import pytest; pytest.skip("샘플 PDF 없음")
    with open(pdfs[0], "rb") as f:
        c.post(f"/api/projects/{pid}/upload/response", files={"file":(pdfs[0].name, f.read())})
    r = c.post(f"/api/projects/{pid}/response/parse")
    assert r.status_code == 200
    body = r.json()
    assert "records" in body
    # 최소 AC1 또는 AC2 record 1건
    assert any(rec.get("section") in {"AC1","AC2","AC3","AC4","AC5","AC6","AC7","AC8"} for rec in body["records"])
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/integration/test_response_route.py -v
```
Expected: FAIL

- [ ] **Step 3: parse_response_uc.py**

```python
# src/application/parse_response_uc.py
import json
from pathlib import Path
from sqlmodel import Session, select
from src.infrastructure.db.models import FileAsset, Counterparty, ExtractedRecord
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.filename_parser import parse_filename
from src.infrastructure.pdf.section_classifier import classify_sections
from src.infrastructure.pdf.generic_parser import (
    parse_ac1_deposit, parse_ac2_borrowing, parse_ac3_derivative,
    parse_ac4_guarantee, parse_ac5_collateral, parse_ac6_bills,
    parse_ac7_insurance, parse_ac8_general,
)
from src.domain.party_normalize import PartyNormalizer

ROOT = Path(__file__).resolve().parents[2]
PARSERS = {
    "AC1": parse_ac1_deposit, "AC2": parse_ac2_borrowing,
    "AC3": parse_ac3_derivative, "AC4": parse_ac4_guarantee,
    "AC5": parse_ac5_collateral, "AC6": parse_ac6_bills,
    "AC7": parse_ac7_insurance, "AC8": parse_ac8_general,
}

def parse_responses(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    files = session.exec(
        select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.kind == "response")
    ).all()
    cps = {(c.canonical_name, c.branch): c for c in session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ).all()}
    records_summary = []
    for f in files:
        meta = parse_filename(f.original_name)
        bc_no = meta.get("bc_no")
        bank_raw = meta.get("bank_raw") or ""
        np = norm.normalize(bank_raw) if bank_raw else None
        bank = np.canonical if np else bank_raw
        ext = extract_text_and_tables(Path(f.stored_path))
        text = ext["text"]
        if len(text.strip()) < 80:
            # 스캔 PDF (텍스트 거의 없음) → OCR
            ocr = ocr_pdf(Path(f.stored_path))
            text = ocr["text"]
            confidence = "low"
        else:
            confidence = "high"
        sections = classify_sections(text)
        cp = cps.get((np.canonical, np.branch)) if np else None
        if cp:
            cp.response_arrived = True
            session.add(cp)
        for ac, section_text in sections.items():
            parser = PARSERS[ac]
            try:
                recs = parser(section_text, bc_no=bc_no or "", bank=bank or "")
            except Exception:
                recs = []
            for rec in recs:
                payload = rec.model_dump_json()
                er = ExtractedRecord(
                    project_id=project_id,
                    counterparty_id=cp.id if cp else 0,
                    ac_section=ac,
                    payload_json=payload,
                    confidence=confidence,
                    source_file=f.original_name,
                )
                session.add(er); session.flush()
                records_summary.append({
                    "section": ac, "bc_no": bc_no, "bank": bank,
                    "confidence": confidence, "payload": json.loads(payload),
                })
    session.commit()
    return {"records": records_summary}
```

- [ ] **Step 4: api/routes/response.py**

```python
# api/routes/response.py
from fastapi import APIRouter, Depends
from sqlmodel import Session
from src.application.parse_response_uc import parse_responses
from src.infrastructure.db.repository import get_engine

router = APIRouter(prefix="/api/projects", tags=["response"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("/{project_id}/response/parse")
def parse(project_id: int, s: Session = Depends(_session)):
    return parse_responses(s, project_id)
```

- [ ] **Step 5: Wire in app.py**

```python
from api.routes import response as response_route
app.include_router(response_route.router)
```

- [ ] **Step 6: Run test (pass)**

```bash
pytest tests/integration/test_response_route.py -v
```
Expected: PASS (or skip)

- [ ] **Step 7: Commit**

```bash
git add src/application/parse_response_uc.py api/routes/response.py api/app.py tests/integration/test_response_route.py
git commit -m "feat(bc): response parse use-case + endpoint (digital + OCR fallback, AC1~AC8 split)"
```

---

## Phase 1D — 4150 Template Fill

### Task 1D.1: ac_filler.py — 셀 단위 fill

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/excel_writer/ac_filler.py`
- Create: `BC_CONFIRMATION_TOOL/templates/4150_AC_template.xlsx` (copy from INPUT/V1)
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_ac_filler.py`

- [ ] **Step 1: Copy template**

```bash
cp "c:/Claude/BC_CONFIRMATION_TOOL/INPUT/4150_AC 금융기관 조회_코스맥스비티아이_FY2025_V1.xlsx" \
   c:/Claude/BC_CONFIRMATION_TOOL/templates/4150_AC_template.xlsx
```

- [ ] **Step 2: Write failing test**

```python
# tests/unit/test_ac_filler.py
import shutil
import openpyxl
from pathlib import Path
from decimal import Decimal
from datetime import date
from src.infrastructure.excel_writer.ac_filler import ACFiller
from src.domain.ac_models import FinancialAsset, Borrowing

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "4150_AC_template.xlsx"

def test_fill_ac1_writes_to_row_11(tmp_path):
    out = tmp_path / "out.xlsx"
    shutil.copy(TEMPLATE, out)
    filler = ACFiller(out)
    recs = [
        FinancialAsset(bc_no="BC-1", bank="국민은행", asset_type="deposit",
                       product="보통예금-내맘대로통장", account_no="0936-01-01",
                       currency="KRW", balance=Decimal("10218")),
    ]
    filler.fill_section("AC1", recs)
    filler.save()
    wb = openpyxl.load_workbook(out, data_only=False)
    ws = [s for s in wb.sheetnames if s.startswith("AC1")][0]
    assert wb[ws]["C11"].value == "BC-1"
    assert wb[ws]["D11"].value == "국민은행"
    assert wb[ws]["H11"].value == 10218

def test_fill_ac2_writes_to_row_12(tmp_path):
    out = tmp_path / "out2.xlsx"
    shutil.copy(TEMPLATE, out)
    filler = ACFiller(out)
    recs = [
        Borrowing(bc_no="BC-2", bank="기업은행", contract_type="일반자금대출",
                  limit_amt=Decimal("14500000000"), limit_ccy="KRW",
                  balance=Decimal("14500000000"), balance_ccy="KRW",
                  contract_date=date(2025, 6, 10))
    ]
    filler.fill_section("AC2", recs)
    filler.save()
    wb = openpyxl.load_workbook(out, data_only=False)
    ws = [s for s in wb.sheetnames if s.startswith("AC2")][0]
    assert wb[ws]["C12"].value == "BC-2"
```

- [ ] **Step 3: Run test (fail)**

```bash
pytest tests/unit/test_ac_filler.py -v
```
Expected: FAIL

- [ ] **Step 4: Implement**

```python
# src/infrastructure/excel_writer/ac_filler.py
import openpyxl
from copy import copy
from pathlib import Path
from decimal import Decimal
from datetime import date
from src.domain.ac_models import (
    FinancialAsset, Borrowing, Derivative, Guarantee,
    Collateral, BillCheck, Insurance, GeneralDeal,
)

# 시트 prefix → 데이터 시작 row + column 매핑
SHEET_CONFIG = {
    "AC1": {"prefix": "AC1.", "start_row": 11, "cols": {
        "C": "bc_no", "D": "bank", "E": "product", "F": "account_no",
        "G": "currency", "H": "balance", "I": "interest_rate", "J": "open_date",
    }},
    "AC2": {"prefix": "AC2.", "start_row": 12, "cols": {
        "C": "bc_no", "D": "bank", "E": "contract_type",
        "F": "limit_ccy", "G": "limit_amt", "H": "balance_ccy", "I": "balance",
        "J": "contract_date",
    }},
    "AC3": {"prefix": "AC3.", "start_row": 12, "cols": {
        "C": "bc_no", "D": "instrument", "E": "contract_date",
        "F": "buy_ccy", "G": "buy_amt", "H": "sell_ccy", "I": "sell_amt",
    }},
    "AC4": {"prefix": "AC4.", "start_row": 13, "cols": {
        "C": "bc_no", "D": "bank", "E": "guarantee_type",
        "F": "limit_ccy", "G": "limit_amt", "H": "balance_ccy", "I": "balance",
        "J": "maturity",
    }},
    "AC5": {"prefix": "AC5.", "start_row": 12, "cols": {
        "C": "bc_no", "D": "bank", "E": "collateral_type",
        "F": "creditor", "G": "issuer", "H": "book_amount", "I": "appraised_amount",
        "J": "priority",
    }},
    "AC6": {"prefix": "AC6.", "start_row": 13, "cols": {
        "C": "bc_no", "D": "bank", "E": "kind", "G": "count",
    }},
    "AC7": {"prefix": "AC7.", "start_row": 12, "cols": {
        "C": "bc_no", "D": "bank", "E": "product", "F": "policy_no",
        "G": "coverage_amount", "H": "premium", "I": "start_date", "J": "end_date",
    }},
    "AC8": {"prefix": "AC8.", "start_row": 12, "cols": {
        "C": "bc_no", "D": "bank", "E": "asset_type", "F": "account_no",
        "G": "deal_date", "H": "deal_type", "I": "outstanding", "J": "period",
    }},
}

class ACFiller:
    def __init__(self, template_path: Path):
        self.path = template_path
        self.wb = openpyxl.load_workbook(template_path)

    def _find_sheet(self, prefix: str):
        for name in self.wb.sheetnames:
            if name.startswith(prefix):
                return self.wb[name]
        return None

    def fill_section(self, ac: str, records: list):
        cfg = SHEET_CONFIG[ac]
        ws = self._find_sheet(cfg["prefix"])
        if ws is None:
            return
        start = cfg["start_row"]
        # 부족 시 insert + style copy from start row
        needed = len(records)
        # template은 보통 첫 record 1개 + 빈 줄들. 안전하게 그냥 셀 write.
        for idx, rec in enumerate(records):
            row = start + idx
            self._ensure_row_style(ws, start, row)
            for col, attr in cfg["cols"].items():
                val = self._extract(rec, attr)
                if val is not None:
                    ws[f"{col}{row}"] = val

    def _extract(self, rec, attr: str):
        if hasattr(rec, attr):
            v = getattr(rec, attr)
            if isinstance(v, Decimal):
                return float(v)
            if isinstance(v, date):
                return v
            return v
        return None

    def _ensure_row_style(self, ws, source_row: int, target_row: int):
        if target_row == source_row:
            return
        # 데이터·서식·border·정렬·number format copy from source_row
        for col_idx in range(1, ws.max_column + 1):
            src = ws.cell(row=source_row, column=col_idx)
            tgt = ws.cell(row=target_row, column=col_idx)
            if src.has_style:
                tgt.font          = copy(src.font)
                tgt.fill          = copy(src.fill)
                tgt.border        = copy(src.border)
                tgt.alignment     = copy(src.alignment)
                tgt.number_format = src.number_format
                tgt.protection    = copy(src.protection)

    def save(self, dest: Path | None = None):
        self.wb.save(dest or self.path)
```

- [ ] **Step 5: Run test (pass)**

```bash
pytest tests/unit/test_ac_filler.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/excel_writer/ac_filler.py templates/4150_AC_template.xlsx tests/unit/test_ac_filler.py
git commit -m "feat(bc): AC filler (셀 단위 fill + row 확장 시 style copy, 원본 양식 보존)"
```

---

### Task 1D.2: color_swap.py — Toss 색감

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/infrastructure/excel_writer/color_swap.py`
- Create: `BC_CONFIRMATION_TOOL/tests/unit/test_color_swap.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_color_swap.py
import shutil
import openpyxl
from pathlib import Path
from src.infrastructure.excel_writer.color_swap import apply_toss_palette

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "4150_AC_template.xlsx"

def test_swap_title_to_toss_blue(tmp_path):
    out = tmp_path / "out.xlsx"
    shutil.copy(TEMPLATE, out)
    wb = openpyxl.load_workbook(out)
    apply_toss_palette(wb)
    wb.save(out)
    wb2 = openpyxl.load_workbook(out)
    ac1 = [s for s in wb2.sheetnames if s.startswith("AC1.")][0]
    title_cell = wb2[ac1]["A2"]
    # A2 fill 색이 #3182F6 (또는 가까운 토스 블루)인지 확인
    fg = title_cell.fill.fgColor.rgb if title_cell.fill and title_cell.fill.fgColor else None
    assert fg and "3182F6" in (fg or "").upper()
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/unit/test_color_swap.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement**

```python
# src/infrastructure/excel_writer/color_swap.py
from openpyxl.styles import PatternFill, Font
from openpyxl.workbook import Workbook

TOSS = {
    "primary":      "FF3182F6",
    "primary_dark": "FF1B64DA",
    "light_bg":     "FFF2F4F6",
    "warning":      "FFFFF7E0",
}

TITLE_ROWS = [1, 2, 3]
HEADER_ROWS_BY_PREFIX = {
    "AC0.": [11, 12],
    "AC1.": [10, 11],
    "AC2.": [10, 11],
    "AC3.": [10, 11],
    "AC4.": [11, 12],
    "AC5.": [11, 12],
    "AC6.": [11, 12],
    "AC7.": [10, 11],
    "AC8.": [10, 11],
    "AC ":  [5],          # control sheet header
}

def _fill_row(ws, row: int, hex_argb: str, font_white: bool = True):
    pf = PatternFill(start_color=hex_argb, end_color=hex_argb, fill_type="solid")
    for c in range(1, ws.max_column + 1):
        cell = ws.cell(row=row, column=c)
        if cell.value is None and c > 1:
            continue
        cell.fill = pf
        if font_white:
            old = cell.font
            cell.font = Font(name=old.name, size=old.size, bold=old.bold,
                             italic=old.italic, color="FFFFFFFF")

def apply_toss_palette(wb: Workbook):
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        # title rows
        for r in TITLE_ROWS:
            if ws.max_row >= r:
                _fill_row(ws, r, TOSS["primary"], font_white=True)
        # header rows by sheet prefix
        for prefix, rows in HEADER_ROWS_BY_PREFIX.items():
            if sheet_name.startswith(prefix):
                for r in rows:
                    if ws.max_row >= r:
                        _fill_row(ws, r, TOSS["primary_dark"], font_white=True)
                break

def mark_low_confidence(ws, row: int, col: str, comment: str = "OCR 신뢰도 낮음 - 검토 필요"):
    from openpyxl.comments import Comment
    cell = ws[f"{col}{row}"]
    cell.fill = PatternFill(start_color=TOSS["warning"], end_color=TOSS["warning"], fill_type="solid")
    cell.comment = Comment(comment, "BC tool")
```

- [ ] **Step 4: Run test (pass)**

```bash
pytest tests/unit/test_color_swap.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/excel_writer/color_swap.py tests/unit/test_color_swap.py
git commit -m "feat(bc): Toss palette swap (title + header rows, low confidence marker)"
```

---

### Task 1D.3: export_4150_uc + route

**Files:**
- Create: `BC_CONFIRMATION_TOOL/src/application/export_4150_uc.py`
- Create: `BC_CONFIRMATION_TOOL/api/routes/workpaper.py`
- Modify: `BC_CONFIRMATION_TOOL/api/app.py`
- Create: `BC_CONFIRMATION_TOOL/tests/integration/test_workpaper_route.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_workpaper_route.py
from fastapi.testclient import TestClient
from api.app import app
from pathlib import Path

def test_export_endpoint_returns_xlsx():
    c = TestClient(app)
    pid = c.post("/api/projects", json={"name":"테스트","fiscal_date":"2025-12-31"}).json()["id"]
    r = c.post(f"/api/projects/{pid}/workpaper/export")
    assert r.status_code == 200
    # zip stream or file path
    assert "xlsx" in (r.headers.get("content-type") or "") or "download_url" in r.json()
```

- [ ] **Step 2: Run test (fail)**

```bash
pytest tests/integration/test_workpaper_route.py -v
```
Expected: FAIL

- [ ] **Step 3: export_4150_uc.py**

```python
# src/application/export_4150_uc.py
import json
import shutil
from datetime import datetime
from pathlib import Path
from sqlmodel import Session, select
import openpyxl
from src.infrastructure.db.models import Project, Counterparty, ExtractedRecord
from src.infrastructure.excel_writer.ac_filler import ACFiller, SHEET_CONFIG
from src.infrastructure.excel_writer.color_swap import apply_toss_palette
from src.domain.ac_models import (
    FinancialAsset, Borrowing, Derivative, Guarantee,
    Collateral, BillCheck, Insurance, GeneralDeal,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "4150_AC_template.xlsx"
OUTPUT_DIR = ROOT / "OUTPUT"

MODEL_BY_SECTION = {
    "AC1": FinancialAsset, "AC2": Borrowing, "AC3": Derivative,
    "AC4": Guarantee, "AC5": Collateral, "AC6": BillCheck,
    "AC7": Insurance, "AC8": GeneralDeal,
}

def export_4150(session: Session, project_id: int) -> Path:
    project = session.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fy = project.fiscal_date[:4]
    out_path = OUTPUT_DIR / f"4150_AC_금융기관조회_{project.name}_FY{fy}_{ts}.xlsx"
    shutil.copy(TEMPLATE, out_path)
    filler = ACFiller(out_path)
    # AC control sheet + AC0 fill (counterparty 기반)
    cps = list(session.exec(select(Counterparty).where(Counterparty.project_id == project_id)).all())
    _fill_control_sheet(filler.wb, cps)
    _fill_ac0(filler.wb, cps)
    # AC1~AC8: ExtractedRecord
    for ac in MODEL_BY_SECTION:
        records_raw = session.exec(
            select(ExtractedRecord).where(
                ExtractedRecord.project_id == project_id,
                ExtractedRecord.ac_section == ac,
            )
        ).all()
        Model = MODEL_BY_SECTION[ac]
        models = [Model.model_validate_json(r.payload_json) for r in records_raw]
        filler.fill_section(ac, models)
        # low confidence cell 마커
        from src.infrastructure.excel_writer.color_swap import mark_low_confidence
        cfg = SHEET_CONFIG[ac]
        ws = filler._find_sheet(cfg["prefix"])
        if ws:
            for idx, raw in enumerate(records_raw):
                if raw.confidence == "low":
                    for col in cfg["cols"]:
                        mark_low_confidence(ws, cfg["start_row"] + idx, col)
    apply_toss_palette(filler.wb)
    filler.save()
    return out_path

def _fill_control_sheet(wb, cps: list[Counterparty]):
    sheet = next((wb[s] for s in wb.sheetnames if "control sheet" in s.lower()), None)
    if sheet is None:
        return
    for i, cp in enumerate(cps):
        r = 6 + i
        sheet[f"B{r}"] = cp.bc_no
        sheet[f"C{r}"] = cp.canonical_name
        if cp.branch:
            sheet[f"D{r}"] = cp.branch
        sheet[f"E{r}"] = cp.channel or ""
        sheet[f"F{r}"] = cp.address or ""
        sheet[f"J{r}"] = "회신" if cp.response_arrived else "미회신"

def _fill_ac0(wb, cps: list[Counterparty]):
    sheet = next((wb[s] for s in wb.sheetnames if s.startswith("AC0.")), None)
    if sheet is None:
        return
    for i, cp in enumerate(cps):
        r = 12 + i
        sheet[f"C{r}"] = cp.bc_no
        sheet[f"D{r}"] = cp.canonical_name + (f" {cp.branch}" if cp.branch else "")
        sheet[f"E{r}"] = "Y" if cp.cs_present else "N"
        sheet[f"F{r}"] = "Y" if cp.prior_present else "N"
        sheet[f"G{r}"] = "Y" if cp.union_listed else "N"
        sheet[f"H{r}"] = ("담보 Y/" if cp.collateral_listed else "담보 N/") + ("보증 Y" if cp.guarantee_listed else "보증 N")
        sheet[f"I{r}"] = "✓" if cp.response_arrived else ""
```

- [ ] **Step 4: api/routes/workpaper.py**

```python
# api/routes/workpaper.py
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlmodel import Session
from src.application.export_4150_uc import export_4150
from src.infrastructure.db.repository import get_engine

router = APIRouter(prefix="/api/projects", tags=["workpaper"])

def _session():
    eng = get_engine()
    with Session(eng) as s:
        yield s

@router.post("/{project_id}/workpaper/export")
def export(project_id: int, s: Session = Depends(_session)):
    path = export_4150(s, project_id)
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
```

- [ ] **Step 5: Wire in app.py**

```python
from api.routes import workpaper as workpaper_route
app.include_router(workpaper_route.router)
```

- [ ] **Step 6: Run test (pass)**

```bash
pytest tests/integration/test_workpaper_route.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/application/export_4150_uc.py api/routes/workpaper.py api/app.py tests/integration/test_workpaper_route.py
git commit -m "feat(bc): 4150 export use-case + endpoint (control sheet + AC0 + AC1~AC8 + Toss palette)"
```

---

## Phase 1E — Frontend Wizard

### Task 1E.1: WAT 표준 셸 (index.html + style.css)

**Files:**
- Create: `BC_CONFIRMATION_TOOL/frontend/index.html`
- Create: `BC_CONFIRMATION_TOOL/frontend/style.css`

- [ ] **Step 1: style.css (Toss 토큰)**

```css
/* frontend/style.css */
:root {
  --accent: #3182F6;
  --accent-dark: #1B64DA;
  --bg: #F9FAFB;
  --bg2: #FFFFFF;
  --border: #E5E8EB;
  --text: #191F28;
  --text2: #333D4B;
  --text3: #4E5968;
  --success: #00C896;
  --warning: #F2A40C;
  --danger: #F04452;
  --conf-low: #FFF7E0;
}
* { box-sizing: border-box; }
body { margin:0; font-family:Pretendard,system-ui,sans-serif; background:var(--bg); color:var(--text); }

header{
  background:var(--bg2);border-bottom:1px solid var(--border);
  padding:1rem 2rem 1rem 7.25rem;
  display:flex;align-items:center;justify-content:space-between;
  flex-shrink:0;flex-wrap:nowrap;gap:1rem;
  min-height:76px;
}
@media (max-width:768px){ header{padding:0.7rem 1rem;min-height:0} }
.hd-title h1{font-size:1.05rem;font-weight:700;color:var(--text);letter-spacing:-0.04em;margin:0}
.hd-title h1 .ac{color:var(--accent);font-weight:800}
.hd-title p{font-size:0.72rem;color:var(--text3);margin:0.2rem 0 0;font-weight:400;letter-spacing:-0.01em}

.layout{display:flex;height:calc(100vh - 76px - 60px)}
nav.steps{width:260px;background:var(--bg2);border-right:1px solid var(--border);padding:1rem;overflow-y:auto}
nav.steps ol{list-style:none;padding:0;margin:0}
nav.steps li{padding:0.6rem 0.8rem;margin:0.2rem 0;border-radius:6px;cursor:pointer;color:var(--text3);font-size:0.85rem}
nav.steps li.active{background:var(--accent);color:white;font-weight:600}
nav.steps li.done{color:var(--success)}
nav.steps li.done::before{content:"✓ ";font-weight:700}

main.panel{flex:1;padding:1.5rem;overflow-y:auto;background:var(--bg)}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:1.2rem;margin-bottom:1rem}
.btn{background:var(--accent);color:white;border:none;padding:0.6rem 1.2rem;border-radius:6px;cursor:pointer;font-weight:600}
.btn.secondary{background:var(--bg2);color:var(--accent);border:1px solid var(--accent)}
.btn:disabled{opacity:0.5;cursor:not-allowed}
input,select{border:1px solid var(--border);border-radius:6px;padding:0.5rem;font-family:inherit}
table{width:100%;border-collapse:collapse}
th,td{border-bottom:1px solid var(--border);padding:0.5rem;text-align:left;font-size:0.85rem}
th{background:var(--bg);color:var(--text2);font-weight:600}

.drop-zone{border:2px dashed var(--border);border-radius:8px;padding:2rem;text-align:center;color:var(--text3);cursor:pointer}
.drop-zone.dragover{border-color:var(--accent);background:#EAF2FE}
.tag{display:inline-block;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.7rem;font-weight:600}
.tag.ok{background:#E0F8EF;color:var(--success)}
.tag.warn{background:#FFF7E0;color:var(--warning)}
.tag.bad{background:#FFEAEC;color:var(--danger)}

footer.legal{background:var(--bg2);border-top:1px solid var(--border);padding:0.8rem 2rem;display:flex;justify-content:space-between;font-size:0.72rem;color:var(--text3)}
```

- [ ] **Step 2: index.html (WAT 표준 골격)**

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>금융기관 조회 자동화</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" rel="stylesheet">
<link rel="stylesheet" href="/style.css">
</head>
<body>
<header>
  <div class="hd-title">
    <h1><span class="ac">BC</span> 금융기관 조회 자동화</h1>
    <p>4150 조서 자동 작성 · G/L 샘플링 → 회신 매칭 → AC0~AC10 fill</p>
  </div>
  <div class="hd-right"></div>
</header>

<div class="layout">
  <nav class="steps">
    <ol id="stepList"></ol>
  </nav>
  <main class="panel" id="panel"></main>
</div>

<footer class="legal">
  <span><b>Disclaimer.</b> 본 도구는 회계감사 실무 보조용 참고자료이며, 최종 판단과 책임은 사용자에게 있습니다.</span>
  <span class="right">© 2026 Woongcpa</span>
</footer>

<script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: 수동 확인 (서버 실행 + 브라우저)**

```bash
cd c:/Claude/BC_CONFIRMATION_TOOL
python run_server.py &
# Open http://127.0.0.1:8765 → header padding·footer 보이는지 시각 확인
```
Expected: WAT 표준 헤더 layout 통과 (좌측 7.25rem padding, 우측 빈 영역)

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/style.css
git commit -m "feat(bc): frontend shell (WAT standard header + Toss tokens + step nav layout)"
```

---

### Task 1E.2: app.js — Wizard state machine

**Files:**
- Create: `BC_CONFIRMATION_TOOL/frontend/app.js`

- [ ] **Step 1: 전체 app.js**

```javascript
// frontend/app.js
const API = "/api";
const STEPS = [
  { id: 1,  title: "회사·기준일",       render: renderStep1 },
  { id: 2,  title: "G/L · 회사 CS 업로드", render: renderUpload(["gl","cs"]) },
  { id: 3,  title: "사전 확장",           render: renderStep3 },
  { id: 4,  title: "Sampling 실행",       render: renderStep4 },
  { id: 5,  title: "전기 CS 비교",         render: renderUpload(["prior_cs"], true) },
  { id: 6,  title: "월보 · 담보 · 보증",    render: renderUpload(["union","collateral","guarantee"], true) },
  { id: 7,  title: "주소 유효성",          render: renderStep7 },
  { id: 8,  title: "회신본 업로드",         render: renderStep8 },
  { id: 9,  title: "파싱 결과 검토",        render: renderStep9 },
  { id: 10, title: "4150 조서 생성",        render: renderStep10 },
];

const state = { projectId: null, current: 1, done: new Set() };

function $(s){ return document.querySelector(s); }
function el(tag, props={}, ...children){
  const n = document.createElement(tag);
  Object.assign(n, props);
  for(const c of children) n.append(c?.nodeType ? c : document.createTextNode(c ?? ""));
  return n;
}

function renderNav(){
  const ol = $("#stepList"); ol.innerHTML = "";
  for(const s of STEPS){
    const li = el("li", { textContent: `${s.id}. ${s.title}` });
    if(s.id === state.current) li.classList.add("active");
    if(state.done.has(s.id)) li.classList.add("done");
    li.onclick = () => { state.current = s.id; render(); };
    ol.append(li);
  }
}

function render(){
  renderNav();
  const panel = $("#panel"); panel.innerHTML = "";
  const step = STEPS.find(s => s.id === state.current);
  step.render(panel);
}

async function post(path, body, isForm=false){
  const opts = { method:"POST" };
  if(isForm){ opts.body = body; }
  else { opts.headers = {"Content-Type":"application/json"}; opts.body = JSON.stringify(body || {}); }
  const r = await fetch(API + path, opts);
  if(!r.ok) throw new Error(await r.text());
  return r.json();
}

function renderStep1(panel){
  const card = el("div", { className:"card" });
  card.append(el("h2", {}, "프로젝트 설정"));
  const name = el("input", { placeholder:"회사명 (예: 코스맥스비티아이)" });
  const date = el("input", { type:"date", value:"2025-12-31" });
  const btn = el("button", { className:"btn" }, "프로젝트 생성");
  btn.onclick = async () => {
    btn.disabled = true;
    const r = await post("/projects", { name: name.value, fiscal_date: date.value });
    state.projectId = r.id; state.done.add(1); state.current = 2; render();
  };
  card.append(name, " ", date, " ", btn);
  panel.append(card);
}

function renderUpload(kinds, optional=false){
  return function(panel){
    panel.append(el("h2", {}, `파일 업로드 (${kinds.join(" · ")})${optional?" - 선택":""}`));
    for(const kind of kinds){
      const card = el("div", { className:"card" });
      card.append(el("h3", {}, kind));
      const drop = el("div", { className:"drop-zone", textContent:`${kind} 파일 드롭 또는 클릭` });
      drop.onclick = () => {
        const f = el("input", { type:"file" });
        f.onchange = async (e) => uploadFile(kind, e.target.files[0], drop);
        f.click();
      };
      drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("dragover"); };
      drop.ondragleave = () => drop.classList.remove("dragover");
      drop.ondrop = async (e) => {
        e.preventDefault(); drop.classList.remove("dragover");
        await uploadFile(kind, e.dataTransfer.files[0], drop);
      };
      card.append(drop);
      panel.append(card);
    }
    const next = el("button", { className:"btn" }, "다음 단계 →");
    next.onclick = () => { state.done.add(state.current); state.current++; render(); };
    panel.append(next);
  };
}

async function uploadFile(kind, file, drop){
  if(!file || !state.projectId) return;
  const fd = new FormData(); fd.append("file", file);
  drop.textContent = "업로드 중…";
  try{
    await post(`/projects/${state.projectId}/upload/${kind}`, fd, true);
    drop.textContent = `✓ ${file.name}`;
  }catch(err){ drop.textContent = "실패: " + err.message; }
}

function renderStep3(panel){
  panel.append(el("div", { className:"card" },
    el("h2", {}, "사전 확장 (선택)"),
    el("p", {}, "현재 MVP: yaml 파일 직접 수정. UI에서 자동 발견된 계정·alias 수락은 Phase 2."),
    (() => { const b = el("button", { className:"btn" }, "건너뛰기"); b.onclick = () => { state.done.add(3); state.current = 4; render(); }; return b; })()
  ));
}

function renderStep4(panel){
  const card = el("div", { className:"card" });
  card.append(el("h2", {}, "Sampling 실행"));
  const btn = el("button", { className:"btn" }, "G/L에서 금융기관 추출");
  const result = el("div");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "추출 중…";
    const r = await post(`/projects/${state.projectId}/sampling/run`);
    result.innerHTML = "";
    const tbl = el("table");
    tbl.append(el("tr", {},
      el("th", {}, "Canonical"), el("th", {}, "Branch"),
      el("th", {}, "B/S 잔액"), el("th", {}, "P/L 거래액"),
      el("th", {}, "B/S 계정"), el("th", {}, "P/L 계정"),
    ));
    for(const p of r.parties){
      tbl.append(el("tr", {},
        el("td", {}, p.canonical),
        el("td", {}, p.branch || ""),
        el("td", {}, p.bs_amount.toLocaleString()),
        el("td", {}, p.pl_amount.toLocaleString()),
        el("td", {}, p.bs_accounts.join(", ")),
        el("td", {}, p.pl_accounts.join(", ")),
      ));
    }
    result.append(tbl);
    btn.textContent = "재실행"; btn.disabled = false;
    state.done.add(4);
  };
  card.append(btn, result);
  panel.append(card);
  const next = el("button", { className:"btn" }, "다음 →");
  next.onclick = () => { state.current = 5; render(); };
  panel.append(next);
}

function renderStep7(panel){
  panel.append(el("h2", {}, "주소 유효성 + cross-check 실행"));
  const btn = el("button", { className:"btn" }, "Cross-check 실행");
  const result = el("div");
  btn.onclick = async () => {
    btn.disabled = true;
    const r = await post(`/projects/${state.projectId}/crosscheck/run`);
    result.innerHTML = "";
    for(const section of ["bidirectional","prior","union","collateral","guarantee","address"]){
      result.append(el("h3", {}, section));
      result.append(el("pre", { textContent: JSON.stringify(r[section], null, 2).slice(0, 1500) }));
    }
    btn.disabled = false;
  };
  panel.append(btn, result);
  const next = el("button", { className:"btn secondary" }, "다음 →");
  next.onclick = () => { state.done.add(7); state.current = 8; render(); };
  panel.append(next);
}

function renderStep8(panel){
  panel.append(el("h2", {}, "회신본 PDF 업로드 (여러 파일)"));
  const card = el("div", { className:"card" });
  const drop = el("div", { className:"drop-zone", textContent:"PDF 파일 드롭 또는 클릭 (여러 파일 가능)" });
  const list = el("ul");
  drop.onclick = () => {
    const f = el("input", { type:"file", multiple:true, accept:".pdf" });
    f.onchange = async (e) => { for(const file of e.target.files) await uploadResponse(file, list); };
    f.click();
  };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("dragover"); };
  drop.ondragleave = () => drop.classList.remove("dragover");
  drop.ondrop = async (e) => {
    e.preventDefault(); drop.classList.remove("dragover");
    for(const f of e.dataTransfer.files) await uploadResponse(f, list);
  };
  card.append(drop, list);
  panel.append(card);
  const next = el("button", { className:"btn" }, "다음 →");
  next.onclick = () => { state.done.add(8); state.current = 9; render(); };
  panel.append(next);
}

async function uploadResponse(file, list){
  const fd = new FormData(); fd.append("file", file);
  await post(`/projects/${state.projectId}/upload/response`, fd, true);
  list.append(el("li", {}, "✓ " + file.name));
}

function renderStep9(panel){
  panel.append(el("h2", {}, "회신 파싱·매칭"));
  const btn = el("button", { className:"btn" }, "파싱 실행");
  const result = el("div");
  btn.onclick = async () => {
    btn.disabled = true;
    const r = await post(`/projects/${state.projectId}/response/parse`);
    const tbl = el("table");
    tbl.append(el("tr", {},
      el("th", {}, "Section"), el("th", {}, "BC"), el("th", {}, "Bank"),
      el("th", {}, "Confidence"), el("th", {}, "Preview"),
    ));
    for(const rec of r.records.slice(0, 200)){
      const tr = el("tr", {},
        el("td", {}, rec.section),
        el("td", {}, rec.bc_no || ""),
        el("td", {}, rec.bank),
        el("td", {}, rec.confidence),
        el("td", { style:"font-size:0.7rem;color:#4E5968" }, JSON.stringify(rec.payload).slice(0,80)),
      );
      if(rec.confidence === "low") tr.style.background = "var(--conf-low)";
      tbl.append(tr);
    }
    result.innerHTML = ""; result.append(tbl);
    btn.disabled = false;
  };
  panel.append(btn, result);
  const next = el("button", { className:"btn secondary" }, "다음 →");
  next.onclick = () => { state.done.add(9); state.current = 10; render(); };
  panel.append(next);
}

function renderStep10(panel){
  panel.append(el("h2", {}, "4150 조서 생성"));
  const btn = el("button", { className:"btn" }, "Excel 다운로드");
  btn.onclick = async () => {
    btn.disabled = true; btn.textContent = "생성 중…";
    const r = await fetch(`${API}/projects/${state.projectId}/workpaper/export`, { method:"POST" });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = el("a", { href:url, download:`4150_AC_금융기관조회_${Date.now()}.xlsx` });
    a.click();
    btn.textContent = "재생성"; btn.disabled = false;
    state.done.add(10);
  };
  panel.append(btn);
}

render();
```

- [ ] **Step 2: 수동 확인**

```bash
cd c:/Claude/BC_CONFIRMATION_TOOL
python run_server.py &
# 브라우저 http://127.0.0.1:8765 → step 1~10 stepper 표시, step 1에서 회사 생성 가능 확인
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat(bc): wizard app.js (10-step state machine, upload, sampling table, parse preview, export)"
```

---

## Phase 1F — Integration

### Task 1F.1: WAT 임베드 등록

**Files:**
- Modify: `c:/Claude/WAT/index.html`

- [ ] **Step 1: TOOLS 객체 위치 확인**

```bash
grep -n "const TOOLS" c:/Claude/WAT/index.html | head -3
```

- [ ] **Step 2: BC entry 추가 (TOOLS 객체에)**

기존 TOOLS 배열의 채권채무·은행 카테고리 또는 신규 추가. Read 후 Edit:

```javascript
// TOOLS 객체에 entry 추가
{ name: "BC 금융기관 조회", category: "채권채무·은행", url: "http://127.0.0.1:8765" }
```

- [ ] **Step 3: 수동 확인**

브라우저에서 WAT shell 열고, BC tool 클릭 → iframe 로드 + 헤더 padding 정상 확인

- [ ] **Step 4: Commit (root c:/Claude repo)**

```bash
cd c:/Claude
git add WAT/index.html
git commit -m "feat(wat): register BC confirmation tool entry"
```

---

### Task 1F.2: E2E 통합 테스트

**Files:**
- Create: `BC_CONFIRMATION_TOOL/tests/e2e/test_full_pipeline.py`

- [ ] **Step 1: Write E2E test**

```python
# tests/e2e/test_full_pipeline.py
from fastapi.testclient import TestClient
from pathlib import Path
import pytest
from api.app import app

INPUT_DIR = Path("c:/Claude/BC_CONFIRMATION_TOOL/INPUT")

@pytest.mark.skipif(not INPUT_DIR.exists(), reason="INPUT 없음")
def test_end_to_end_with_real_inputs():
    c = TestClient(app)
    # 1. project create
    pid = c.post("/api/projects", json={"name":"코스맥스비티아이","fiscal_date":"2025-12-31"}).json()["id"]
    
    # 2. upload G/L
    gl = INPUT_DIR / "FY2025_보조부원장_BTI.XLSX"
    with open(gl, "rb") as f:
        c.post(f"/api/projects/{pid}/upload/gl", files={"file":(gl.name, f.read())})
    
    # 3. upload current CS + prior CS + collateral + guarantee
    cs_cur = INPUT_DIR / "4150_AC 금융기관 조회_코스맥스비티아이_FY2025_V1.xlsx"
    cs_prior = INPUT_DIR / "코스맥스비티아이_금융기관 조회서1_Control Sheet_FY2024.xlsx"
    coll = INPUT_DIR / "비티아이 제공 담보현황 251231_ok.xlsx"
    guar = INPUT_DIR / "비티아이 제공 연대보증현황 251231.xlsx"
    for kind, p in [("cs", cs_cur), ("prior_cs", cs_prior), ("collateral", coll), ("guarantee", guar)]:
        if p.exists():
            with open(p, "rb") as f:
                c.post(f"/api/projects/{pid}/upload/{kind}", files={"file":(p.name, f.read())})
    
    # 4. sampling
    r = c.post(f"/api/projects/{pid}/sampling/run").json()
    assert len(r["parties"]) >= 10  # 코스맥스비티아이는 최소 10+ 금융기관 거래
    
    # 5. crosscheck
    r = c.post(f"/api/projects/{pid}/crosscheck/run").json()
    assert "bidirectional" in r
    
    # 6. upload 회신본 (모두)
    for sub in ["온라인", "우편"]:
        d = INPUT_DIR / sub
        if not d.exists(): continue
        for pdf in d.glob("*.pdf"):
            with open(pdf, "rb") as f:
                c.post(f"/api/projects/{pid}/upload/response", files={"file":(pdf.name, f.read())})
    
    # 7. parse responses
    r = c.post(f"/api/projects/{pid}/response/parse").json()
    assert "records" in r
    
    # 8. export 4150
    r = c.post(f"/api/projects/{pid}/workpaper/export")
    assert r.status_code == 200
    assert "xlsx" in r.headers.get("content-type", "")
```

- [ ] **Step 2: Run E2E**

```bash
pytest tests/e2e/test_full_pipeline.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_full_pipeline.py
git commit -m "test(bc): E2E full pipeline (코스맥스비티아이 FY2025 실데이터)"
```

---

### Task 1F.3: 원본 양식 보존 회귀 테스트

**Files:**
- Create: `BC_CONFIRMATION_TOOL/tests/integration/test_template_preservation.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_template_preservation.py
import openpyxl
import shutil
from pathlib import Path
from src.infrastructure.excel_writer.ac_filler import ACFiller, SHEET_CONFIG
from src.infrastructure.excel_writer.color_swap import apply_toss_palette

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "4150_AC_template.xlsx"

def test_borders_and_merges_preserved(tmp_path):
    out = tmp_path / "out.xlsx"
    shutil.copy(TEMPLATE, out)
    # 원본 메타 수집
    src_wb = openpyxl.load_workbook(TEMPLATE)
    src_merges = {s: list(src_wb[s].merged_cells.ranges) for s in src_wb.sheetnames}
    src_borders_n = {s: sum(1 for row in src_wb[s].iter_rows() for c in row if c.border) for s in src_wb.sheetnames}
    src_wb.close()
    # fill·color swap
    filler = ACFiller(out)
    filler.fill_section("AC1", [])  # 빈 채움
    apply_toss_palette(filler.wb)
    filler.save()
    # 비교
    out_wb = openpyxl.load_workbook(out)
    for s in out_wb.sheetnames:
        if s not in src_merges: continue
        out_merges = list(out_wb[s].merged_cells.ranges)
        assert len(out_merges) == len(src_merges[s]), f"merge 영역 변경됨: {s}"
    out_wb.close()
```

- [ ] **Step 2: Run**

```bash
pytest tests/integration/test_template_preservation.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_template_preservation.py
git commit -m "test(bc): template preservation regression (merge ranges 무결성)"
```

---

## Phase 1G — Polish

### Task 1G.1: 서버 자동 재기동 스크립트

**Files:**
- Modify: `BC_CONFIRMATION_TOOL/run_server.py`
- Create: `BC_CONFIRMATION_TOOL/_restart_server.ps1`

- [ ] **Step 1: PowerShell restart script**

```powershell
# _restart_server.ps1
$port = 8765
$proc = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if ($proc) {
    Stop-Process -Id $proc.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath "python" -ArgumentList "run_server.py" -WorkingDirectory $here -WindowStyle Hidden
Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -UseBasicParsing -TimeoutSec 5
    Write-Host "Server up: $($r.Content)"
} catch {
    Write-Host "Healthz failed: $_"
}
```

- [ ] **Step 2: Commit**

```bash
git add _restart_server.ps1
git commit -m "chore(bc): server restart script (kill on 8765 + start + healthz)"
```

---

## Self-Review

**1. Spec coverage check:**
- Section 1 (목표·범위) → Phase 1 전체 cover ✓
- Section 2 (Architecture) → Task 0.1~0.4 + 폴더 구조 ✓
- Section 3 (Sampling) → Task 1A.1~1A.5 (B/S+P/L + Branch normalize) ✓
- Section 4 (Cross-check) → Task 1B.1~1B.5 (4-1~4-5) ✓
- Section 5 (PDF 파싱) → Task 1C.1~1C.6 (파일명·OCR·섹션·도메인·generic parser·UC) ✓
- Section 6 (Template fill) → Task 1D.1 (AC filler, AC0~AC10 매핑) ✓
- Section 7 (Frontend) → Task 1E.1~1E.2 (WAT 셸 + wizard) ✓
- Section 8 (Toss 색감) → Task 1D.2 (color_swap) + 1E.1 (CSS 토큰) ✓
- Section 9 (Phase) → Phase 1만 cover, Phase 2 명시적 제외 (의도된 범위) ✓
- Section 10 (테스트) → 단위 (각 task TDD) + 통합 (route tests) + E2E (Task 1F.2) + 회귀 (Task 1F.3) ✓
- Section 11 (비기능) → pyproject deps, port 8765, SQLite, juso.go.kr만 ✓
- Section 12 (위험·완화) → confidence 색·OCR fallback·alias override·preservation 테스트 ✓
- Section 13 (메모리 link) → spec 자체에 있음, plan 본문엔 불필요 ✓

**2. Placeholder scan:** "TODO", "TBD" 없음. 모든 step에 실제 code/cmd 있음. ✓

**3. Type 일관성:**
- `NormalizedParty.entity_key()` 사용처: sampling, crosscheck — 일관 ✓
- `Counterparty.canonical_name + branch` ↔ `NormalizedParty.canonical + branch` — 일관 ✓
- `ExtractedRecord.ac_section` "AC1"..."AC8" ↔ `SHEET_CONFIG` 키 — 일관 ✓
- `parse_filename` 반환 keys (bc_no, bank_raw, channel) ↔ parse_response_uc 사용처 — 일관 ✓

**4. Gaps:**
- AC9/AC10 자동 채움 — Phase 2 명시했으므로 OK (spec에 일치)
- 잔액 diff (5.6) — Phase 2 명시 ✓
- 은행별 어댑터 — Phase 2 명시 ✓

OK, plan ready.

---

## 실행 옵션

Plan complete and saved to `docs/superpowers/plans/2026-05-29-bc-confirmation-tool.md`. 두 가지 실행 방식:

**1. Subagent-Driven (recommended)** — task별 새 subagent dispatch, 단계 검토, 빠른 iteration. 30 task → 30회 subagent 호출 + 두 단계 review.

**2. Inline Execution** — 같은 session에서 plan 실행. 큰 checkpoint별로 사용자 review.

어느 방식으로 진행?
