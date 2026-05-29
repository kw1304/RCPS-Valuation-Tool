# BC 회신본 PDF→AC 매핑 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 회신서 PDF를 양식 지문으로 식별 → 양식별 섹션↔AC 매핑표로 구역을 잘라 정확히 추출하는 5단계 조립라인 구축.

**Architecture:** `FormFingerprinter`(양식 식별) → `FormProfile`(YAML 매핑표) → `SectionSplitter`(헤더 앵커 분할) → AC별 `RowParser` → 우편 fallback. 기존 라인 단위 키워드 추측(`section_classifier`)을 대체. `parse_responses` UC에서 조립.

**Tech Stack:** Python 3.11, pydantic v2, sqlmodel, pdfplumber, pytest, PyYAML.

설계서: `docs/superpowers/specs/2026-05-29-bc-pdf-mapping-redesign-design.md`

---

## File Structure

**신규**
- `src/infrastructure/pdf/form_fingerprint.py` — 양식 패밀리 식별
- `configs/form_profiles.yaml` — 양식별 섹션번호→AC 매핑표 (데이터)
- `src/infrastructure/pdf/form_profile.py` — YAML 로더 + 라우팅 조회
- `src/infrastructure/pdf/section_splitter.py` — 헤더 앵커 구역 분할
- `src/infrastructure/pdf/row_parsers/__init__.py`
- `src/infrastructure/pdf/row_parsers/base.py` — 공통 토큰 추출 (AC1 방식 일반화)
- `src/infrastructure/pdf/row_parsers/ac2_borrowing.py`
- `src/infrastructure/pdf/row_parsers/ac4_guarantee.py`
- `src/infrastructure/pdf/row_parsers/ac5_collateral.py`
- `src/infrastructure/pdf/row_parsers/ac6_bills.py`
- 테스트: `tests/unit/test_form_fingerprint.py`, `test_form_profile.py`, `test_section_splitter.py`, `test_row_parser_ac2.py`, `test_row_parser_ac4.py`, `test_row_parser_ac5.py`, `test_row_parser_ac6.py`
- 골든 픽스처: `tests/fixtures/sections/*.txt` (대표 양식 섹션 텍스트)

**수정**
- `src/infrastructure/db/models.py:49-59` — `ExtractedRecord`에 `needs_manual_review: bool = False`, `form_family: Optional[str]` 추가
- `src/domain/ac_models.py` — `Borrowing`에 17컬럼 필드 보강, `Guarantee`/`Collateral`/`BillCheck`에 `direction`(제공/제공받음) sub-section 필드
- `src/application/parse_response_uc.py` — 새 파이프라인으로 교체
- 기존 `section_classifier.py`, `generic_parser.py`의 `parse_ac2`~`ac8` — 신규 row_parser로 대체 후 제거 (AC1 함수는 base로 이전)

---

## Phase 1 — 공통 엔진 (지문·매핑표·분할)

### Task 1: 양식 지문 데이터 픽스처 준비

**Files:**
- Create: `tests/fixtures/sections/bank.txt`, `securities.txt`, `insurance.txt`, `surety.txt`, `postal_ocr.txt`

- [ ] **Step 1: 대표 양식별 헤더+첫 데이터행 텍스트를 픽스처로 추출**

Run:
```bash
cd c:/Claude/BC_CONFIRMATION_TOOL && python -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text_and_tables
reps={
 'bank':'INPUT/온라인/전자_[BC-1]_코스맥스비티아이(주)_[124-81-22463]_국민은행_[2025년12월31일].pdf',
 'securities':'INPUT/온라인/전자_[BC-13]_코스맥스비티아이（주）_[124-81-22463]_KB증권_[2025년12월31일].pdf',
 'insurance':'INPUT/온라인/전자_[BC-19]_코스맥스비티아이（주）_[124-81-22463]_KB손해보험_[2025년12월31일].pdf',
 'surety':'INPUT/온라인/전자_[BC-22]_코스맥스비티아이（주）_[124-81-22463]_서울보증보험_[2025년12월31일].pdf',
}
import os; os.makedirs('tests/fixtures/sections',exist_ok=True)
for k,p in reps.items():
    t=extract_text_and_tables(Path(p))['text']
    Path(f'tests/fixtures/sections/{k}.txt').write_text(t,encoding='utf-8')
    print(k,len(t))
"
```
Expected: 4개 파일 생성, 각 len > 1000

- [ ] **Step 2: 우편 OCR 픽스처 생성**

Run:
```bash
cd c:/Claude/BC_CONFIRMATION_TOOL && python -c "
import sys; sys.path.insert(0,'.')
from pathlib import Path
from src.infrastructure.pdf.ocr import ocr_pdf
t=ocr_pdf(Path('INPUT/우편/BC-26_신한은행 홍콩.pdf'))['text']
Path('tests/fixtures/sections/postal_ocr.txt').write_text(t,encoding='utf-8')
print('postal',len(t))
"
```
Expected: postal.txt 생성 (헤더 번호 거의 없음 — fallback 테스트용)

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/sections/
git commit -m "test(bc): 양식별 섹션 픽스처 추가"
```

---

### Task 2: FormFingerprinter — 양식 식별

**Files:**
- Create: `src/infrastructure/pdf/form_fingerprint.py`
- Test: `tests/unit/test_form_fingerprint.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_form_fingerprint.py
from pathlib import Path
from src.infrastructure.pdf.form_fingerprint import identify_form

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"

def _txt(name): return (FIX / name).read_text(encoding="utf-8")

