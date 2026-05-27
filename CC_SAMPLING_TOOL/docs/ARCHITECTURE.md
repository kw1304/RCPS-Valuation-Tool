# 시스템 아키텍처

채권채무조회서 MUS 표본추출 툴의 계층 구조와 주요 컴포넌트를 설명합니다.

---

## 계층 구조 (Clean Architecture)

```
┌─────────────────────────────────────┐
│   Interface Layer (api/app.py)      │  Flask REST API + 정적 프론트엔드
├─────────────────────────────────────┤
│   Orchestrator (src/orchestrator.py)│  Use Case: 샘플링 전체 플로우
├──────────────┬──────────────────────┤
│ Domain Layer │ Infrastructure Layer │
│ (src/domain/)│ (src/infrastructure/)│
└──────────────┴──────────────────────┘
```

### Domain Layer — 순수 비즈니스 로직
외부 의존성 없음. 감사 도메인 규칙을 캡슐화합니다.

| 모듈 | 책임 |
|---|---|
| `domain/population.py` | 거래처별 집계, 완전성 검토, Key item/Representative 분류 |
| `domain/mus.py` | MUS 확률비례추출 알고리즘 |
| `domain/sample_size.py` | 표본규모·신뢰계수·Key item 비율 결정 매트릭스 |
| `domain/matching.py` | 거래처명 퍼지 매칭 (Levenshtein 기반) |
| `domain/reconciliation.py` | 장부가 vs 회신금액 차이 판정 |

### Infrastructure Layer — 외부 시스템 어댑터
| 모듈 | 책임 |
|---|---|
| `infrastructure/loaders.py` | Excel 파일 읽기 (거래처원장/재무제표/특관자) |
| `infrastructure/schemas/` | 시트명·컬럼 자동 감지 (ledger/fs/rp) |
| `infrastructure/persistence/` | SQLite DB CRUD (프로젝트/워크페이퍼/Artifact) |
| `infrastructure/pdf/` | PDF 텍스트 추출 (pdfplumber + Tesseract OCR) |
| `infrastructure/confirmations/` | 조회서 발송명단 생성 |
| `infrastructure/report/` | 조서 Excel 출력 (양식 레지스트리 포함) |
| `infrastructure/evidence/` | 증빙 파일 저장 및 집계 |

---

## 데이터 흐름

```
[거래처원장.xlsx]
    ↓ load_ledger()
[DataFrame]
    ↓ detect_ledger_columns() → load_ledger_rows()
[LedgerRow list]
    ↓ aggregate_by_party()
[PartyBalance dict]
    ↓ classify_parties() + compute_sample_size() + run_mus()
[SamplingOutput]
    ↓ build_template_report()
[조서.xlsx]
```

---

## DB 스키마 (SQLite)

```
Project
├── id (UUID)
├── company_name
├── period_end
├── kind (receivable|payable|both)
├── status (active|archived)
└── Workpaper (1:N)
    ├── id (UUID)
    ├── kind
    ├── sampling_params (JSON)
    ├── sampling_result (JSON)
    ├── step1~5_completed_at
    ├── ConfirmationReply (1:N)  -- PDF 회신 처리 결과
    └── AlternativeProcedure (1:N)  -- 대체적 절차

Artifact
├── id (UUID)
├── project_id
├── kind (ledger|fs|rp|workpaper|send_list|pdf_reply|evidence)
├── stored_path
└── filename

AuditTrail
├── action
├── entity_type / entity_id
├── project_id
└── after (JSON)
```

---

## 확장 포인트

### 새 양식 추가
`configs/templates/` 폴더에 YAML 파일 추가 → 자동 레지스트리 등록.
`docs/TEMPLATE_REGISTRY.md` 참조.

### 새 시트명 키워드 추가
`src/infrastructure/schemas/ledger_schema.py`의 `_RECEIVABLE_PARTIAL`, `_PAYABLE_PARTIAL` 리스트에 추가.

### 새 감사기준 매트릭스 값
`src/domain/sample_size.py`의 `CONFIDENCE_FACTOR_MATRIX`, `KEY_ITEM_RATIO_MATRIX` 딕셔너리 수정.

### 새 대체적 절차 유형
`src/infrastructure/persistence/models.py`의 `AlternativeProcedure` 모델 + `api/app.py` Step 5 엔드포인트 확장.

---

## 기술 스택

| 구분 | 기술 |
|---|---|
| 백엔드 API | Flask 3.x |
| DB ORM | SQLAlchemy (SQLite) |
| Excel I/O | openpyxl, pandas |
| PDF 추출 | pdfplumber (+ pytesseract 선택) |
| 프론트엔드 | Vanilla JS (fetch API) |
| 테스트 | pytest |

---

## 파일 구조

```
CC_SAMPLING_TOOL/
├── api/
│   └── app.py                   # Flask 엔드포인트 전체
├── src/
│   ├── domain/                  # 비즈니스 규칙
│   │   ├── population.py
│   │   ├── mus.py
│   │   ├── sample_size.py
│   │   ├── matching.py
│   │   └── reconciliation.py
│   ├── infrastructure/
│   │   ├── loaders.py           # Excel 로더
│   │   ├── schemas/             # 자동 감지
│   │   ├── persistence/         # DB
│   │   ├── pdf/                 # PDF 추출
│   │   ├── confirmations/       # 발송명단
│   │   ├── report/              # 조서 출력
│   │   └── evidence/            # 증빙 집계
│   └── orchestrator.py          # 샘플링 플로우
├── configs/
│   ├── templates/               # 조서 양식 YAML
│   └── account_groups/          # 계정과목 그룹 매핑
├── tests/
│   └── fixtures/
│       └── dummy_client_a/      # 범용성 검증 더미 데이터
├── docs/                        # 이 폴더
└── templates/                   # 조서 Excel 원본 양식
```
