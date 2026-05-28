# 채권채무조회서 샘플링·회수 툴 V2 설계서

- **작성일**: 2026-05-28
- **작성자**: kw1304 + Claude
- **상태**: Draft — 사용자 리뷰 대기
- **대상**: `CC_SAMPLING_TOOL_V2/` (신규)

---

## 1. 목적·범위·성공기준

### 1.1 목적

K-IFRS·ISA 530·ISA 505 부합 채권채무 외부조회 표본설계 ~ 회수 ~ projection 전체 라이프사이클 자동화.
감사인 1명이 거래처원장·재무제표·특관자리스트·대손충당금명세서만 드롭하면 표본·발송명단·조서·회신매칭·차이판정·모집단오차추정까지 단일 대시보드에서 완결.

### 1.2 범위 IN

- 표본설계 (MUS + Stratification 다단계 + Key item + 특관자 강제)
- 외화 거래처 환산 (기말환율)
- 대손충당금·부실채권 자동 제외 / Key 강제 분류
- 발송명단·조서 Excel 생성
- PDF 회신 추출·매칭·차이판정
- 대체적 절차 등록·증빙합산
- ISA 530 모집단오차 projection (PPS·tainting)

### 1.3 범위 OUT

현재 명시 OUT 없음. 위 IN 외 항목은 추후 결정.

### 1.4 성공기준

1. 더미 데이터 e2e (특관자·외화·부실·미회신 혼합) ≤ 3분 완주
2. ISA 530 projection 결과가 수기 PPS 추정치와 ±0.5% 이내 일치
3. 다국적 거래처원장 (시트·컬럼 임의) 자동감지 정확도 ≥ 95%, 실패 시 UI 매핑 확인
4. **최종 조서 정상 생성** — C100(채권)·AA100(채무) Excel이 감사조서시스템 import 가능한 양식·서식·시그니처(헤더·합계·tickmark·footnote) 완비. 발송명단·회신매칭표·대체적절차표·projection결과표 포함

---

## 2. 도메인 모델

### 2.1 채권·채무 분리·합산 규칙

- 표본설계는 채권·채무 각각 독립 수행 (모집단·confidence·tolerable·MUS PPS·strata 별도)
- 결과 표시·조서·발송명단·projection은 **합쳐서 한 화면·한 Excel**에 표시 (kind 컬럼으로 구분)
- 합산표 컬럼: kind(AR/AP), 거래처, 잔액, 선정사유, 회신상태, 차이, 절차결과

### 2.2 엔티티 구조

```
Project
 ├─ meta: client, period_end, base_ccy, materiality, tolerable
 ├─ Population[AR], Population[AP]                    ← 분리
 │    └─ Account: party_id, name, gl_account,
 │                balance_krw, balance_orig, ccy, fx_rate,
 │                is_related_party, is_bad_debt, allowance_amt,
 │                aging_bucket, src_sheet, src_row
 ├─ SamplingDesign[AR], SamplingDesign[AP]            ← 분리, 모집단별 독립
 │    ├─ method, confidence, tolerable, expected_ms, key_threshold
 │    ├─ strata[]: (low, high, n_required)
 │    └─ sample[]: Account + selection_reason(KEY/REP/RP/BAD)
 ├─ ConfirmationBatch                                 ← 합산
 │    └─ entries[]: kind(AR/AP), account_ref, expected, sent_at,
 │                  status, confirmed, diff, diff_reason, pdf_path
 ├─ AlternativeProcedure: kind, account_ref, type,
 │                        evidence_sum, coverage_pct
 └─ ProjectionResult[AR], ProjectionResult[AP]        ← 분리 계산
      └─ MergedProjectionView: 합산 표시 (총오차·총한도·총평가)
```

### 2.3 핵심 invariant

- AR·AP 모집단 어떤 단계에서도 mix 금지 (MUS·strata·projection은 항상 분리)
- 표시·export 레이어에서만 union (kind 컬럼 키)
- 특관자 강제포함은 AR·AP 각각 적용
- 외화 거래처는 base_ccy 환산 후 잔액 기준 표본 (원통화 잔액·환율은 조서에 병기)