def test_bank_form():
    assert identify_form(_txt("bank.txt")) == "bank"

def test_securities_form():
    assert identify_form(_txt("securities.txt")) == "securities"

def test_insurance_form():
    assert identify_form(_txt("insurance.txt")) == "insurance"

def test_surety_form():
    assert identify_form(_txt("surety.txt")) == "surety"

def test_postal_ocr_unknown():
    assert identify_form(_txt("postal_ocr.txt")) == "unknown"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_form_fingerprint.py -v`
Expected: FAIL — ModuleNotFoundError: form_fingerprint

- [ ] **Step 3: 구현**

```python
# src/infrastructure/pdf/form_fingerprint.py
"""회신서 텍스트 → 양식 패밀리 식별.

번호 섹션 헤더("N. ...다음과 같습니다")의 첫 헤더 문구로 양식 구분.
헤더 0개(우편 OCR) → "unknown".
"""
import re
from typing import Literal

FormFamily = Literal["bank", "securities", "insurance", "surety", "unknown"]

_HEADER = re.compile(r"^\s*(\d{1,2})\.\s*(.{6,90}?)(?:습니다|입니다)")


def _section_headers(text: str) -> list[tuple[int, str]]:
    out = []
    for ln in text.splitlines():
        m = _HEADER.match(ln.strip())
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
    return out


def identify_form(text: str) -> FormFamily:
    headers = _section_headers(text)
    if not headers:
        return "unknown"
    first = headers[0][1]
    joined = " ".join(h for _, h in headers)
    # 보증보험: 첫 헤더가 "대출, 채무, 의무 이행...보증" — 가장 specific 먼저
    if "의무" in first and "보증" in first:
        return "surety"
    # 손보: 첫 헤더 "보험거래 내용"
    if "보험거래" in first:
        return "insurance"
    # 증권: 첫 헤더 "당사가 보유하고 있는...유가증권 등 금융상품"
    if "보유하고 있는" in first:
        return "securities"
    # 은행: 첫 헤더 "당 은행에 대한 금융상품" + 어음·당좌 섹션 존재
    if "금융상품" in first:
        return "bank"
    return "unknown"
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_form_fingerprint.py -v`
Expected: 5 passed

- [ ] **Step 5: 30개 전수 회귀 확인 (수동)**

Run:
```bash
cd c:/Claude/BC_CONFIRMATION_TOOL && python -c "
import sys,glob,os; sys.path.insert(0,'.')
from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.form_fingerprint import identify_form
from collections import Counter
c=Counter()
for p in sorted(glob.glob('INPUT/온라인/*.pdf'))+sorted(glob.glob('INPUT/우편/*.pdf')):
    t=extract_text_and_tables(Path(p))['text']
    if len(t.strip())<80: t=ocr_pdf(Path(p))['text']
    c[identify_form(t)]+=1
print(dict(c))
"
```
Expected: `{'securities': 10, 'bank': 9, 'insurance': 4, 'surety': 1, 'unknown': 6}`

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/pdf/form_fingerprint.py tests/unit/test_form_fingerprint.py
git commit -m "feat(bc): FormFingerprinter — 양식 4종+우편 식별"
```

---

### Task 3: FormProfile — 섹션→AC 매핑표 (YAML 데이터)

**Files:**
- Create: `configs/form_profiles.yaml`, `src/infrastructure/pdf/form_profile.py`
- Test: `tests/unit/test_form_profile.py`

- [ ] **Step 1: YAML 매핑표 작성**

```yaml
# configs/form_profiles.yaml
# 양식별 섹션번호 → {ac, direction}. direction: provided=회사가 제공, received=회사가 제공받음
bank:
  1: {ac: AC1}
  2: {ac: AC2}
  3: {ac: AC4, direction: received}
  4: {ac: AC3}
  5: {ac: AC5, direction: provided}
  6: {ac: AC6, direction: provided}
  7: {ac: AC6, direction: provided}
  8: {ac: AC6, direction: received}
  10: {ac: AC6, sub: 당좌}
securities:
  1: {ac: AC1}
  2: {ac: AC1_DETAIL}
  3: {ac: AC2}
  4: {ac: AC4, direction: received}
  5: {ac: AC3}
  6: {ac: AC5, direction: provided}
  7: {ac: AC6, direction: received}
insurance:
  1: {ac: AC7}
  2: {ac: AC2}
  3: {ac: AC4, direction: received}
  4: {ac: AC6, direction: received}
  5: {ac: AC5, direction: provided}
surety:
  1: {ac: AC4, direction: received}
  2: {ac: AC7}
  3: {ac: AC7}
  4: {ac: AC2}
  5: {ac: AC1}
  6: {ac: AC4, direction: received}
  7: {ac: AC6, direction: received}
  8: {ac: AC5, direction: provided}
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_form_profile.py
from src.infrastructure.pdf.form_profile import FormProfile

def test_bank_section2_is_ac2():
    p = FormProfile.load()
    assert p.route("bank", 2)["ac"] == "AC2"

def test_securities_section2_is_detail():
    p = FormProfile.load()
    assert p.route("securities", 2)["ac"] == "AC1_DETAIL"

def test_insurance_section1_is_ac7():
    p = FormProfile.load()
    assert p.route("insurance", 1)["ac"] == "AC7"

def test_provided_direction_marked():
    p = FormProfile.load()
    assert p.route("bank", 5)["direction"] == "provided"

def test_unknown_section_returns_none():
    p = FormProfile.load()
    assert p.route("bank", 99) is None
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_form_profile.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: 구현**

```python
# src/infrastructure/pdf/form_profile.py
from pathlib import Path
import yaml

