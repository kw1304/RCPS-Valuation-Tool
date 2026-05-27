# 조서 양식 추가 가이드 (Template Registry)

새 회계법인 양식을 등록하는 방법을 설명합니다.

---

## 현재 등록된 양식

| ID | 이름 | 파일 |
|---|---|---|
| `woongkye_standard` | 웅계회계 표준 | `configs/templates/woongkye_standard.yaml` |

---

## 새 양식 등록 절차

### Step 1: 기준 Excel 템플릿 준비
조서 양식 Excel 파일(`.xlsx`)을 `templates/` 폴더에 복사합니다.

```
templates/
├── cc_template.xlsx          (기존 웅계회계 표준)
└── bigfour_cc_template.xlsx  (새로 추가할 양식)
```

### Step 2: YAML 설정 파일 작성
`configs/templates/` 폴더에 새 YAML 파일을 만듭니다.

```yaml
# configs/templates/bigfour_generic.yaml
id: bigfour_generic
name: "Big4 공통 조서 양식"
firm_name: "대형회계법인"
template_xlsx_path: "templates/bigfour_cc_template.xlsx"

sheet_mapping:
  control: "Control"
  size: "SampleSize"
  key_item: "KeyItem"
  mus: "MUSSample"

cell_anchors:
  company_name: [2, 2]      # row, col (1-based)
  period_end: [4, 2]
  preparer: [2, 6]
  reviewer: [3, 6]
  prep_date: [2, 8]
  review_date: [3, 8]
  control_preparer: [2, 13]
  control_reviewer: [3, 13]
  control_prep_date: [2, 15]
  control_review_date: [3, 15]

column_anchors_c100_2:
  receivable:
    외상매출금: 3
    받을어음: 4
    미수금: 5
    선급금: 6
  payable:
    외상매입금: 3
    미지급금: 4
    선수금: 5

party_matrix_start_row: 50

size_sheet_anchors:
  population: [20, 5]
  pm: [21, 5]
  key_item_threshold: [22, 5]
  key_item_amount: [23, 5]
  key_item_count: [24, 5]
  base_sample_size: [25, 5]
  confidence_factor: [26, 5]
  final_sample_size: [29, 5]
  summary_ki_count: [10, 4]
  summary_ki_amount: [10, 5]
  summary_ki_coverage: [10, 7]
  summary_rep_count: [11, 4]
  summary_rep_amount: [11, 5]
  summary_total_count: [12, 4]
  summary_total_amount: [12, 5]
  summary_pop_count: [13, 4]
  summary_pop_amount: [13, 5]
  coverage_count: [14, 4]
  coverage_amount: [14, 5]

mus_sheet_anchors:
  remaining_population: [12, 4]
  final_sample_size: [13, 4]
  sample_interval: [14, 4]
  random_start: [15, 4]
  data_start_row: 20
```

### Step 3: 자동 등록 확인
서버를 재시작하면 `configs/templates/` 폴더의 모든 YAML 파일이 자동 로드됩니다.

```bash
# 등록된 양식 목록 확인 (API)
curl http://127.0.0.1:8520/api/templates
```

응답 예시:
```json
[
  {"id": "woongkye_standard", "name": "웅계회계 표준", "firm_name": "웅계회계법인"},
  {"id": "bigfour_generic", "name": "Big4 공통 조서 양식", "firm_name": "대형회계법인"}
]
```

---

## YAML 필드 설명

### 기본 정보
| 필드 | 설명 | 필수 |
|---|---|---|
| `id` | 고유 식별자 (URL/파일명에 사용, 영문+숫자+언더바) | O |
| `name` | 화면에 표시되는 이름 | O |
| `firm_name` | 회계법인명 (조서 헤더용) | O |
| `template_xlsx_path` | Excel 템플릿 파일 경로 (프로젝트 루트 기준) | O |

### sheet_mapping
조서 Excel의 시트 이름을 역할별로 매핑합니다.

| 키 | 역할 |
|---|---|
| `control` | C100 조회서 Control Sheet |
| `size` | C100-1 표본규모 결정 |
| `key_item` | C100-2 Key item 추출 |
| `mus` | C100-3 MUS 표본 추출 |

### cell_anchors
조서 헤더(회사명, 기간, 작성자 등)를 기록할 셀 위치 (1-based row, col).

### column_anchors_c100_2
Key item 시트에서 계정과목별 컬럼 번호 (1-based).

### size_sheet_anchors / mus_sheet_anchors
표본규모·MUS 시트의 주요 숫자 입력 셀 위치.

---

## 주의사항

1. `id`는 파일명과 일치시키는 것을 권장합니다: `mytemplate.yaml` → `id: mytemplate`
2. `template_xlsx_path`의 Excel 파일은 반드시 실제로 존재해야 합니다.
3. 셀 좌표는 **1-based** (openpyxl 기준)입니다. Excel에서 A1=row1,col1, B3=row3,col2.
4. 기존 양식(`woongkye_standard`)을 복사해서 수정하는 방법을 권장합니다.

---

## 구현 참조
- 레지스트리 로더: `src/infrastructure/report/template_registry.py`
- 양식 렌더러: `src/infrastructure/template_reporter.py`
