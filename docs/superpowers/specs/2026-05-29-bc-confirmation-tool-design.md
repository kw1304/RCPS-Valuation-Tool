# BC 은행조회서(금융기관 조회) Tool — Design Spec

- 작성일: 2026-05-29
- 작성자: kw1304
- 목표: 4150 조서(금융기관조회) Excel을 sampling → cross-check → 회신 PDF 파싱 → AC0~AC10 셀 fill 까지 자동 완성하는 tool

## 1. 목표·범위

### 1.1 최종 목표
4150 조서 (`AC 금융기관 조회_<회사>_FY<YY>_<버전>.xlsx`)를 **원본 양식 그대로 유지하면서** 자동 작성. 색감만 Toss 팔레트로 swap.

### 1.2 커버 범위 (전체 cycle)
- G/L 기반 금융기관 sampling (B/S + P/L 계정 모두 sweep)
- 회사 control sheet · 전기 CS · 은행연합회 월보 · 담보 · 지급보증 cross-check
- 우편 발송 거래처 주소 유효성 검사
- 회신본 PDF (온라인 24 + 우편 6 예시) 파싱·매칭
- AC control sheet · AC0 종합표 · AC1~AC10 세부 시트 자동 fill
- WAT 임베드 (디자인 토큰 통일)

### 1.3 비목표
- 조회서 letter 발송 자체 (회사가 발송)
- G/L 분개 자동 수정
- 후속측정·attribution 등 RCPS 류 기능 ([[feedback_no_subsequent]])

## 2. Architecture

```
BC_CONFIRMATION_TOOL/
├── INPUT/                       # 사용자 input 자료
├── OUTPUT/                      # 4150 조서 산출물
├── api/
│   ├── app.py                   # FastAPI entry, port 8765
│   └── routes/
│       ├── upload.py
│       ├── sampling.py
│       ├── crosscheck.py
│       ├── response.py
│       └── workpaper.py
├── src/
│   ├── domain/
│   │   ├── financial_account.py # 금융계정 분류 룰
│   │   ├── party_normalize.py   # 금융기관명 + 지점 normalize
│   │   ├── sampling.py
│   │   ├── crosscheck.py
│   │   └── ac_models.py         # AC1~AC10 도메인 모델
│   ├── application/
│   │   ├── ingest_uc.py
│   │   ├── sampling_uc.py
│   │   ├── crosscheck_uc.py
│   │   ├── parse_response_uc.py
│   │   └── export_4150_uc.py
│   └── infrastructure/
│       ├── gl_loader.py
│       ├── cs_loader.py
│       ├── pdf/
│       │   ├── extractor.py
│       │   ├── ocr.py
│       │   └── banks/           # 은행별 어댑터 (필요 시)
│       ├── union_monthly.py
│       ├── address_validator.py
│       ├── db/                  # SQLite (projects.db)
│       └── excel_writer/
│           ├── ac_filler.py
│           └── color_swap.py
├── templates/
│   └── 4150_AC_template.xlsx
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── configs/
│   ├── financial_keywords.yaml
│   ├── bank_aliases.yaml
│   ├── domestic_locations.yaml
│   ├── foreign_cities.yaml
│   └── companies/<company_id>.yaml
├── data/projects.db
└── tests/
```

### 핵심 결정
- **Clean Arch**: domain ← application ← infrastructure
- **Template 보존**: openpyxl `keep_vba=False`, 데이터 영역만 fill, 서식·border·셀병합 그대로
- **State persistence**: SQLite (CC_SAMPLING_TOOL_V2 패턴)
- **재사용**: `party_normalize.py`는 CC_SAMPLING_TOOL_V2의 "긴 candidate 우선" 패턴 차용

## 3. Sampling 알고리즘