_CONFIG = Path(__file__).resolve().parents[3] / "configs" / "form_profiles.yaml"


class FormProfile:
    def __init__(self, data: dict):
        self._data = data

    @classmethod
    def load(cls, path: Path | None = None) -> "FormProfile":
        p = path or _CONFIG
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        # YAML 키(섹션번호)를 int로 정규화
        norm = {fam: {int(k): v for k, v in secs.items()} for fam, secs in raw.items()}
        return cls(norm)

    def route(self, family: str, section_no: int) -> dict | None:
        """(family, 섹션번호) → {ac, direction?, sub?} 또는 None."""
        return self._data.get(family, {}).get(section_no)
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_form_profile.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add configs/form_profiles.yaml src/infrastructure/pdf/form_profile.py tests/unit/test_form_profile.py
git commit -m "feat(bc): FormProfile — 양식별 섹션→AC 매핑표(YAML)"
```

---

### Task 4: SectionSplitter — 헤더 앵커 구역 분할

**Files:**
- Create: `src/infrastructure/pdf/section_splitter.py`
- Test: `tests/unit/test_section_splitter.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_section_splitter.py
from pathlib import Path
from src.infrastructure.pdf.section_splitter import split_sections

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "sections"

def test_bank_splits_into_numbered_blocks():
    text = (FIX / "bank.txt").read_text(encoding="utf-8")
    blocks = split_sections(text)
    # 은행형은 1,2,3,4,5,6,7,8,10 섹션
    assert 1 in blocks and 2 in blocks and 10 in blocks
    # 1번 블록(예금)에 예금 데이터가, 2번 블록(대출)에 대출 데이터가
    assert "예금" in blocks[1] or "통장" in blocks[1]

def test_block_boundary_no_leak():
    # 2번(대출) 블록에 1번 예금 데이터가 새지 않아야
    text = (FIX / "bank.txt").read_text(encoding="utf-8")
    blocks = split_sections(text)
    # 대출 블록은 "대출" 헤더 다음부터 "지급보증" 헤더 전까지
    assert "대출" in blocks[2] or "한도" in blocks[2]

def test_empty_text_returns_empty():
    assert split_sections("") == {}
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_section_splitter.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 구현**

```python
# src/infrastructure/pdf/section_splitter.py
"""번호 섹션 헤더 앵커로 텍스트를 구역별로 분할.

헤더 라인("N. ...다음과 같습니다")을 경계로, 헤더 다음 줄부터
다음 헤더 전까지를 그 섹션 번호의 블록으로 모은다.
라인 단위 키워드 추측(구 section_classifier)을 대체 — drift 없음.
"""
import re

_HEADER = re.compile(r"^\s*(\d{1,2})\.\s*.{6,90}?(?:습니다|입니다)")


def split_sections(text: str) -> dict[int, str]:
    blocks: dict[int, list[str]] = {}
    current: int | None = None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = _HEADER.match(s)
        if m:
            current = int(m.group(1))
            blocks.setdefault(current, [])
            continue  # 헤더 문장 자체는 데이터 아님
        if current is not None:
            blocks[current].append(s)
    return {k: "\n".join(v) for k, v in blocks.items() if v}
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_section_splitter.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/pdf/section_splitter.py tests/unit/test_section_splitter.py
git commit -m "feat(bc): SectionSplitter — 헤더 앵커 구역 분할(drift 제거)"
```

---

## Phase 2 — AC별 RowParser (우선순위 AC2→AC4→AC5→AC6)

### Task 5: 공통 토큰 추출 base (AC1 로직 일반화)

**Files:**
- Create: `src/infrastructure/pdf/row_parsers/__init__.py` (빈 파일), `src/infrastructure/pdf/row_parsers/base.py`
- Test: `tests/unit/test_row_parser_base.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_row_parser_base.py
from decimal import Decimal
from datetime import date
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

def test_tokenize_extracts_dates_amounts_ccy():
    row = "일반자금대출 KRW 1,000,000,000 5,000,000 20250610 20260610 4.5000"
    tok = tokenize_row(row)
    assert tok.currency == "KRW"
    assert Decimal("1000000000") in tok.amounts
    assert date(2025, 6, 10) in tok.dates
    assert tok.rate == Decimal("4.5000")

def test_noise_line_detected():
    assert is_noise("해당 거래 없음")
    assert is_noise("확인자 소속 및 직위 : 기업금융")
    assert not is_noise("일반자금대출 1,000,000,000")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_row_parser_base.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 구현**

```python
# src/infrastructure/pdf/row_parsers/base.py
"""AC별 RowParser 공통 토큰 추출. generic_parser._parse_line 일반화."""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

_CCY_SET = {"KRW", "USD", "EUR", "JPY", "CNY", "HKD", "GBP", "AUD", "SGD", "CNH"}
_DATE_8 = re.compile(r"^\d{8}$")
_RATE = re.compile(r"^\d+\.\d{2,5}$")
_NUM = re.compile(r"^[\d,]+(?:\.\d+)?$")
_ACCT = re.compile(r"^[0-9\-]{8,22}$")
_PAREN = re.compile(r"^\([\d,.\-]+\)$")

_NOISE = [
    "조회기준일", "다음과 같", "참고 목적", "정확성", "해당 거래 없음",
    "해당사항 없음", "확인자", "당 은행", "당사", "면책", "유의사항",
]