---

## 3. 단일 대시보드 UI 레이아웃

```
┌─────────────────────────────────────────────────────────────────┐
│ 헤더: [회사명 ▾ 프로젝트선택] [평가기준일] [Materiality] [저장]  │
├──────────────┬──────────────────────────────────────────────────┤
│ 좌측 패널     │  메인 작업 영역 (탭 없음 — 스크롤 섹션)            │
│ (sticky)     │                                                  │
│              │  ① 자료 드롭존                                    │
│ ▸ 진행도      │     [거래처원장] [재무제표] [특관자] [충당금명세]    │
│   AR 표본 ✓   │     자동감지결과 → 매핑확인 인라인 (시트·컬럼)      │
│   AP 표본 ✓   │                                                  │
│   발송 ✓      │  ② 표본설계 패널 (AR·AP 좌우 2 컬럼)               │
│   회신 12/20  │     conf/tolerable/key threshold 슬라이더         │
│   대체절차 3  │     strata 자동제안 → 수동조정                    │
│   projection │     실시간 표본수·커버리지% 표시                    │
│              │                                                  │
│ ▸ 핵심지표    │  ③ 합산 표본 테이블 (kind=AR/AP 컬러 구분)         │
│   모집단      │     필터·정렬·선정사유 표시                       │
│   ₩5,832M     │                                                  │
│   표본 ₩3,1B  │  ④ 발송·회신 트래커                              │
│   커버리지    │     상태별 카운트 + PDF 드롭 → 자동매칭            │
│   53.2%       │     차이행만 빨강 강조, 클릭 시 사유 입력         │
│              │                                                  │
│ ▸ 다운로드    │  ⑤ 대체적 절차                                   │
│   [C100]     │     미회신 행에 절차유형·증빙 등록 → coverage 갱신  │
│   [AA100]    │                                                  │
│   [발송명단]  │  ⑥ Projection 결과                               │
│   [회신매칭]  │     AR·AP 별 PPS upper limit + 합산판정          │
│   [최종조서]  │     tolerable 초과 시 빨강 + 추가절차 권고문        │
└──────────────┴──────────────────────────────────────────────────┘
푸터: WAT 표준 ([[wat_tool_standard]])
```

### 3.1 UX 핵심

- 좌측 sticky 진행도·핵심지표 — 어디 스크롤해도 전체 상태 인지
- 표본설계는 AR·AP 좌우 분리 (도메인 invariant UI 반영), 합산표는 ③에서
- 자동감지 실패·차이 발생만 사용자 개입 요구. 정상은 침묵 (시그널 노이즈 최소)
- 모든 변경 즉시 좌측 지표 갱신 (단일 상태원천 = 백엔드 GET /project/{id}/state)

---

## 4. 아키텍처·디렉토리