### 3.1 2단계 추출
**Step A** — 금융계정 직접 추출 (B/S + P/L):
```yaml
# configs/financial_keywords.yaml
direct_accounts:
  # B/S
  예금:    [현금성자산, 단기금융상품, 정기예금, 보통예금, 당좌예금, MMDA, MMF, CMA]
  차입:    [단기차입금, 장기차입금, 사채, 유동성장기부채, 회사채]
  파생:    [파생상품자산, 파생상품부채, 통화선도, 이자율스왑, 통화스왑]
  보증:    [지급보증, 보증금, 보증채무, 우발채무]
  담보:    [담보제공자산, 근저당, 질권]
  유가증권: [당기손익공정가치측정금융자산, 매도가능증권, FVPL, FVOCI]
  보험:    [장기금융상품-보험, 보험예치금, 퇴직연금운용자산]
  # P/L
  이자손익:  [이자수익, 이자비용, 차입금이자, 사채이자]
  외환:      [외환차익, 외환차손, 외화환산이익, 외화환산손실]
  평가손익:  [파생상품평가이익, 파생상품평가손실, FVPL평가손익, FVOCI평가손익]
  수수료:    [지급수수료, 금융수수료, 은행수수료, 증권거래수수료]
  배당:      [배당금수익, 수입배당금]
  보험비용:  [보험료, 화재보험료, 손해보험료, 임원배상책임보험료]
```

**Step B** — 일반계정 텍스트 매칭 (`bank_aliases.yaml`, 긴 candidate 우선).

**Step C** — Merge + dedupe → BC 자동 번호 부여.

### 3.2 지점 Normalize 룰 ([[bc_tool_branch_normalize]])
- 국내 지점 → 본점 canonical로 통합 (강남·종로·역삼·여의도·잠실 + 광역시·도 등)
- 해외 지점 → canonical + 도시명 유지 (도쿄·홍콩·런던·뉴욕·상하이·싱가포르 등)

판별 우선순위:
1. 영문/한글 외국 도시명 매칭 → 해외 지점 entity
2. 국내 도시·구·동 매칭 → 본점 통합
3. 둘 다 없음 → canonical 매칭만

### 3.3 출력 (AC0 종합표)
| BC번호 | 금융기관(canonical) | 발견 B/S | 발견 P/L | B/S 잔액 | P/L 거래액 | confidence |
| --- | --- | --- | --- | --- | --- | --- |

### 3.4 회사·시기별 가변성
- `configs/companies/{id}.yaml` override로 계정·alias 추가/제외
- 일반계정에서 alias 매칭 row 발견 시 그 계정과목을 후보로 자동 추가 + 사용자 검토 flag
- 사용자 UI에서 수락 시 회사 yaml에 영구 저장

## 4. Cross-check (5단계)

### 4-1. 회사 CS ↔ 우리 추출 list (양방향)
- `우리 ∧ ¬CS` → "회사 누락 가능"
- `CS ∧ ¬우리` → "회사 자발 추가, 사유 문의"
- 양쪽 존재 → ✓
- 매칭: canonical name 우선, fuzzy ratio ≥ 0.85 fallback

### 4-2. 전기 CS ↔ 당기
- 전기 BC list 추출
- 2단계 매칭 (canonical → fuzzy 0.85)
- column: `전기 있음/당기 있음` 4분면

### 4-3. 은행연합회 월보 → CS 존재 여부 (단순 Y/N)
- 월보 PDF/Excel 파싱
- 각 기관에 대해 CS 존재만 기재

### 4-4. 담보·지급보증 명세서 → CS 존재 여부 (단순 Y/N)
- 두 파일에서 금융기관 추출
- CS 존재만 기재

### 4-5. 주소 유효성 (우편 발송 대상만)
- 회사 CS에서 회신구분 = 우편 row 필터
- 검증 stack:
  1. 도로명주소 OpenAPI (juso.go.kr, 무료)
  2. 실패 시 인터넷 검색 fallback (은행 지점 공식 주소)
- 결과 4단계: 정상 / 우편번호 불일치 / 주소 미존재 / 검증 실패

## 5. 회신본 PDF 파싱·매칭