def is_noise(line: str) -> bool:
    s = line.strip()
    if not s or len(s) < 4:
        return True
    return any(p in s for p in _NOISE)


def _ymd(s: str) -> date | None:
    if not s or s == "00000000" or len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", ""))
    except Exception:
        return None


@dataclass
class RowTokens:
    account: str | None = None
    currency: str | None = None
    amounts: list[Decimal] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    rate: Decimal | None = None
    text_tokens: list[str] = field(default_factory=list)


def tokenize_row(row: str) -> RowTokens:
    t = RowTokens()
    for tok in row.split():
        if tok in _CCY_SET:
            t.currency = tok
        elif _DATE_8.match(tok):
            d = _ymd(tok)
            if d:
                t.dates.append(d)
        elif _RATE.match(tok) and t.rate is None:
            t.rate = _dec(tok)
        elif _PAREN.match(tok):
            continue  # 누적이자 등 괄호 토큰 skip
        elif _ACCT.match(tok) and "," not in tok and t.account is None:
            t.account = tok
        elif _NUM.match(tok):
            v = _dec(tok)
            if v is not None:
                t.amounts.append(v)
        else:
            t.text_tokens.append(tok)
    return t
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_row_parser_base.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/pdf/row_parsers/
git commit -m "feat(bc): RowParser 공통 토큰 추출 base"
```

---

### Task 6: AC2 차입금 RowParser (17컬럼)

**Files:**
- Create: `src/infrastructure/pdf/row_parsers/ac2_borrowing.py`
- Modify: `src/domain/ac_models.py` (Borrowing 필드 보강)
- Test: `tests/unit/test_row_parser_ac2.py`

- [ ] **Step 1: Borrowing 모델 17컬럼 보강**

`src/domain/ac_models.py`의 `Borrowing`(49-57행)을 교체:

```python
class Borrowing(_Base):                   # AC2
    contract_type: str                    # 대출종류
    limit_ccy: str = "KRW"                # 한도통화
    limit_amt: Decimal = Decimal("0")     # 한도금액
    balance_ccy: str = "KRW"              # 잔액통화
    balance: Decimal = Decimal("0")       # 대출금액(잔액)
    contract_date: date | None = None     # 대출일
    maturity: date | None = None          # 최종만기일
    rate: Decimal | None = None           # 연이자율
    last_interest_date: date | None = None  # 최종이자지급일
    repayment: str | None = None          # 상환방법
    collateral: str | None = None         # 담보·보증
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_row_parser_ac2.py
from decimal import Decimal
from datetime import date
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2

def test_parse_loan_row():
    block = """운영일반운전자금대출 14,500,000,000 0 20250610 20260610 4.5000 20251210 일시상환 9차담보제공
당좌대출 5,000,000,000 0 20210219 20260213 4.6600 20251219 일시상환 9차담보제공"""
    recs = parse_ac2(block, bc_no="BC-1", bank="국민은행")
    assert len(recs) == 2
    assert recs[0].limit_amt == Decimal("14500000000")
    assert recs[0].maturity == date(2026, 6, 10)
    assert recs[0].rate == Decimal("4.5000")
    assert "일시상환" in (recs[0].repayment or "")

def test_no_deal_returns_empty():
    assert parse_ac2("해당 거래 없음", bc_no="BC-1", bank="국민은행") == []
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac2.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: 구현**

```python
# src/infrastructure/pdf/row_parsers/ac2_borrowing.py
"""AC2 차입금(대출) 파서. 한도금액·잔액·대출일·만기·이자율·상환방법·담보."""
from decimal import Decimal
from src.domain.ac_models import Borrowing
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac2(block: str, bc_no: str, bank: str) -> list[Borrowing]:
    out: list[Borrowing] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        # 차입금 행 판정: 금액 토큰 1개 이상 + (날짜 또는 금리)
        if not t.amounts or not (t.dates or t.rate):
            continue
        amts = t.amounts
        limit = amts[0] if len(amts) >= 1 else Decimal("0")
        balance = amts[1] if len(amts) >= 2 else amts[0]
        contract_date = t.dates[0] if len(t.dates) >= 1 else None
        maturity = t.dates[1] if len(t.dates) >= 2 else None
        last_int = t.dates[2] if len(t.dates) >= 3 else None
        # 상환방법·담보: 후미 텍스트 토큰
        tail = " ".join(t.text_tokens)
        contract_type = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        repayment = next((w for w in t.text_tokens if "상환" in w), None)
        collateral = next((w for w in t.text_tokens if "담보" in w or "보증" in w), None)
        out.append(Borrowing(
            bc_no=bc_no, bank=bank, contract_type=contract_type,
            limit_ccy=t.currency or "KRW", limit_amt=limit,
            balance_ccy=t.currency or "KRW", balance=balance,
            contract_date=contract_date, maturity=maturity,
            rate=t.rate, last_interest_date=last_int,
            repayment=repayment, collateral=collateral,
        ))
    return out
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac2.py tests/unit/test_ac_models.py -v`
Expected: 모두 passed (ac_models 회귀 포함)

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/pdf/row_parsers/ac2_borrowing.py src/domain/ac_models.py tests/unit/test_row_parser_ac2.py
git commit -m "feat(bc): AC2 차입금 RowParser — 한도·잔액·만기·이자율·상환·담보"
```

---

### Task 7: AC4 지급보증 RowParser (제공/제공받음 direction)

**Files:**
- Create: `src/infrastructure/pdf/row_parsers/ac4_guarantee.py`
- Modify: `src/domain/ac_models.py` (Guarantee에 direction 필드)
- Test: `tests/unit/test_row_parser_ac4.py`

- [ ] **Step 1: Guarantee 모델에 direction 추가**

`src/domain/ac_models.py`의 `Guarantee`(70-76행)에 필드 추가:

```python
class Guarantee(_Base):                   # AC4
    guarantee_type: str
    limit_ccy: str = "KRW"
    limit_amt: Decimal = Decimal("0")
    balance_ccy: str = "KRW"
    balance: Decimal = Decimal("0")
    maturity: date | None = None
    direction: str = "received"           # received=제공받음 / provided=제공
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_row_parser_ac4.py
from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac4_guarantee import parse_ac4