```
CC_SAMPLING_TOOL_V2/
├── api/
│   ├── app.py                    # Flask 앱·라우트 등록
│   └── routes/
│       ├── project.py            # CRUD: /api/projects
│       ├── ingest.py             # 파일 드롭·자동감지·매핑확인
│       ├── sampling.py           # 표본설계 수행/재계산
│       ├── confirmation.py       # 발송명단 생성·회신 PDF 업로드·매칭
│       ├── alternative.py        # 대체적 절차 등록
│       ├── projection.py         # ISA 530 PPS projection
│       └── export.py             # Excel 조서 download
│
├── src/
│   ├── domain/                   # 순수 로직 (Flask·DB 의존 X)
│   │   ├── entities.py           # Project·Population·Account·Sample·Confirmation 등
│   │   ├── sampling/
│   │   │   ├── mus.py            # MUS PPS 알고리즘
│   │   │   ├── stratified.py     # 다단계 stratification·strata 자동제안
│   │   │   ├── sample_size.py    # ISA 530·AICPA AAG-SAM 매트릭스
│   │   │   └── classification.py # KEY/REP/RP/BAD 판정
│   │   ├── projection/
│   │   │   └── pps.py            # tainting·upper limit·precision
│   │   ├── fx.py                 # 외화 환산
│   │   ├── allowance.py          # 대손충당금·부실판정
│   │   └── matching.py           # 회신금액·차이판정 규칙
│   │
│   ├── infrastructure/           # 외부 의존
│   │   ├── db/                   # SQLAlchemy 모델·세션
│   │   ├── ingest/
│   │   │   ├── excel_loader.py   # openpyxl/pandas 시트·컬럼 자동감지
│   │   │   ├── fs_parser.py      # 재무제표
│   │   │   ├── rp_parser.py      # 특관자
│   │   │   └── allowance_parser.py
│   │   ├── pdf/
│   │   │   ├── extractor.py      # pdfplumber 텍스트층
│   │   │   └── ocr.py            # Tesseract (옵션)
│   │   └── excel_writer/
│   │       ├── workpaper.py      # C100·AA100·발송명단·매칭표·projection
│   │       └── styles.py         # tickmark·서식 토큰
│   │
│   └── application/              # 유스케이스 (도메인+인프라 조합)
│       ├── ingest_uc.py
│       ├── design_sampling_uc.py
│       ├── match_response_uc.py
│       ├── project_population_uc.py
│       └── export_workpaper_uc.py
│
├── configs/
│   ├── schema_mapping/           # 시트·컬럼 alias YAML
│   ├── templates/                # 조서 양식 YAML (확장 포인트)
│   └── audit_standards/          # 신뢰계수·key 비율 매트릭스 데이터
│
├── frontend/
│   └── index.html                # 단일 대시보드 (Vanilla JS)
│
├── templates/                    # Excel 원본 양식
│   └── cc_template_v2.xlsx
│
├── tests/
│   ├── unit/                     # domain 순수 테스트
│   ├── integration/              # application·infrastructure
│   └── e2e/                      # dummy client 전과정
│
└── docs/
    ├── ARCHITECTURE.md
    ├── AUDIT_STANDARDS_MAPPING.md
    └── USER_GUIDE.md
```

### 4.1 클린 아키텍처 원칙

- `domain` 순수 — pandas·flask·sqlalchemy import 금지. dataclass + 함수
- `application` 유스케이스가 domain 호출·infrastructure 어댑터 조립
- `api` 라우트 = HTTP 변환 only. 로직 금지
- 의존방향: api → application → domain ← infrastructure (양쪽이 domain만 의존)
- 테스트는 domain unit이 가장 많고 빠름. e2e는 더미 데이터 1세트로 회귀

---

## 5. 핵심 알고리즘·도메인 규칙

### 5.1 표본규모 (AICPA AAG-SAM)

```
n = (BV × RF) / (TM − EM × ExpansionFactor)
```

- BV = 모집단 장부가 (외화 환산 후 base_ccy)
- RF = 신뢰계수 (95% = 3.0, 90% = 2.3)
- TM = tolerable misstatement
- EM = expected misstatement
- ExpansionFactor = AAG-SAM 표

### 5.2 MUS PPS 선택

```
sampling_interval = BV / n_required
random_start ∈ [0, sampling_interval)
selected[i] = first account where cumulative_balance ≥ random_start + i × interval
```

- 시드 노출 안함 (테스트 재현용 별도 dev flag만)

### 5.3 Stratification 자동 제안

- 잔액 분포 log-binning → 자연 클러스터 (예: 0~Q1, Q1~Q3, Q3~99%, 99%~100%) 4단계 기본
- 사용자 슬라이더로 strata 경계·각 strata 표본수 조정
- 각 strata 내 MUS PPS 독립 수행
- **fallback**: 분포가 균일 (CV < 0.3) 이거나 모집단 < 50 → 단일 strata MUS로 자동 강등 (사용자 토스트 알림)

### 5.4 KEY / RP / BAD 분류