### 5.1 파일명 파서
```
온라인: 전자_[BC-N]_<회사>_[<사업자번호>]_<은행>_[<YYYY년MM월DD일>].pdf
우편:   BC-N_<은행>.pdf  또는  BC-N_<회사>_<은행>.pdf
```
→ `{bc_no, bank_name_raw, channel}` 추출 → canonical 후 sampling list join.

### 5.2 텍스트 추출
- 온라인 (digital): `pdfplumber` (text + table)
- 우편 (스캔): Tesseract OCR (kor+eng) + 회전 자동 보정

### 5.3 섹션 분류
| 섹션 | 키워드 | 시트 |
|---|---|---|
| 금융자산 | 예금·계좌·잔액·주식·채권·펀드·수익증권·CMA·MMF·RP·CP·CD·신탁·ETF·외화예금 | AC1 |
| 차입금 | 차입·대출·한도·약정 | AC2 |
| 파생상품 | 파생·선도·스왑·옵션 | AC3 |
| 지급보증 | 지급보증·L/C·신용장 | AC4 |
| 담보 | 담보·근저당·질권 | AC5 |
| 어음·수표 | 어음·수표·당좌 | AC6 |
| 보험 | 보험증권·보험상품 | AC7 |
| 기타 | (분류 안됨) | AC8 |

### 5.4 도메인 모델

```python
class FinancialAsset(BaseModel):     # AC1
    bc_no: str
    bank: str
    asset_type: Literal['deposit','stock','bond','fund','other']
    product: str
    account_no: str | None
    currency: str
    quantity: Decimal | None
    face_amount: Decimal | None
    balance: Decimal
    interest_rate: Decimal | None
    open_date: date | None
    maturity: date | None

class Borrowing(BaseModel):          # AC2
    bc_no: str
    bank: str
    contract_type: str
    limit_amt: Decimal
    limit_ccy: str
    balance: Decimal
    balance_ccy: str
    contract_date: date
    maturity: date | None
    rate: str | None
```
(AC3~AC8 동일 패턴, ac_models.py)

### 5.5 은행별 어댑터
- 공통 generic parser 우선 (80%+ cover 목표)
- 양식 특이한 은행만 `infrastructure/pdf/banks/{bank}.py` 추가 (점진)
- 어댑터 선택: canonical 매핑 → `BANK_PARSERS[canonical]` 우선, 없으면 generic

### 5.6 잔액 diff 검증 (Phase 2, optional)
- G/L 잔액 vs 회신 잔액 (BC × 섹션별)
- 차이 > threshold `max(KRW 100,000, 1% × 잔액)` → ⚠ flag (둘 중 큰 값)

### 5.7 Confidence
- 각 필드에 `confidence: high|medium|low`
- low → AC 셀 fill `#FFF7E0` + cell comment "OCR 신뢰도 낮음 - 검토 필요" + 원본 PDF 페이지 hyperlink

## 6. 4150 Template Fill 매핑

### 6.1 시트 매핑 (start_row + column_map)

#### AC control sheet (row 6+)
B=BC번호 / C=금융기관 / D=지점 / E=회신구분 / F=주소 / H=담당자 / I=전화 / J=회신여부

#### AC0 종합표 (row 12+)
C=BC / D=기관 / E=회사 list 일치 (4-1) / F=전기 일치 (4-2) / G=월보 (4-3) / H=담보·보증 (4-4) / I=회신도착

#### AC1 금융자산 (row 11+)
C=BC / D=기관 / E=상품명 / F=계좌 / G=통화 / H=금액 / I=이자율 / J=거래개시일

#### AC2 차입금 (row 12+)
C=BC / D=기관 / E=거래종류 / F-G=한도 ccy·금액 / H-I=잔액 ccy·금액 / J=계약일

#### AC3 파생상품 (row 12+)
C=BC / D=종류 / E=계약일 / F-G=매입 ccy·금액 / H-I=매도 ccy·금액