def test_parse_guarantee_with_direction():
    block = "지급보증 L/C 100,000,000 80,000,000 20251231"
    recs = parse_ac4(block, bc_no="BC-1", bank="국민은행", direction="received")
    assert len(recs) == 1
    assert recs[0].limit_amt == Decimal("100000000")
    assert recs[0].direction == "received"

def test_no_deal_returns_empty():
    assert parse_ac4("해당 거래 없음", bc_no="BC-1", bank="국민은행", direction="received") == []
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac4.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: 구현**

```python
# src/infrastructure/pdf/row_parsers/ac4_guarantee.py
"""AC4 지급보증 파서. direction: received(제공받음)/provided(제공)."""
from decimal import Decimal
from src.domain.ac_models import Guarantee
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac4(block: str, bc_no: str, bank: str, direction: str = "received") -> list[Guarantee]:
    out: list[Guarantee] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        amts = t.amounts
        gtype = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        out.append(Guarantee(
            bc_no=bc_no, bank=bank, guarantee_type=gtype,
            limit_ccy=t.currency or "KRW", limit_amt=amts[0],
            balance_ccy=t.currency or "KRW",
            balance=amts[1] if len(amts) >= 2 else Decimal("0"),
            maturity=t.dates[0] if t.dates else None,
            direction=direction,
        ))
    return out
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac4.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/pdf/row_parsers/ac4_guarantee.py src/domain/ac_models.py tests/unit/test_row_parser_ac4.py
git commit -m "feat(bc): AC4 지급보증 RowParser — direction(제공/제공받음)"
```

---

### Task 8: AC5 담보제공자산 RowParser

**Files:**
- Create: `src/infrastructure/pdf/row_parsers/ac5_collateral.py`
- Modify: `src/domain/ac_models.py` (Collateral에 direction)
- Test: `tests/unit/test_row_parser_ac5.py`

- [ ] **Step 1: Collateral 모델에 direction 추가**

`src/domain/ac_models.py`의 `Collateral`(79-85행)에 추가: `direction: str = "provided"`

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_row_parser_ac5.py
from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5

def test_parse_collateral():
    block = "부동산근저당 1,200,000,000 900,000,000"
    recs = parse_ac5(block, bc_no="BC-1", bank="국민은행", direction="provided")
    assert len(recs) == 1
    assert recs[0].book_amount == Decimal("1200000000")
    assert recs[0].direction == "provided"

def test_no_deal_empty():
    assert parse_ac5("해당 거래 없음", bc_no="BC-1", bank="국민은행", direction="provided") == []
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac5.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: 구현**

```python
# src/infrastructure/pdf/row_parsers/ac5_collateral.py
"""AC5 담보제공자산 파서. direction: provided(제공)/received(제공받음)."""
from decimal import Decimal
from src.domain.ac_models import Collateral
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac5(block: str, bc_no: str, bank: str, direction: str = "provided") -> list[Collateral]:
    out: list[Collateral] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        ctype = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        out.append(Collateral(
            bc_no=bc_no, bank=bank, collateral_type=ctype,
            book_amount=t.amounts[0],
            appraised_amount=t.amounts[1] if len(t.amounts) >= 2 else None,
            direction=direction,
        ))
    return out
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac5.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/pdf/row_parsers/ac5_collateral.py src/domain/ac_models.py tests/unit/test_row_parser_ac5.py
git commit -m "feat(bc): AC5 담보제공자산 RowParser"
```

---

### Task 9: AC6 어음·수표·당좌 RowParser

**Files:**
- Create: `src/infrastructure/pdf/row_parsers/ac6_bills.py`
- Modify: `src/domain/ac_models.py` (BillCheck에 direction/sub)
- Test: `tests/unit/test_row_parser_ac6.py`

- [ ] **Step 1: BillCheck 모델 보강**

`src/domain/ac_models.py`의 `BillCheck`(88-91행)을 교체:

```python
class BillCheck(_Base):                   # AC6
    kind: str
    count: int = 0
    balance: Decimal = Decimal("0")
    direction: str = "received"           # received=교부받음 / provided=교부 / 당좌
    sub: str | None = None                # 당좌 등
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/unit/test_row_parser_ac6.py
from decimal import Decimal
from src.infrastructure.pdf.row_parsers.ac6_bills import parse_ac6

def test_parse_bill():
    block = "약속어음 3 50,000,000"
    recs = parse_ac6(block, bc_no="BC-1", bank="국민은행", direction="received")
    assert len(recs) == 1
    assert recs[0].direction == "received"

def test_dangjwa_sub():
    block = "당좌예금 09360101 1,500,000"
    recs = parse_ac6(block, bc_no="BC-1", bank="국민은행", direction="provided", sub="당좌")
    assert recs[0].sub == "당좌"

def test_no_deal_empty():
    assert parse_ac6("해당 거래 없음", bc_no="BC-1", bank="국민은행", direction="received") == []
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac6.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: 구현**

```python
# src/infrastructure/pdf/row_parsers/ac6_bills.py
"""AC6 어음·수표·당좌 파서. direction: received(교부받음)/provided(교부)."""
from decimal import Decimal
from src.domain.ac_models import BillCheck
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise


