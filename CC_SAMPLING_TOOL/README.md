# 채권채무조회서 MUS 표본추출 툴

감사기준서 530 (표본감사) 기반 **MUS(Monetary Unit Sampling) 자동화 툴**.
채권·채무 조회서 표본설계부터 회신 처리·대체적 절차까지 5단계 워크플로우를 지원합니다.

## 감사기준 근거
- **감사기준서 530** (표본감사) — 표본규모·MUS 알고리즘
- **AICPA Audit Guide: Audit Sampling (AAG-SAM)** — 신뢰계수·Key item 비율 매트릭스
- **ISA 505** (외부조회) — 조회서 발송·회신 절차
- **ISA 550** (특수관계자) — 특관자 강제 포함

---

## 빠른 시작

### 설치
```bash
pip install -r requirements.txt
```

### 서버 실행
```bash
python -m flask --app api.app run --host 127.0.0.1 --port 8520
```

브라우저: `http://127.0.0.1:8520`

---

## 5단계 워크플로우

| 단계 | 내용 |
|---|---|
| Step 0 | 프로젝트 생성 + 회사자료 업로드 (거래처원장/재무제표/특관자) |
| Step 1 | MUS 표본설계 — Key item / Representative / 특관자 분류 |
| Step 2 | 조회서 발송명단 Excel 생성 |
| Step 3 | 조서 (C100/AA100) Excel 생성 |
| Step 4 | PDF 회신 업로드 → 자동 추출·매칭·차이 판정 |
| Step 5 | 대체적 절차 등록 + 증빙 합산 + 최종 조서 다운로드 |

---

## 범용성

- **시트명 자동 감지**: 채권/매출원장/AR, 채무/매입원장/AP 등
- **재무제표 자동 감지**: FS_M/BS/재무상태표 등
- **특관자 자동 감지**: 특관자리스트/관계회사/Related Parties 등
- **컬럼 순서 자동 감지**: 거래처명·계정과목·기말잔액 위치 무관

---

## 폴더 구조

```
CC_SAMPLING_TOOL/
├── api/app.py            # Flask REST API
├── src/
│   ├── domain/           # MUS·표본규모·매칭 비즈니스 로직
│   └── infrastructure/   # Excel/PDF/DB/조서 어댑터
├── configs/templates/    # 조서 양식 YAML (새 양식 여기 추가)
├── docs/                 # 사용자 가이드 + 감사기준 매핑 문서
├── tests/                # pytest 180+ 테스트
└── templates/            # 조서 Excel 원본 양식
```

---

## 테스트 실행

```bash
# 전체 테스트
python -m pytest tests/ -q

# 특정 테스트
python -m pytest tests/test_dummy_client_e2e.py -v   # 범용성 검증
python -m pytest tests/test_against_7620.py -v       # 회귀 검증
```

---

## 문서

| 문서 | 내용 |
|---|---|
| `docs/USER_GUIDE.md` | 한국어 사용자 가이드 + FAQ |
| `docs/AUDIT_STANDARDS_MAPPING.md` | 감사기준·K-IFRS 매핑 |
| `docs/ARCHITECTURE.md` | 시스템 아키텍처 |
| `docs/TEMPLATE_REGISTRY.md` | 새 조서 양식 추가 방법 |

---

## 알려진 한계

- Tesseract 미설치 시 스캔 PDF 추출 불가 (텍스트 레이어 있는 PDF 권장)
- 외화 거래처 원화 환산 미적용
- 분기별 비교·후속측정 미지원 (기말 시점 1회 표본만 설계)

---

## 기술 스택

Flask / SQLAlchemy / openpyxl / pandas / pdfplumber / pytest