#### AC4 지급보증 (row 13+)
C=BC / D=기관 / E=종류 / F-G=한도 ccy·금액 / H-I=잔액 ccy·금액 / J=만기

#### AC5 담보제공자산 (row 12+)
C=BC / D=기관 / E=종류 / F=담보권자 / G=발행인 / H=장부금액 / I=평가금액 / J=우선순위

#### AC6 어음·수표 (row 13+)
C=BC / D=기관 / E=종류 / G=매수 …

#### AC7 보험 (row 12+)
C=BC / D=기관 / E=상품명 / F=증권번호 / G=부보금액 / H=보험료 / I-J=계약기간

#### AC8 일반거래 (row 12+)
C=BC / D=기관 / E=자산종류 / F=계좌 / G=거래일 / H=거래종류 / I=미상환잔액 / J=거래기간

#### AC9 거래정보 (row 1+)
자유 list (회신 미해결·추후확인 issue)

#### AC10 추가내역 (row 2+)
외화·미수·기타 자유 기재

### 6.2 Filler 구현

```python
class ACFiller:
    sheet_config = {
        'AC1. 금융자산': {'start_row': 11, 'col_map': AC1_MAP, 'extend': True},
        'AC2. 차입금':   {'start_row': 12, 'col_map': AC2_MAP, 'extend': True},
        # ...
    }
    
    def fill(self, sheet, records):
        # 기존 row 수 < records 수 → insert_rows + style copy from start_row
        # 셀 단위 .value = ... (스타일 건드리지 않음)
        # 병합 셀 → top-left에만 write
```

### 6.3 행 확장 룰
- 원본 template row 부족 → `ws.insert_rows()` + 마지막 데이터 row의 style copy (border·font·정렬·number format·data validation)
- 병합 영역 동일 패턴 복사

## 7. Frontend Wizard

### 7.1 셸
- WAT iframe 등록 (`c:/Claude/WAT/index.html` TOOLS 객체), category="채권채무·은행", url=`http://127.0.0.1:8765`
- WAT 표준 ([[wat_tool_standard]]) 강제: header padding-left 7.25rem, min-height 76px, h1 1.05rem, 부제 1줄, 푸터 통일 문구, Pretendard

### 7.2 Wizard 10단계
1. 회사·기준일
2. G/L + 회사 CS 업로드
3. 사전 확장 (재량 계정·alias) — 선택
4. Sampling 실행 → 결과 편집
5. 전기 CS 업로드 + 비교
6. 월보 + 담보·보증 업로드 + 비교
7. 주소 유효성 (우편 대상)
8. 회신본 업로드 (zip / 폴더) → 자동 분류
9. 파싱·매칭 결과 확인·수정
10. 4150 조서 생성·다운로드

### 7.3 핵심 인터랙션
- Step 4 → inline table 편집 (추가/삭제/canonical 수정/지점 통합·분리 토글)
- Step 6 → drop zone × 3, 비교 결과 inline
- Step 7 → 색 표시 (✓ / ⚠ / ✗) + 제안 주소 클릭 적용
- Step 8 → drag-drop, BC 번호 추출 실패 시 수동 매핑
- Step 9 → AC1~AC8 탭, confidence 색, 원본 PDF 페이지 미리보기 (pdf.js)
- Step 10 → `4150_AC_금융기관조회_<회사>_FY<연도>_<timestamp>.xlsx`

## 8. Toss 색감 swap

### 8.1 팔레트
| 용도 | 색 | hex |
|---|---|---|
| Primary (헤더 강조) | Toss Blue | `#3182F6` |
| Primary Dark (제목줄) | | `#1B64DA` |
| Light BG | Cool Gray 50 | `#F2F4F6` |
| BG | Off White | `#F9FAFB` |
| Border | Cool Gray 200 | `#E5E8EB` |
| Text | Cool Gray 900 | `#191F28` |
| Text Sub | Cool Gray 600 | `#4E5968` |
| Success | | `#00C896` |
| Warning | | `#F2A40C` |
| Danger | | `#F04452` |
| Confidence Low | | `#FFF7E0` |