**선정사유 우선순위** (단일 reason 부착, 충돌 시 상위 채택):
`EXCLUDED_BAD` > `EXCLUDED_ZERO` > `FORCED_RP` > `FORCED_KEY` > `REP`

```
for acc in population:
  if acc.is_bad_debt and acc.allowance_ratio == 1.0:
      excluded.add(acc, "EXCLUDED_BAD"); continue
  if acc.balance == 0:
      excluded.add(acc, "EXCLUDED_ZERO"); continue
  if acc.is_related_party:
      selected.add(acc, "FORCED_RP"); continue              # RP면 KEY 검사 skip
  if abs(acc.balance) ≥ key_threshold:
      selected.add(acc, "FORCED_KEY"); continue
remaining = population − selected − excluded
mus_sample = pps(remaining, n_required − len(selected))     # 각 acc는 "REP" 사유
```

- key_threshold 기본 = tolerable misstatement (사용자 변경 가능)
- RP + 잔액 0 동시: `EXCLUDED_ZERO` (제외 우선). 발송 의미 없음
- BAD + RP 동시: `EXCLUDED_BAD` 우선. 단 사용자가 강제포함 토글 가능 (별도 옵션)

### 5.5 외화 환산

```
balance_krw = balance_orig × fx_rate(ccy, period_end)
```

- fx_rate 출처: WAT IRS 환율 API (`/api/rates` 기존 프록시 재사용)
- 환산 시점 = period_end (기말환율). 평균환율 옵션 아님 (잔액평가용)
- 환산 후 잔액으로만 MUS·projection. 조서 표시는 원통화·환율·환산금액 3열 병기

### 5.6 회신 매칭·차이판정

```
diff = confirmed_amt − expected_amt
threshold = max(1000, abs(expected_amt) × 0.001)            # 음수잔액 (선수금·환불 등) 안전
if |diff| ≤ threshold:
    verdict = "MATCH"
elif diff_reason in ("시점차이","미수령","미발송"):
    verdict = "RECONCILED"  # 사용자 입력 필요
else:
    verdict = "DISCREPANCY"  # projection 입력
```

- 임계값 ₩1,000 또는 |expected| × 0.1% — 사용자 변경 가능
- 시점차이 = 결산기준일 후 회수·결제로 reconcile
- `confirmed_amt is None` (PDF 추출 실패·미회신) → `verdict = "NO_RESPONSE"` (대체적 절차 후보)

### 5.7 대체적 절차 coverage

```
covered_amt = sum(alt_proc.evidence_sum) for non-response
coverage_pct = covered_amt / non_response_total
verdict = "ACCEPTABLE" if coverage_pct ≥ 0.75 else "INSUFFICIENT"
```

### 5.8 ISA 530 Projection (PPS)

```
for each sampled account with misstatement:
    tainting = misstatement_amt / book_amt           # if book < interval
    OR projected_ms = misstatement_amt               # if book ≥ interval (key item)
basic_precision = RF × sampling_interval
incremental_allowance = Σ (RF_increment × tainting × interval) for tainting < 1
upper_limit = projected_ms_sum + basic_precision + incremental_allowance
```

- AR·AP 각각 계산. 합산표에 두 값·합계 표시
- verdict = "WITHIN_TOLERABLE" / "EXCEED → 추가절차 필요"

### 5.9 invariants (반드시 성립)

- AR sample ∩ AP population = ∅, AP sample ∩ AR population = ∅
- Σ(selected.balance) ≥ Σ(forced.balance)
- coverage_pct ∈ [0, 1]
- projection upper_limit ≥ projected_ms_sum (basic precision 가산 보장)
- 외화·원화 합산 시 항상 base_ccy로 (UI 어느 곳도 mixed-ccy 합산 금지)

---

## 6. 데이터 흐름·에러처리·테스트

### 6.1 End-to-end 흐름

