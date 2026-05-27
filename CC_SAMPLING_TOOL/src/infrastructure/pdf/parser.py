"""조회서 회신 텍스트 파싱 — 거래처명·금액·날짜·서명 추출 (Week 4 강화 + Week 5 v2).

삼덕회계법인 표준양식 (한국어/영문) 지원:
  - 한국어: "{거래처명} 귀중 YYYY년 MM월 DD일" 헤더
  - 영문: "TO : {거래처명} YYYY- MM- DD" 헤더
  - 계정과목별 채권/채무 잔액 추출 (표 파싱 우선, 텍스트 폴백)
  - 기준일 (현재) vs 회신일자 분리
  - Week 5: declared_match (셀 수준), per_account_rows, original_currency 추가

지원 통화: KRW, USD, EUR, JPY, CNY, SGD, AUD, MYR, THB
금액 표기: KRW/USD/EUR/JPY + 숫자, 쉼표 구분, 괄호 음수
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class AccountRow:
    """계정과목별 단일 행 파싱 결과 (parse_confirmation_v2 전용)."""
    section: str                     # "receivable" | "payable"
    account_name: str
    sent_amount: Optional[float]     # 발송금액 (조회금액)
    declared_match: Optional[bool]   # 해당 행의 일치여부 셀값
    reply_amount: Optional[float]    # 회신금액
    currency: str = "KRW"
    note: str = ""


@dataclass
class ParsedReply:
    extracted_party_name: Optional[str]        # 거래처명 (귀중 앞 또는 TO: 뒤)
    period_end: Optional[date]                  # 기준일 (현재) — "YYYY년 MM월 DD일 현재"
    reply_date: Optional[str]                   # 회신일자 YYYY-MM-DD, 없으면 None
    audit_firm: Optional[str]                   # 감사인명 (삼덕회계법인 등)
    receivable_by_account: dict[str, float]     # 채권 계정과목별 회신금액
    payable_by_account: dict[str, float]        # 채무 계정과목별 회신금액
    receivable_total: Optional[float]           # 채권 합계 (회신금액)
    payable_total: Optional[float]              # 채무 합계 (회신금액)
    is_match_declared: Optional[bool]           # 회신서에 "일치" 표시 여부
    has_signature: bool                         # 서명/도장 키워드 존재
    extraction_confidence: float                # 0.0~1.0

    # ── Week 5 v2 확장 필드 ──────────────────────────────────────────────
    per_account_rows: list[AccountRow] = field(default_factory=list)
    # 계정과목별 세부 행 (표 동적 매핑 결과)
    declared_match: Optional[bool] = None
    # 종합 declared_match: 모든 행 일치→True, 하나라도 불일치→False, 혼합/없음→None
    original_currency: str = "KRW"
    # PDF에서 검출된 원통화 코드 (KRW 외에는 환산 필요)

    # ── 하위 호환성 (Week 3 API와 동일한 필드명 유지) ──
    @property
    def extracted_name(self) -> Optional[str]:
        return self.extracted_party_name

    @property
    def extracted_balance(self) -> Optional[float]:
        """채권 합계 우선, 없으면 채무 합계 반환 (하위 호환)."""
        return self.receivable_total if self.receivable_total is not None else self.payable_total

    @property
    def balance_currency(self) -> str:
        """주요 통화 추론 (하위 호환)."""
        for d in (self.receivable_by_account, self.payable_by_account):
            for acct in d:
                # 계정과목명에 통화 힌트 없음 — 금액으로 추론 불가 → KRW default
                pass
        return self._currency

    @property
    def confidence(self) -> float:
        """하위 호환성 — extraction_confidence 별명."""
        return self.extraction_confidence

    # 내부 통화 필드
    _currency: str = field(default="KRW", repr=False, compare=False)

    def __post_init__(self):
        # _currency 기본값
        if not hasattr(self, '_currency') or self._currency is None:
            object.__setattr__(self, '_currency', "KRW")


# ── 통화 패턴 ────────────────────────────────────────────────────────────────
# 순서 중요: 2자 이상 접두사 먼저 (USD, EUR, CNY 등)
_CURRENCY_PREFIXES = {
    "USD": "USD", "EUR": "EUR", "JPY": "JPY", "CNY": "CNY",
    "RMB": "CNY", "SGD": "SGD", "AUD": "AUD", "MYR": "MYR",
    "THB": "THB", "KRW": "KRW",
    "$": "USD", "￥": "JPY", "¥": "JPY", "€": "EUR",
}

_AMOUNT_NUM_RE = re.compile(r"[\d,]+(?:\.\d+)?")
_CURRENCY_AMOUNT_RE = re.compile(
    r"(USD|EUR|JPY|CNY|RMB|SGD|AUD|MYR|THB|KRW|\$|￥|¥|€)\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

# ── 날짜 패턴 ─────────────────────────────────────────────────────────────────
_DATE_KO = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_DATE_ISO = re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})")
_DATE_EN_MDY = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")  # MM.DD.YYYY
_DATE_EN_SPACED = re.compile(r"(\d{4})-\s*(\d{1,2})-\s*(\d{1,2})")  # "2026- 02- 04"

# 기준일 키워드 (해당 날짜는 period_end로 처리)
_PERIOD_END_KW = re.compile(
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*현재"
)

# ── 거래처명 패턴 ─────────────────────────────────────────────────────────────
# 삼덕 한국어: "{거래처명} 귀중|귀하 2026년 ..."  (첫 번째 줄 또는 두 번째 줄)
_PARTY_KWITO_KO = re.compile(
    r"^(.+?)\s+(?:귀중|귀하|貴下|貴中)",
    re.MULTILINE,
)
# 영문 양식: "TO : {거래처명} YYYY- ..."
_PARTY_TO_EN = re.compile(
    r"^TO\s*:\s*(.+?)\s+\d{4}",
    re.IGNORECASE | re.MULTILINE,
)
# "당사[...] 귀사[{거래처명}]" — 검증용 2차 추출
_PARTY_GUISA = re.compile(r"귀사\[([^\]]+)\]")

# ── 감사인명 ───────────────────────────────────────────────────────────────────
_AUDIT_FIRM_KO = re.compile(r"감사인명\s+(.+?)(?:\s*\n|\s*$)")
_AUDIT_FIRM_EN = re.compile(r"Accounting\s+Firm\s*:\s*(.+?)(?:\s*\n|\s*$)", re.IGNORECASE)

# ── 서명 키워드 ───────────────────────────────────────────────────────────────
_SIGNATURE_RE = re.compile(
    r"확인통지|인\)|（인）|\(인\)|서명|sign|signature|chop|Signature", re.IGNORECASE
)

# ── 표 섹션 구분 키워드 ────────────────────────────────────────────────────────
_RECV_SECTION = re.compile(r"받을\s*금액|Receivable|receivable", re.IGNORECASE)
_PAYB_SECTION = re.compile(r"지급할\s*금액|Payable|payable", re.IGNORECASE)
_TABLE_HEADER = re.compile(r"계정과목|Account", re.IGNORECASE)
_TOTAL_ROW = re.compile(r"^(?:합계|TOTAL|Total)\s*$")


# ── 금액 정규화 ────────────────────────────────────────────────────────────────
def _parse_amount(raw: str) -> Optional[float]:
    """쉼표·공백 제거, 괄호 음수 처리 → float."""
    raw = raw.strip()
    if not raw:
        return None
    negative = raw.startswith("(") or raw.startswith("（")
    cleaned = re.sub(r"[（）()\s,，]", "", raw)
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None


def _extract_currency_amount(text: str) -> tuple[Optional[float], str]:
    """텍스트에서 (금액, 통화코드) 추출."""
    m = _CURRENCY_AMOUNT_RE.search(text)
    if m:
        prefix = m.group(1).upper()
        num_str = m.group(2)
        currency = _CURRENCY_PREFIXES.get(prefix, "KRW")
        val = _parse_amount(num_str)
        return val, currency
    # 순수 숫자만 있으면 KRW
    nums = _AMOUNT_NUM_RE.findall(text)
    for n in nums:
        v = _parse_amount(n)
        if v and v >= 1:
            return v, "KRW"
    return None, "KRW"


# ── 날짜 추출 ─────────────────────────────────────────────────────────────────
def _extract_period_end(text: str) -> Optional[date]:
    """기준일 (XX년 YY월 ZZ일 현재) 추출 → date 객체."""
    m = _PERIOD_END_KW.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # "as per YYYY-MM-DD" 영문 패턴
    m2 = re.search(r"as per\s+(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text, re.IGNORECASE)
    if m2:
        try:
            return date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            pass
    return None


def _extract_reply_date(text: str, period_end: Optional[date] = None) -> Optional[str]:
    """회신일자 추출 (기준일과 구분).

    전략:
      1. '확인통지' 다음에 오는 날짜 우선
      2. 텍스트 후반부(확인통지 아래) 날짜 탐색
      3. 영문 MM.DD.YYYY 패턴
      4. "YYYY- MM- DD" 띄어쓴 영문 날짜 (발송일)
      5. 기준일 != 후보 날짜면 최후반부 날짜 반환
    """
    # 기준일 문자열 보호
    period_str = None
    if period_end:
        period_str = f"{period_end.year:04d}-{period_end.month:02d}-{period_end.day:02d}"

    # 확인통지 아래 섹션 추출
    notice_idx = text.find("확인통지")
    if notice_idx < 0:
        notice_idx = _find_pattern(text, r"Signature and Company", re.IGNORECASE)
    search_region = text[notice_idx:] if notice_idx >= 0 else text

    candidates: list[tuple[int, str]] = []

    def _add_candidates(src: str, offset: int):
        # 한국어 날짜
        for m in _DATE_KO.finditer(src):
            ds = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            candidates.append((offset + m.start(), ds))
        # ISO / 점 구분
        for m in _DATE_ISO.finditer(src):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                ds = f"{y:04d}-{mo:02d}-{d:02d}"
                candidates.append((offset + m.start(), ds))
        # 영문 MM.DD.YYYY
        for m in _DATE_EN_MDY.finditer(src):
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
                ds = f"{y:04d}-{mo:02d}-{d:02d}"
                candidates.append((offset + m.start(), ds))
        # 영문 2026- 02- 04 패턴
        for m in _DATE_EN_SPACED.finditer(src):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2100:
                ds = f"{y:04d}-{mo:02d}-{d:02d}"
                candidates.append((offset + m.start(), ds))

    _add_candidates(search_region, notice_idx if notice_idx >= 0 else 0)

    # 기준일과 동일한 후보 제거 (발송일 제외)
    filtered = [(pos, ds) for pos, ds in candidates if ds != period_str]
    if filtered:
        # 가장 뒤에 있는 날짜 = 회신일
        filtered.sort(key=lambda x: x[0], reverse=True)
        return filtered[0][1]

    # 전체 텍스트에서도 탐색 (확인통지 없는 경우)
    all_candidates: list[tuple[int, str]] = []
    _add_candidates(text, 0)
    non_period = [(p, d) for p, d in all_candidates if d != period_str]
    if non_period:
        non_period.sort(key=lambda x: x[0], reverse=True)
        return non_period[0][1]

    return None


def _find_pattern(text: str, pattern: str, flags=0) -> int:
    m = re.search(pattern, text, flags)
    return m.start() if m else -1


# ── 감사인명 추출 ─────────────────────────────────────────────────────────────
def _extract_audit_firm(text: str) -> Optional[str]:
    m = _AUDIT_FIRM_KO.search(text)
    if m:
        return m.group(1).strip()
    m = _AUDIT_FIRM_EN.search(text)
    if m:
        return m.group(1).strip()
    return None


# ── 거래처명 추출 ─────────────────────────────────────────────────────────────
def _extract_party_name(text: str) -> Optional[str]:
    """거래처명 추출 (우선순위 순).

    1. "귀사[{이름}]" — 조회서 본문 내 가장 명확한 위치
    2. "{이름} 귀중" — 수신자 표기 (헤더 첫 줄)
    3. "TO : {이름}" — 영문 양식
    """
    # 1. 귀사[...] — 복수 추출 시 첫 번째 (가장 짧은 의미 있는 이름)
    guisa_matches = _PARTY_GUISA.findall(text)
    if guisa_matches:
        # 가장 짧고 의미 있는 이름 선택
        for nm in guisa_matches:
            nm = nm.strip()
            if 2 <= len(nm) <= 80:
                return nm

    # 2. "{이름} 귀중"
    for m in _PARTY_KWITO_KO.finditer(text):
        nm = m.group(1).strip()
        # 불필요한 접두어 제거 ("채권채무조회서" 같은 제목 제외)
        if 2 <= len(nm) <= 80 and "조회서" not in nm and "확인통지" not in nm:
            return nm

    # 3. "TO : {이름}"
    m = _PARTY_TO_EN.search(text)
    if m:
        nm = m.group(1).strip().rstrip(",")
        if 2 <= len(nm) <= 80:
            return nm

    return None


# ── pdfplumber 표 파싱 ────────────────────────────────────────────────────────
def _parse_tables_from_pdfplumber(tables: list[list[list[str | None]]]) -> tuple[
    dict[str, float], dict[str, float],
    Optional[float], Optional[float],
    str
]:
    """pdfplumber extract_tables() 결과에서 채권/채무 계정과목별 잔액 추출.

    반환: (receivable_by_account, payable_by_account,
           recv_total, payb_total, currency)
    """
    recv: dict[str, float] = {}
    payb: dict[str, float] = {}
    recv_total: Optional[float] = None
    payb_total: Optional[float] = None
    currency = "KRW"

    # 표가 순서대로 [채권표, 채무표] 로 오는 경우 (삼덕 한국어 표준)
    # 영문의 경우도 동일하게 Receivables → Payables 순서
    # 헤더 행: ['계정과목', '발송금액', '일치여부', '회신금액', '비고']
    # 또는   : ['Account', 'Our Amount', 'Your Amount', 'Description']

    for table_idx, table in enumerate(tables):
        if not table:
            continue

        # 헤더 확인 — 4컬럼 이상이어야 표
        header = table[0]
        if not header or len(header) < 2:
            continue

        header_joined = " ".join(str(c or "") for c in header).lower()
        is_acct_table = (
            "계정과목" in header_joined or
            "account" in header_joined
        )
        if not is_acct_table:
            continue

        # 컬럼 인덱스 결정
        # 한국어: [계정과목, 발송금액, 일치여부, 회신금액, 비고] → 회신금액=3
        # 영문:   [Account, Our Amount, Your Amount, Description] → Your Amount=2
        acct_col = 0
        amount_col = 3  # 기본: 회신금액 (한국어)
        if "account" in header_joined:
            amount_col = 2  # Your Amount (영문)

        # 어느 섹션인지 판별 (table_idx 기반 + 첫 번째=채권, 두 번째=채무)
        # 단, 모든 행을 파싱해 합계 없으면 채권, 있으면 구분 유지
        target = recv if table_idx == 0 else payb
        total_target_ref = [None]

        for row in table[1:]:
            if not row or len(row) <= amount_col:
                continue
            acct_raw = str(row[acct_col] or "").strip()
            amt_raw = str(row[amount_col] or "").strip()

            if not acct_raw:
                continue

            # 합계 행
            if _TOTAL_ROW.match(acct_raw) or acct_raw.upper() == "TOTAL":
                val, cur = _extract_currency_amount(amt_raw)
                if val is not None:
                    total_target_ref[0] = val
                    if cur != "KRW":
                        currency = cur
                continue

            # 계정과목 행 — (cid:X) 포함된 경우 스킵
            if "(cid:" in acct_raw:
                continue

            val, cur = _extract_currency_amount(amt_raw)
            if val is not None and val != 0:
                target[acct_raw] = val
                if cur != "KRW":
                    currency = cur

        if table_idx == 0:
            recv_total = total_target_ref[0]
        else:
            payb_total = total_target_ref[0]

    return recv, payb, recv_total, payb_total, currency


# ── 텍스트 기반 잔액 추출 (폴백) ──────────────────────────────────────────────
_ACCT_LINE_RE = re.compile(
    r"(외상매출금|받을어음|미수금|선급금|장기대여금|임차보증금|기타채권"
    r"|외상매입금|미지급금|지급어음|선수금|임대보증금|외담대미지급금"
    r"|외상매입금\(관계사\)|외상매입금\(국외\)|미지급금\(국외\)"
    r"|[가-힣]{2,8}(?:채권|어음|지급금|매출금|매입금|수금|급금|보증금|대여금))"
    r"\s+(?:KRW|USD|EUR|JPY|CNY|SGD|AUD|MYR|THB)?\s*([\d,]+(?:\.\d+)?)",
    re.UNICODE,
)
_TOTAL_LINE_RE = re.compile(
    r"^(?:합계|TOTAL)\s+(?:KRW|USD|EUR|JPY|CNY)?\s*([\d,]+(?:\.\d+)?)",
    re.MULTILINE | re.IGNORECASE,
)


_GENERIC_BALANCE_KW_RE = re.compile(
    r"(?:잔액|확인금액|Balance|balance|금액|합계)"
    r"[\s:：]*"
    r"(?:KRW|USD|EUR|JPY|CNY|SGD|AUD|MYR|THB|\$|￥|¥|€)?\s*"
    r"([\(（]?\s*[\d,]+(?:\.\d+)?\s*[\)）]?)",
    re.IGNORECASE,
)


def _parse_balances_from_text(text: str) -> tuple[
    dict[str, float], dict[str, float],
    Optional[float], Optional[float],
    str
]:
    """텍스트 기반 잔액 추출 — 표 파싱 실패 시 폴백.

    단계:
    1. 섹션 분할 (받을금액/지급할금액) 후 계정과목별 추출
    2. 섹션 없으면 키워드(잔액, Balance 등) 인근 숫자 추출 (합성 텍스트 호환)
    3. 키워드도 없으면 큰 숫자(5자리 이상) 폴백
    """
    recv: dict[str, float] = {}
    payb: dict[str, float] = {}
    currency = "KRW"

    # 섹션 분할
    recv_start = _find_pattern(text, r"받을\s*금액|Receivable", re.IGNORECASE)
    payb_start = _find_pattern(text, r"지급할\s*금액|Payable", re.IGNORECASE)
    confirm_start = _find_pattern(text, r"확인통지|Signature and Company", re.IGNORECASE)

    def _parse_section(section_text: str) -> tuple[dict[str, float], Optional[float]]:
        accts: dict[str, float] = {}
        total = None
        for m in _ACCT_LINE_RE.finditer(section_text):
            acct = m.group(1)
            val = _parse_amount(m.group(2))
            if val and val > 0:
                accts[acct] = val
        # 합계 행
        cm = _TOTAL_LINE_RE.search(section_text)
        if cm:
            total = _parse_amount(cm.group(1))
        return accts, total

    recv_total: Optional[float] = None
    payb_total: Optional[float] = None

    if recv_start >= 0:
        end = payb_start if payb_start > recv_start else (confirm_start if confirm_start > recv_start else len(text))
        recv, recv_total = _parse_section(text[recv_start:end])

    if payb_start >= 0:
        end = confirm_start if confirm_start > payb_start else len(text)
        payb, payb_total = _parse_section(text[payb_start:end])

    # 통화 감지
    cur_m = _CURRENCY_AMOUNT_RE.search(text)
    if cur_m:
        currency = _CURRENCY_PREFIXES.get(cur_m.group(1).upper(), "KRW")

    # 섹션도 없고 계정과목도 없으면 키워드 기반 폴백 (합성 텍스트 / 단순 양식 호환)
    if not recv and not payb and recv_total is None and payb_total is None:
        for m in _GENERIC_BALANCE_KW_RE.finditer(text):
            val = _parse_amount(m.group(1))
            if val is not None and abs(val) >= 1:
                recv_total = val
                break

        # 키워드도 없으면 큰 숫자 (5자리 이상) 폴백
        if recv_total is None:
            big_nums = re.findall(r"(?:KRW|USD|EUR|JPY|CNY|\$|￥)?\s*([\d,]{5,}(?:\.\d+)?)", text)
            for raw in big_nums:
                v = _parse_amount(raw)
                if v and abs(v) >= 10000:
                    recv_total = v
                    break

    return recv, payb, recv_total, payb_total, currency


# ── 일치여부 선언 추출 ─────────────────────────────────────────────────────────
def _extract_is_match(text: str) -> Optional[bool]:
    """회신서에 "일치"/"불일치" 선언이 있는지 확인."""
    # 표 내 일치여부 컬럼에서 확인
    if re.search(r"불일치", text):
        return False
    if re.search(r"(?<!\S)일치(?!\S|여부)", text):
        # "일치여부"(헤더) 제외하고 "일치"만 있으면 True
        return True
    # 영문 discrepancy
    if re.search(r"discrepanc", text, re.IGNORECASE):
        return False
    return None


# ── 메인 파싱 함수 ─────────────────────────────────────────────────────────────
def parse_confirmation(
    text: str,
    kind: str = "receivable",
    tables: list | None = None,
) -> ParsedReply:
    """추출된 텍스트 (+ 옵션: pdfplumber tables)에서 회신 핵심 정보를 파싱한다.

    Args:
        text: ExtractResult.full_text
        kind: "receivable" | "payable" — 반환할 주 잔액 결정
        tables: pdfplumber page.extract_tables() 결과 (있으면 우선 사용)
    """
    # 1. 거래처명
    party_name = _extract_party_name(text)

    # 2. 기준일
    period_end = _extract_period_end(text)

    # 3. 회신일자
    reply_date = _extract_reply_date(text, period_end)

    # 4. 감사인명
    audit_firm = _extract_audit_firm(text)

    # 5. 잔액 — 표 우선, 텍스트 폴백
    if tables:
        recv, payb, recv_total, payb_total, currency = _parse_tables_from_pdfplumber(tables)
        # 표 결과가 빈약하면 텍스트 폴백
        if not recv and not payb:
            recv, payb, recv_total, payb_total, currency = _parse_balances_from_text(text)
    else:
        recv, payb, recv_total, payb_total, currency = _parse_balances_from_text(text)

    # 합계 보정 — 합계 행이 없으면 계정과목 합산
    if recv_total is None and recv:
        recv_total = sum(recv.values())
    if payb_total is None and payb:
        payb_total = sum(payb.values())

    # 6. 일치여부
    is_match = _extract_is_match(text)

    # 7. 서명 여부
    has_sig = bool(_SIGNATURE_RE.search(text))

    # 8. 신뢰도
    score = sum([
        party_name is not None,
        period_end is not None,
        reply_date is not None,
        bool(recv) or bool(payb),
        recv_total is not None or payb_total is not None,
        has_sig,
    ])
    confidence = round(score / 6.0, 4)

    result = ParsedReply(
        extracted_party_name=party_name,
        period_end=period_end,
        reply_date=reply_date,
        audit_firm=audit_firm,
        receivable_by_account=recv,
        payable_by_account=payb,
        receivable_total=recv_total,
        payable_total=payb_total,
        is_match_declared=is_match,
        has_signature=has_sig,
        extraction_confidence=confidence,
    )
    object.__setattr__(result, '_currency', currency)
    return result


# ── Parser v2 ─────────────────────────────────────────────────────────────────

def _find_column_index(header: list, keywords: list[str]) -> Optional[int]:
    """헤더 행에서 keywords 중 하나를 포함하는 컬럼 인덱스 반환."""
    for i, cell in enumerate(header):
        cell_str = str(cell or "").strip().lower()
        for kw in keywords:
            if kw.lower() in cell_str:
                return i
    return None


def _parse_declared_match_cell(cell_str: str, positive: list[str], negative: list[str]) -> Optional[bool]:
    """셀 텍스트 → True(일치) / False(불일치) / None(공란).

    주의: negative("불일치")가 positive("일치")를 포함하므로
    negative를 먼저 체크해야 오탐을 방지한다.
    """
    s = cell_str.strip().lower()
    if not s:
        return None
    # negative 우선 (예: "불일치"는 "일치"도 포함하므로 먼저 검사)
    for neg in negative:
        if neg.lower() in s:
            return False
    for pos in positive:
        if pos.lower() in s:
            return True
    return None


def _is_total_row(acct_raw: str) -> bool:
    """합계 행 여부 판별."""
    return bool(re.match(r"^(?:합계|TOTAL|Total)\s*$", acct_raw.strip()))


def _determine_section_from_table_context(
    table_idx: int,
    table_text_above: str,
    recv_kws: list[str],
    payb_kws: list[str],
) -> str:
    """표 위 텍스트 + 표 순번으로 채권/채무 섹션 판별."""
    for kw in recv_kws:
        if re.search(kw, table_text_above, re.IGNORECASE):
            return "receivable"
    for kw in payb_kws:
        if re.search(kw, table_text_above, re.IGNORECASE):
            return "payable"
    # 순서 기반 fallback: 첫 번째 표=채권, 두 번째=채무
    return "receivable" if table_idx == 0 else "payable"


def parse_confirmation_v2(
    text: str,
    tables: Optional[list] = None,
    patterns=None,          # FormPatterns | None
    filename_hint: Optional[str] = None,
) -> ParsedReply:
    """표 헤더 동적 매핑 기반 파싱 v2.

    기존 parse_confirmation()과 동일한 ParsedReply를 반환하되
    per_account_rows, declared_match, original_currency 필드를 추가로 채운다.

    Args:
        text:          ExtractResult.full_text
        tables:        pdfplumber extract_tables() 결과
        patterns:      FormPatterns — 컬럼 키워드 힌트 (None이면 기본값 사용)
        filename_hint: 파일명 (CJK 거래처명 추론 등에 활용)
    """
    # ── 1단계: 기존 parse_confirmation()으로 기반 파싱 ────────────────────
    base = parse_confirmation(text, tables=tables)

    # patterns가 없으면 기본 한국어 패턴 사용
    if patterns is None:
        from .pattern_library import PATTERN_REGISTRY
        patterns = PATTERN_REGISTRY.get("samduk_kr_standard")

    per_account_rows: list[AccountRow] = []
    currency = base._currency

    # ── 2단계: 표 헤더 동적 매핑 ─────────────────────────────────────────
    if tables:
        match_col_kws   = getattr(patterns, "match_column_keywords", ["일치여부"])
        reply_col_kws   = getattr(patterns, "reply_amount_column_keywords", ["회신금액"])
        sent_col_kws    = getattr(patterns, "sent_amount_column_keywords", ["발송금액"])
        recv_section_kws = getattr(patterns, "receivable_section_keywords", [r"받을\s*금액"])
        payb_section_kws = getattr(patterns, "payable_section_keywords", [r"지급할\s*금액"])
        match_pos = getattr(patterns, "match_positive_values", ["일치", "○", "O"])
        match_neg = getattr(patterns, "match_negative_values", ["불일치", "×", "X"])

        # 표 앞 텍스트 위치 추적 (페이지 분할 없이 단순 순서로)
        # 표 i의 "위 텍스트"는 text 전체에서 판단
        for table_idx, table in enumerate(tables):
            if not table or len(table) < 2:
                continue
            header = table[0]
            if not header:
                continue
            header_joined = " ".join(str(c or "") for c in header).lower()

            # 계정과목 표인지 확인
            has_acct = "계정과목" in header_joined or "account" in header_joined
            if not has_acct:
                continue

            # 컬럼 인덱스 동적 결정
            acct_col_idx = _find_column_index(header, ["계정과목", "Account"])
            if acct_col_idx is None:
                acct_col_idx = 0

            match_col_idx  = _find_column_index(header, match_col_kws)
            reply_col_idx  = _find_column_index(header, reply_col_kws)
            sent_col_idx   = _find_column_index(header, sent_col_kws)

            # reply_col이 없으면 column 3 (기존 fallback)
            if reply_col_idx is None:
                if "account" in header_joined and len(header) > 2:
                    reply_col_idx = min(2, len(header) - 1)
                else:
                    reply_col_idx = min(3, len(header) - 1)

            # 섹션 판별: 표 위 텍스트 (전체 텍스트에서 해당 표 index 기준으로)
            section = _determine_section_from_table_context(
                table_idx, text, recv_section_kws, payb_section_kws
            )

            for row in table[1:]:
                if not row:
                    continue
                max_idx = max(
                    acct_col_idx,
                    reply_col_idx if reply_col_idx else 0,
                    match_col_idx if match_col_idx else 0,
                    sent_col_idx if sent_col_idx else 0,
                )
                if len(row) <= max_idx:
                    continue

                acct_raw = str(row[acct_col_idx] or "").strip()
                if not acct_raw or "(cid:" in acct_raw:
                    continue
                if _is_total_row(acct_raw):
                    continue

                # 회신금액
                reply_raw = str(row[reply_col_idx] or "").strip() if reply_col_idx is not None else ""
                reply_val, row_currency = _extract_currency_amount(reply_raw)
                if row_currency != "KRW":
                    currency = row_currency

                # 발송금액
                sent_val = None
                if sent_col_idx is not None and sent_col_idx < len(row):
                    sent_raw = str(row[sent_col_idx] or "").strip()
                    sent_val, _ = _extract_currency_amount(sent_raw)

                # 일치여부
                row_match: Optional[bool] = None
                if match_col_idx is not None and match_col_idx < len(row):
                    match_raw = str(row[match_col_idx] or "").strip()
                    row_match = _parse_declared_match_cell(match_raw, match_pos, match_neg)

                per_account_rows.append(AccountRow(
                    section=section,
                    account_name=acct_raw,
                    sent_amount=sent_val,
                    declared_match=row_match,
                    reply_amount=reply_val,
                    currency=row_currency,
                ))

    # ── 3단계: per_account 종합 declared_match 계산 ───────────────────────
    # 우선순위: 셀 수준 declared_match → 텍스트 키워드(base.is_match_declared)
    declared_overall: Optional[bool] = None

    row_matches = [r.declared_match for r in per_account_rows if r.declared_match is not None]
    if row_matches:
        if all(m is True for m in row_matches):
            declared_overall = True
        elif any(m is False for m in row_matches):
            declared_overall = False
        else:
            declared_overall = None
    else:
        # 셀 수준 정보 없음 → 텍스트 키워드 기반 fallback
        declared_overall = base.is_match_declared

    # ── 4단계: ParsedReply 확장 필드 채우기 ──────────────────────────────
    base.per_account_rows = per_account_rows
    base.declared_match = declared_overall
    base.original_currency = currency
    # _currency 동기화
    object.__setattr__(base, '_currency', currency)

    return base