### 8.2 Excel swap 룰
1. 시트 제목 영역 (A1~J3) → fill `#3182F6`, 폰트 white
2. 테이블 헤더 row (시트별 config) → fill `#1B64DA`, 폰트 white (굵게 유지)
3. 데이터 row → 원본 그대로 (흰색)
4. 합계 row → fill `#F2F4F6`
5. confidence low 셀 → fill `#FFF7E0` + cell comment
6. (Phase 2) diff column → `#FFF7E0` ~ `#FFE0E0` gradation

구현: 시트별 명시적 영역 swap (`color_swap.py`의 sheet-config 기반, RGB literal swap 방식 아님)

### 8.3 Frontend CSS 변수
```css
:root {
  --accent: #3182F6;
  --accent-dark: #1B64DA;
  --bg: #F9FAFB;
  --bg2: #FFFFFF;
  --border: #E5E8EB;
  --text: #191F28;
  --text3: #4E5968;
  --success: #00C896;
  --warning: #F2A40C;
  --danger: #F04452;
  --conf-low: #FFF7E0;
}
```

## 9. 단계·우선순위 (Phase)

### Phase 1 (MVP)
- Sampling (B/S + P/L)
- Cross-check 4-1, 4-2, 4-3, 4-4 (Y/N)
- 주소 유효성 4-5 (juso.go.kr 우선)
- 회신본 generic parser (5.1~5.5)
- 4150 fill AC1~AC8 + AC control sheet + AC0
- Toss 색감 적용
- WAT 임베드

### Phase 2 (확장)
- 잔액 diff 검증 (5.6)
- 은행별 어댑터 추가
- 인터넷 검색 fallback (4-5 stage 2)
- AC9·AC10 자유 기재 UI (Phase 1에서는 자동 채움만, 사용자 직접 편집은 Excel에서)

## 10. 테스트

### 10.1 단위
- party_normalize: 국내 지점 합산 + 해외 지점 분리 (BC-26 신한 홍콩, BC-28 국민 런던 케이스)
- financial_account: B/S·P/L 사전 매칭
- ac_filler: row insert + style copy 무결성

### 10.2 통합
- 코스맥스비티아이 FY2025 INPUT 자료 풀세트 → 4150 조서 생성
- 원본 V1 vs 생성 V2 셀 diff 비교 (서식·테두리·병합 차이 0)
- 회신본 PDF 30개 파싱 confidence 분포

### 10.3 회귀
- WAT 임베드 시 헤더 padding·min-height 침범 없는지 시각 확인
- 다른 회사 input (가상 데이터) 1세트로 회사·기준일 가변성 검증

## 11. 비기능 요구

- Python 3.12, FastAPI, openpyxl, pdfplumber, pytesseract, rapidfuzz, pydantic v2
- 메모리: G/L 보조부 100MB Excel 처리 가능 (read_only stream)
- 로컬 only (127.0.0.1:8765), 외부 API는 juso.go.kr만
- 회사별 input·결과 격리 (`data/projects.db` project_id)

## 12. 위험·완화

| 위험 | 완화 |
|---|---|
| 은행별 회신서식 차이 큼 | generic parser + 점진적 어댑터, confidence 색 표시 |
| OCR 정확도 부족 (우편 스캔) | low confidence 셀 노랑 fill + 원본 PDF link |
| 회사별 계정과목 명칭 다양 | configs/companies override + 자동 발견 + 사용자 수락 |
| 지점 normalize 오판 | 사용자 UI 토글 (통합·분리 수동 조정) |
| 원본 양식 깨짐 | 모든 시트 cell-by-cell write, 병합·border·font 보존 테스트 회귀 |

## 13. 관련 메모리
- [[bc_tool_branch_normalize]]
- [[wat_tool_standard]]
- [[feedback_korean_accounting_terms]]
- [[feedback_use_custom_agents]]
- [[feedback_no_subsequent]]