def parse_ac6(block: str, bc_no: str, bank: str,
              direction: str = "received", sub: str | None = None) -> list[BillCheck]:
    out: list[BillCheck] = []
    for line in block.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts and not t.text_tokens:
            continue
        kind = (t.text_tokens[0] if t.text_tokens else s.split()[0])[:40]
        # 매수(count): 작은 정수 금액 토큰, 잔액: 큰 금액
        count = 0
        balance = Decimal("0")
        if t.amounts:
            ints = [a for a in t.amounts if a == a.to_integral_value() and a < 1000]
            count = int(ints[0]) if ints else 0
            big = [a for a in t.amounts if a >= 1000]
            balance = big[0] if big else (t.amounts[-1] if t.amounts else Decimal("0"))
        out.append(BillCheck(
            bc_no=bc_no, bank=bank, kind=kind,
            count=count, balance=balance, direction=direction, sub=sub,
        ))
    return out
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_row_parser_ac6.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/infrastructure/pdf/row_parsers/ac6_bills.py src/domain/ac_models.py tests/unit/test_row_parser_ac6.py
git commit -m "feat(bc): AC6 어음·수표·당좌 RowParser"
```

---

## Phase 3 — fallback·조립·배선

### Task 10: ExtractedRecord에 수동검토 플래그 추가

**Files:**
- Modify: `src/infrastructure/db/models.py:49-59`
- Test: `tests/unit/test_db_models.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_db_models.py`에 추가:

```python
def test_extracted_record_manual_review_flag():
    from src.infrastructure.db.models import ExtractedRecord
    r = ExtractedRecord(project_id=1, counterparty_id=1, ac_section="AC2",
                        payload_json="{}", needs_manual_review=True, form_family="unknown")
    assert r.needs_manual_review is True
    assert r.form_family == "unknown"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_db_models.py::test_extracted_record_manual_review_flag -v`
Expected: FAIL — unexpected keyword argument

- [ ] **Step 3: 구현 — 모델에 필드 2개 추가**

`src/infrastructure/db/models.py`의 `ExtractedRecord`에 추가 (59행 뒤):

```python
    needs_manual_review: bool = False            # 우편/비표준 → 감사인 직접 확인
    form_family: Optional[str] = None            # bank|securities|insurance|surety|unknown
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_db_models.py -v`
Expected: 모두 passed

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/db/models.py tests/unit/test_db_models.py
git commit -m "feat(bc): ExtractedRecord에 needs_manual_review·form_family 추가"
```

---

### Task 11: fallback 파서 (우편/unknown)

**Files:**
- Create: `src/infrastructure/pdf/row_parsers/fallback.py`
- Test: `tests/unit/test_fallback_parser.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/test_fallback_parser.py
from src.infrastructure.pdf.row_parsers.fallback import fallback_parse

def test_fallback_flags_manual_review():
    text = "신한은행 홍콩 USD 예금 잔액 100,000"
    recs = fallback_parse(text, bc_no="BC-26", bank="신한은행 홍콩")
    # 모든 레코드는 (ac_section, payload, needs_manual_review=True)
    assert all(r["needs_manual_review"] for r in recs)
    assert recs and recs[0]["ac_section"] == "AC1"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_fallback_parser.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 구현**

```python
# src/infrastructure/pdf/row_parsers/fallback.py
"""우편/unknown 양식 best-effort 파서. 모든 레코드 needs_manual_review=True.

억지 자동화로 틀린 숫자를 넣지 않는다 — 감사인 직접 확인용 후보만 추출.
"""
from src.infrastructure.pdf.row_parsers.base import tokenize_row, is_noise

_AC_KEYWORDS = {
    "AC1": ["예금", "deposit", "잔액", "balance", "유가증권", "주식", "펀드"],
    "AC2": ["대출", "차입", "loan", "borrowing"],
    "AC4": ["지급보증", "보증", "guarantee", "L/C"],
    "AC5": ["담보", "근저당", "collateral"],
    "AC6": ["어음", "수표", "당좌"],
    "AC7": ["보험", "insurance"],
}


def fallback_parse(text: str, bc_no: str, bank: str) -> list[dict]:
    out: list[dict] = []
    for line in text.splitlines():
        s = line.strip()
        if is_noise(s):
            continue
        t = tokenize_row(s)
        if not t.amounts:
            continue
        ac = "AC1"
        for cand, kws in _AC_KEYWORDS.items():
            if any(k in s for k in kws):
                ac = cand
                break
        out.append({
            "ac_section": ac,
            "payload": {"bc_no": bc_no, "bank": bank, "raw": s[:120],
                        "amounts": [str(a) for a in t.amounts],
                        "currency": t.currency},
            "needs_manual_review": True,
        })
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_fallback_parser.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/pdf/row_parsers/fallback.py tests/unit/test_fallback_parser.py
git commit -m "feat(bc): fallback 파서 — 우편/unknown best-effort + 수동검토 플래그"
```

---

### Task 12: parse_responses UC 새 파이프라인 배선

**Files:**
- Modify: `src/application/parse_response_uc.py`
- Test: `tests/integration/test_response_route.py` (기존 회귀)

- [ ] **Step 1: AC별 RowParser 디스패치 맵 작성 + 파이프라인 교체**

`src/application/parse_response_uc.py`의 import·PARSERS·`parse_responses` 내부 파싱 루프를 교체:

```python
import json
from pathlib import Path
from sqlmodel import Session, select
from src.infrastructure.db.models import FileAsset, Counterparty, ExtractedRecord
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.filename_parser import parse_filename
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.section_splitter import split_sections
from src.infrastructure.pdf.generic_parser import parse_ac1_deposit, parse_ac1_security_details
from src.infrastructure.pdf.row_parsers.ac2_borrowing import parse_ac2
from src.infrastructure.pdf.row_parsers.ac4_guarantee import parse_ac4
from src.infrastructure.pdf.row_parsers.ac5_collateral import parse_ac5
from src.infrastructure.pdf.row_parsers.ac6_bills import parse_ac6
from src.infrastructure.pdf.row_parsers.fallback import fallback_parse
from src.domain.party_normalize import PartyNormalizer