```
[1] 프로젝트 생성 (client, period_end, materiality, tolerable)
        │
        ▼
[2] 파일 드롭 → ingest_uc
    ├─ excel_loader: 시트·컬럼 alias 자동매핑 → 신뢰도 < 0.95면 UI 매핑확인
    ├─ fx 환산 (WAT /api/rates)
    ├─ rp·bad_debt·allowance 플래그 부착
    └─ Population[AR], Population[AP] DB persist
        │
        ▼
[3] 표본설계 패널 → design_sampling_uc (AR·AP 병렬)
    ├─ sample_size (AAG-SAM)
    ├─ classification (KEY/RP/BAD)
    ├─ stratified MUS PPS
    └─ Sample[] persist + 합산 ③ 테이블 갱신
        │
        ▼
[4] 발송명단 export → export_workpaper_uc("sendlist")
        │
        ▼
[5] PDF 회신 업로드 → match_response_uc
    ├─ pdfplumber 텍스트추출 (실패시 OCR)
    ├─ 거래처·금액 추출
    ├─ matching: MATCH / RECONCILED / DISCREPANCY
    └─ Confirmation persist + ④ 트래커 갱신
        │
        ▼
[6] 미회신 → 대체적 절차 UI
    └─ AlternativeProcedure persist + coverage_pct 갱신
        │
        ▼
[7] Projection → project_population_uc
    ├─ AR PPS projection
    ├─ AP PPS projection
    └─ MergedProjectionView + ⑥ 결과 갱신
        │
        ▼
[8] 최종 조서 export → export_workpaper_uc("final")
    └─ C100·AA100·발송명단·매칭표·대체절차·projection 통합 Excel
```

### 6.2 에러처리 정책

| 상황 | 정책 |
|---|---|
| 시트·컬럼 자동감지 < 0.95 | UI 매핑확인 차단 (사용자 개입까지 pending) |
| fx_rate 미확보 ccy | 행 단위 에러 표시, 환율 수동입력 필드 노출 |
| PDF 추출 실패 (OCR 포함) | 회신상태 EXTRACT_FAILED, 사용자가 수기 입력 |
| confirmed_amt 불명 | DISCREPANCY 후보지만 사용자 reconcile 선택 가능 |
| projection precision < tolerable·n 부족 | upper_limit 빨강 + "표본 확대 또는 추가절차 권고" 문구 |
| DB 충돌 (동일 프로젝트 동시편집) | last-write-wins + UI 토스트 경고 |

도메인 invariants 위배 (AR/AP mix, coverage > 1 등) → 즉시 500 + 로그·테스트 회귀 케이스 추가

### 6.3 테스트 전략

**unit (도메인 — pytest)**

- `test_sample_size.py`: AAG-SAM 매트릭스 모든 (conf, EM%) 셀 검증
- `test_mus.py`: 결정적 시드로 PPS 선택 회귀
- `test_stratified.py`: strata 경계·할당 invariant
- `test_classification.py`: KEY/RP/BAD edge (잔액 0, 충당 100%, RP+BAD 충돌)
- `test_fx.py`: 환율·통화 mix 금지 invariant
- `test_matching.py`: 임계값·시점차이·미수령 분기
- `test_pps_projection.py`: tainting·basic_precision·upper_limit 수식

**integration**

- `test_excel_loader.py`: 다양한 시트·컬럼 순서 fixture
- `test_pdf_extractor.py`: 텍스트층 PDF·이미지 PDF·다양 양식
- `test_workpaper_writer.py`: 생성 Excel 다시 읽어서 round-trip 일치

**e2e**

- `test_dummy_client.py`: 거래처 200건 (외화·RP·BAD·미회신 혼합) → 표본·조서·projection 까지 1회 완주
- `test_against_v1_baseline.py`: V1 결과와 V2 결과 핵심 지표 비교 (회귀 oracle, 100% 일치 요구 아님 — 의도된 개선 케이스는 보고)

**커버리지 목표**: domain ≥ 95%, application ≥ 80%, infrastructure ≥ 60%

---

## 7. 구현 단계·마이그레이션·롤아웃

### 7.1 구현 단계 (4 phase, 작은 increment)

**Phase 1 — Skeleton + Domain core (1~2일치 작업)**