ROOT = Path(__file__).resolve().parents[2]


def _dispatch(ac: str, block: str, bc_no: str, bank: str, route: dict):
    """(ac, block) → 도메인 레코드 리스트."""
    direction = route.get("direction", "received")
    if ac == "AC1":
        return parse_ac1_deposit(block, bc_no=bc_no, bank=bank)
    if ac == "AC1_DETAIL":
        return parse_ac1_security_details(block, bc_no=bc_no, bank=bank)
    if ac == "AC2":
        return parse_ac2(block, bc_no=bc_no, bank=bank)
    if ac == "AC4":
        return parse_ac4(block, bc_no=bc_no, bank=bank, direction=direction)
    if ac == "AC5":
        return parse_ac5(block, bc_no=bc_no, bank=bank, direction=direction)
    if ac == "AC6":
        return parse_ac6(block, bc_no=bc_no, bank=bank, direction=direction, sub=route.get("sub"))
    return []  # AC3·AC7·AC8 후순위 — 추후 추가


def parse_responses(session: Session, project_id: int) -> dict:
    norm = PartyNormalizer.load(ROOT / "configs")
    profile = FormProfile.load()
    files = session.exec(
        select(FileAsset).where(FileAsset.project_id == project_id, FileAsset.kind == "response")
    ).all()
    cps = {(c.canonical_name, c.branch): c for c in session.exec(
        select(Counterparty).where(Counterparty.project_id == project_id)
    ).all()}
    records_summary = []

    for f in files:
        meta = parse_filename(f.original_name)
        bc_no = meta.get("bc_no") or ""
        bank_raw = meta.get("bank_raw") or ""
        np = norm.normalize(bank_raw) if bank_raw else None
        bank = np.canonical if np else bank_raw
        ext = extract_text_and_tables(Path(f.stored_path))
        text = ext["text"]
        if len(text.strip()) < 80:
            text = ocr_pdf(Path(f.stored_path))["text"]
        cp = cps.get((np.canonical, np.branch)) if np else None
        if cp:
            cp.response_arrived = True
            session.add(cp)

        family = identify_form(text)

        def _persist(ac, payload_obj, manual, confidence):
            payload = json.dumps(payload_obj, default=str, ensure_ascii=False) \
                if isinstance(payload_obj, dict) else payload_obj.model_dump_json()
            er = ExtractedRecord(
                project_id=project_id, counterparty_id=cp.id if cp else 0,
                ac_section=ac, payload_json=payload, confidence=confidence,
                source_file=f.original_name, needs_manual_review=manual,
                form_family=family,
            )
            session.add(er); session.flush()
            records_summary.append({"section": ac, "bc_no": bc_no, "bank": bank,
                                    "confidence": confidence, "needs_manual_review": manual,
                                    "payload": json.loads(payload)})

        if family == "unknown":
            for rec in fallback_parse(text, bc_no=bc_no, bank=bank):
                _persist(rec["ac_section"], rec["payload"], True, "low")
            continue

        blocks = split_sections(text)
        for section_no, block in blocks.items():
            route = profile.route(family, section_no)
            if not route:
                continue
            ac = route["ac"]
            try:
                recs = _dispatch(ac, block, bc_no, bank, route)
            except Exception:
                recs = []
            target_ac = "AC1" if ac == "AC1_DETAIL" else ac
            store_ac = "AC1_DETAIL" if ac == "AC1_DETAIL" else ac
            for rec in recs:
                _persist(store_ac, rec, False, "high")

    session.commit()
    return {"records": records_summary}
```

- [ ] **Step 2: 기존 통합 테스트 회귀 확인**

Run: `python -m pytest tests/integration/test_response_route.py -v`
Expected: PASS (AC1 기존 동작 유지 + 신규 AC2/4/5/6 레코드 생성)

- [ ] **Step 3: 전체 파이프라인 e2e 확인**

Run: `python -m pytest tests/e2e/test_full_pipeline.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/application/parse_response_uc.py
git commit -m "feat(bc): parse_responses 새 5단계 파이프라인 배선"
```

---

### Task 13: 30개 회신서 실전 검증 + 골든 카운트

**Files:**
- Create: `tests/integration/test_real_replies_smoke.py`

- [ ] **Step 1: 실전 추출 카운트 스모크 테스트**

```python
# tests/integration/test_real_replies_smoke.py
import glob
from pathlib import Path
import pytest
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.ocr import ocr_pdf
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.section_splitter import split_sections

ROOT = Path(__file__).resolve().parents[2]
PDFS = sorted(glob.glob(str(ROOT / "INPUT" / "온라인" / "*.pdf")))

@pytest.mark.skipif(not PDFS, reason="INPUT PDFs 없음")
def test_every_electronic_pdf_identified_and_split():
    profile = FormProfile.load()
    for p in PDFS:
        t = extract_text_and_tables(Path(p))["text"]
        if len(t.strip()) < 80:
            t = ocr_pdf(Path(p))["text"]
        fam = identify_form(t)
        # 전자 회신서는 unknown이면 안 됨
        assert fam != "unknown", f"{Path(p).name} → unknown (식별 실패)"
        blocks = split_sections(t)
        assert blocks, f"{Path(p).name} → 섹션 분할 0"
        # 적어도 하나의 섹션이 매핑표에 라우팅돼야
        assert any(profile.route(fam, n) for n in blocks), f"{Path(p).name} 라우팅 0"
```

- [ ] **Step 2: 실행 확인**

Run: `python -m pytest tests/integration/test_real_replies_smoke.py -v`
Expected: PASS (24 전자 회신서 모두 식별·분할·라우팅)

- [ ] **Step 3: 추출 결과 육안 검증 (수동)**

Run:
```bash
cd c:/Claude/BC_CONFIRMATION_TOOL && python -c "
import sys,glob; sys.path.insert(0,'.')
from pathlib import Path
from src.infrastructure.pdf.extractor import extract_text_and_tables
from src.infrastructure.pdf.form_fingerprint import identify_form
from src.infrastructure.pdf.form_profile import FormProfile
from src.infrastructure.pdf.section_splitter import split_sections
from src.application.parse_response_uc import _dispatch
prof=FormProfile.load()
p=[x for x in glob.glob('INPUT/온라인/*.pdf') if '국민은행' in x][0]
t=extract_text_and_tables(Path(p))['text']
fam=identify_form(t); blocks=split_sections(t)
print('family',fam)
for n,b in blocks.items():
    r=prof.route(fam,n)
    if not r: continue
    recs=_dispatch(r['ac'],b,'BC-1','국민은행',r)
    print(f'섹션{n}→{r[\"ac\"]}: {len(recs)}건')
"
```
Expected: 섹션2→AC2 차입금 N건, 섹션3→AC4 등 0 아닌 건수. 0이면 해당 RowParser 토큰 로직 보정 (executing 단계에서 systematic-debugging).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_real_replies_smoke.py
git commit -m "test(bc): 30개 회신서 식별·분할·라우팅 스모크"
```

---

### Task 14: 구 section_classifier·generic_parser 정리

**Files:**
- Modify: `src/infrastructure/pdf/generic_parser.py` (parse_ac2~ac8 제거)
- Delete: `src/infrastructure/pdf/section_classifier.py`
- Modify: `tests/unit/test_section_classifier.py`, `tests/unit/test_generic_parser.py`

- [ ] **Step 1: 구 parse_ac2~ac8 함수 제거**

`src/infrastructure/pdf/generic_parser.py`에서 `parse_ac2_borrowing`·`parse_ac3_derivative`·`parse_ac4_guarantee`·`parse_ac5_collateral`·`parse_ac6_bills`·`parse_ac7_insurance`·`parse_ac8_general` 함수(309-451행) 삭제. `parse_ac1_deposit`·`parse_ac1_security_details`·`_parse_line`·헬퍼는 유지.

- [ ] **Step 2: section_classifier 삭제 + 테스트 정리**

```bash
git rm src/infrastructure/pdf/section_classifier.py tests/unit/test_section_classifier.py
```

`tests/unit/test_generic_parser.py`에서 ac2~8 참조 테스트가 있으면 제거 (AC1 테스트만 유지).

- [ ] **Step 3: 전체 테스트 회귀**

Run: `python -m pytest tests/ -v`
Expected: 모두 passed (구 모듈 참조 잔존 ImportError 없을 것)

- [ ] **Step 4: import 잔존 확인**

Run: `grep -rn "section_classifier\|parse_ac2_borrowing\|parse_ac3_derivative" src/`
Expected: 출력 없음

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(bc): 구 section_classifier·generic parse_ac2~8 제거"
```

---

## Self-Review 결과

- **Spec §3 매핑표** → Task 3 YAML로 구현 ✓
- **Spec §4[1] 지문** → Task 2 ✓ / **[2] 매핑표** → Task 3 ✓ / **[3] 분할** → Task 4 ✓ / **[4] RowParser** → Task 5~9 ✓ / **[5] fallback** → Task 10~11 ✓
- **Spec §8 우선순위 AC2→4→5→6** → Task 6~9 순서 일치 ✓
- **Spec §7 테스트 전략** → 식별(Task2 Step5)·분할(Task4)·골든(Task13)·fallback(Task11) 모두 커버 ✓
- **타입 일관성**: `tokenize_row`/`RowTokens`(Task5) → 모든 RowParser가 동일 시그니처 사용 ✓. `route()` 반환 dict 키(`ac`/`direction`/`sub`) → `_dispatch`·YAML 일치 ✓
- **후순위 AC3·AC7·AC8**: `_dispatch` 빈 리스트 반환으로 명시 — 추후 RowParser 추가 시 분기만 추가 (의도적 미구현, placeholder 아님)
- **알려진 검증 리스크**: Task13 Step3에서 실제 추출 건수 0 나오면 RowParser 토큰 휴리스틱(매수/잔액 구분 등)을 실데이터로 보정 필요 — executing 단계에서 systematic-debugging으로 대응.