- 디렉토리·Flask 부트·DB 모델 생성
- domain pure: entities, sample_size, mus, classification, fx
- unit 테스트 작성 (TDD)
- 마일스톤: `pytest tests/unit -q` 통과, API 미작동 OK

**Phase 2 — Ingest + Sampling UC (2~3일치)**

- excel_loader 시트·컬럼 자동감지 + 매핑확인 UI
- ingest_uc·design_sampling_uc
- AR·AP 병렬 표본설계 결과 합산 테이블
- 마일스톤: 더미 원장 드롭 → 합산 표본 ③ 표시

**Phase 3 — Confirmation + Alternative + Projection (3~4일치)**

- PDF 추출·매칭·차이판정
- 대체적 절차 등록·coverage
- ISA 530 PPS projection (AR·AP 분리·합산표시)
- 마일스톤: e2e 더미 데이터 1세트 완주

**Phase 4 — Workpaper Export + WAT 통합 (2일치)**

- C100·AA100·발송명단·매칭표·projection 통합 Excel
- 조서 양식 YAML 확장 포인트
- WAT 임베드 (헤더 padding 7.25rem·푸터·디자인토큰 표준)
- 마일스톤: 감사조서시스템 import 검증 (성공기준 4)

### 7.2 V1·V2 공존·롤오버

```
phase 1~3 동안:
  CC_SAMPLING_TOOL/      # V1 운영 유지 (포트 8520)
  CC_SAMPLING_TOOL_V2/   # V2 개발 (포트 8521 또는 분리 sub-route)

phase 4 완료·e2e green 후:
  git tag v1-stable-final
  mv CC_SAMPLING_TOOL CC_SAMPLING_TOOL_legacy
  mv CC_SAMPLING_TOOL_V2 CC_SAMPLING_TOOL
  WAT 라우트 V2로 swap
  legacy는 90일 보존 후 archive
```

### 7.3 마이그레이션 데이터

- V1 SQLite 프로젝트 → V2 import 어댑터 (선택사항, Phase 4에서 결정)
- 기본은 V2에서 새 프로젝트 생성 (감사건 라이프사이클상 깔끔)

### 7.4 위험·완화

| 위험 | 완화 |
|---|---|
| Stratified MUS 복잡도 → 표본수 폭증 | 슬라이더로 단순 MUS 모드 fallback |
| OCR 미설치 환경 | 텍스트층 PDF 우선·OCR optional·수동 입력 fallback |
| WAT 통합 회귀 | Phase 4 마지막에 통합·기존 WAT 회귀 테스트 통과 후 swap |
| V1 baseline 의존 | [[feedback_verify_reference_first]] — V1 결과를 진리로 가정 금지. V1 자체 회계정확성 먼저 검증 후 V2 비교 |

### 7.5 OUT 항목

현재 명시 OUT 없음. 1.2 IN 외 항목은 추후 결정.

---

## 8. 관련 메모리·표준

- [[wat_tool_standard]] — WAT 임베드 헤더·푸터·디자인 토큰
- [[feedback_verify_reference_first]] — 회귀·정합 검증 baseline 정확성 확인
- [[feedback_korean_accounting_terms]] — 한국 회계 용어 (장부가 / 공정가치 등)
- [[feedback_explanation_style]] — 이론·개념 위주 설명
- [[feedback_use_custom_agents]] — `.claude/agents/` 우선 활용
- [[feedback_auto_restart_server]] — 서버 변경 시 자동 재기동

## 9. 감사기준 근거

- **ISA 530** (표본감사) — 표본규모·MUS·projection 알고리즘
- **AICPA Audit Guide: Audit Sampling (AAG-SAM)** — 신뢰계수·Key item 비율 매트릭스·ExpansionFactor
- **ISA 505** (외부조회) — 조회서 발송·회신 절차·대체적 절차
- **ISA 550** (특수관계자) — 특관자 강제 포함
- **K-IFRS 1109** — 대손충당금·부실채권 인식 기준
