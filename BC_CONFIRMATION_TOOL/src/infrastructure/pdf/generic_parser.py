import re
from datetime import date
from decimal import Decimal
from src.domain.ac_models import (
    FinancialAsset,
    SecurityDetail,
)

AMOUNT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*원?")
ACCT_RE = re.compile(r"계좌(?:번호)?\s*([0-9\-]+)")
CCY_RE = re.compile(r"\b(KRW|USD|EUR|JPY|CNY|HKD|GBP|AUD|SGD)\b")
RATE_RE = re.compile(r"([\d.]+)\s*%")
DATE_RE = re.compile(r"(\d{4})[-./]?\s*(\d{1,2})[-./]?\s*(\d{1,2})")

# 회신서 보일러플레이트 — record 만들면 안 되는 안내 문구
_NOISE_PATTERNS = [
    "조회기준일",          # "4. 조회기준일 현재 조회대상회사..."
    "당사의",
    "다음과 같습니다",
    "다음과같음",
    "참고 목적으로",
    "정확성",
    "표시되어",
    "이는 참고",
    "조회대상회사",
    "당 금융회사",
    "당 은행",
    "(주)",                # 보통 헤더 텍스트 "코스맥스비티아이(주)" 등
    "유의사항",
    "면책",
    "기재 사항",
    "기재사항",
    "확인자",              # "확인자 소속 및 성명 : 업무혁신부 강선경" — 종목명·보조필드 오염
    "소속 및 성명",
]
# "해당사항 없음"·"비고" 등은 데이터 행의 제한사항/비고 칸에도 적힌다.
# (예: 대신증권 '101-187649-10 위탁자상품 KRW 0 ... 해당사항 없음')
# 이런 문구는 진짜 데이터(계좌번호/통화+금액)가 없을 때만 noise 로 본다.
# 그렇지 않으면 전액 0 증권계좌가 통째로 누락되어 완전성이 깨진다.
_SOFT_NOISE_PATTERNS = [
    "해당 거래 없음",
    "해당사항 없음",
    "해당사항없음",
    "비고",
]


def _is_noise(line: str) -> bool:
    """회신서 안내·면책·헤더 문구 skip 판정. 짧은 문구·번호로 시작하는 절 제외."""
    s = line.strip()
    if not s or len(s) < 6:
        return True
    if len(s) > 200:    # 너무 긴 줄 — 한 record 아닌 paragraph
        return True
    # 번호 절 ("1.", "1)", "①", "가.", "(1)", "4. 조회기준일") → noise
    if re.match(r"^\s*[\d①②③④⑤⑥⑦⑧⑨⑩가-힣]\s*[.)]\s", s):
        # 단 숫자 다음 금융상품 키워드는 record (e.g. "1. 보통예금")
        pass
    # 보일러플레이트 키워드 포함 → 무조건 noise
    for p in _NOISE_PATTERNS:
        if p in s:
            return True
    # soft noise: 데이터(계좌번호 or 통화+금액)가 없을 때만 noise
    for p in _SOFT_NOISE_PATTERNS:
        if p in s:
            if _has_acct_token(s) or _has_ccy_amount_token(s):
                return False  # 데이터 행 — 살린다
            return True
    return False


def _amount(text: str, anchor: str) -> Decimal | None:
    """Extract amount following anchor keyword."""
    m = re.search(rf"{anchor}\s*[:：]?\s*([\d,]+)", text)
    if not m:
        return None
    return Decimal(m.group(1).replace(",", ""))


def _date(text: str, anchor: str) -> date | None:
    """Extract date following anchor keyword."""
    m = re.search(
        rf"{anchor}\s*[:：]?\s*(\d{{4}}[-./]\d{{1,2}}[-./]\d{{1,2}})", text
    )
    if not m:
        return None
    parts = re.split(r"[-./]", m.group(1))
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


_AC1_KEYWORDS = [
    "보통예금", "정기예금", "당좌예금", "외화예금", "기업자유", "MMDA",
    "MMF", "CMA", "RP", "수익증권", "ETF",
    "주식", "채권", "신탁",
    "퇴직연금", "발행어음", "랩", "위탁자상품", "펀드상품", "종합투자",
    "당좌개설보증금", "보증금",
]
_CCY_SET = {"KRW","USD","EUR","JPY","CNY","HKD","GBP","AUD","SGD","CNH"}
_DATE_8 = re.compile(r"^\d{8}$")
_YYYYMMDD = re.compile(r"^(19|20)\d{6}$")


def _maturity_from_token(t: str) -> date | None:
    """YYYYMMDD 8자리 토큰을 유효한 date 로 파싱(아니면 None).

    채권 상세행 끝의 만기일(예 '20300531')을 평가액으로 오인하지 않도록,
    valuation/amount 후보에서 제외하고 maturity 로 분리하기 위한 판정.
    19/20 세기 + 월(01~12) + 일(01~31) 이 모두 유효해야 날짜로 인정한다.
    """
    if not _YYYYMMDD.match(t):
        return None
    try:
        return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
    except ValueError:
        return None
_RATE_PATTERN = re.compile(r"^\d+\.\d{2,5}$")
_NUM_TOKEN = re.compile(r"^[\d,]+(?:\.\d+)?$")
_ACCT_TOKEN = re.compile(r"^[0-9\-]{8,22}$")
_PAREN = re.compile(r"^\([\d,.\-]+\)$")
# (KRW)32,023,447,835 / (USD)1,138,268.99 처럼 통화가 괄호로 금액 앞에 붙은 토큰.
# KEB하나 등 회신서가 통화 접두를 금액에 글루(glue)하면 기존 숫자 정규식이
# 못 잡아 balance 0 으로 떨어진다. 통화를 분리·기록하고 잔여를 숫자로 재해석.
_CCY_PREFIX = re.compile(
    r"^\((KRW|USD|EUR|JPY|CNY|CNH|HKD|GBP|AUD|SGD)\)(.*)$"
)


def _strip_ccy_prefix(tok: str) -> tuple[str | None, str]:
    """토큰 앞 (KRW)/(USD)/… 접두를 떼고 (통화, 잔여토큰) 반환.

    접두가 없으면 (None, tok). 잔여가 비면(통화만 단독 괄호) ('CCY', '').
    """
    m = _CCY_PREFIX.match(tok)
    if not m:
        return None, tok
    return m.group(1), m.group(2)


def _classify(s: str) -> tuple[str, str]:
    """(asset_type, category)."""
    if any(k in s for k in ["주식", "보통주", "우선주", "ETF"]):
        return "stock", "securities"
    if "채권" in s:
        return "bond", "securities"
    if any(k in s for k in ["수익증권", "신탁", "랩", "펀드", "위탁자상품", "종합투자", "발행어음", "MMF", "RP"]):
        return "fund", "securities"
    if any(k in s for k in ["예금", "CMA", "MMDA", "기업자유", "퇴직연금"]):
        return "deposit", "bank"
    return "other", "bank"


def _to_dec(v: str | None) -> Decimal | None:
    if v is None or v in {"-", "", "0"}:
        return Decimal("0") if v == "0" else None
    try:
        return Decimal(v.replace(",", ""))
    except Exception:
        return None


# 평가액으로 인정하는 최소 원화 금액. 기준가(단가, 예 163,000.00)·담보수량은
# 이보다 훨씬 작거나, 평가액(수십억~수천억)과 한 자릿수 이상 규모 차이가 난다.
_VALUATION_MIN = Decimal("1000000")
# 진짜 처분제한/담보 어휘만 collateral_type 으로 보존. 'KRW KRW'·계좌조각 등은 버린다.
_COLLATERAL_WORDS = ["질권설정", "담보제공", "처분제한"]
_HANGUL_RUN = re.compile(r"[가-힣]{2,}")


def _is_detail_header(s: str) -> bool:
    return "종목명" in s or ("수량" in s and "액면" in s)


def _detail_acct(tokens: list[str]) -> str | None:
    """첫 token 이 유가증권 상세 계좌번호면 반환. 아니면 None.

    계좌는 숫자/대시로만 이뤄진 8~18자 토큰(숫자 8자리 이상). 금액/한글 wrap 줄과
    구별하기 위해 콤마가 없어야 한다.
    """
    if not tokens:
        return None
    t = tokens[0]
    if "," in t:
        return None
    if not re.fullmatch(r"[0-9\-]{8,18}", t):
        return None
    if len(re.sub(r"[^0-9]", "", t)) < 8:
        return None
    return t


def _pick_ticker(tokens: list[str]) -> str | None:
    """토큰열에서 한글 종목명(2자 이상 연속 한글 포함) 후보를 고른다.

    계좌조각·참조번호(101-314-2362249 외)·통화(KRW)는 종목명이 아니다.
    '1건' '외' 같은 참조 관용어는 제외하고, 코스맥스/코스맥스보통주 같은 실제
    종목명을 우선한다.
    """
    best = None
    for t in tokens:
        if not _HANGUL_RUN.search(t):
            continue
        if t in {"주", "외", "본인", "건"}:
            continue
        # 참조 관용어(외/건/상세/명세/참조)만으로 된 토큰 제외
        core = t
        for w in ["외", "건", "상세", "명세", "참조", "주"]:
            core = core.replace(w, "")
        if not _HANGUL_RUN.search(core):
            continue
        # 더 긴(=더 구체적인) 종목명을 우선
        if best is None or len(core) > len(best):
            best = core
    return best


def parse_ac1_security_details(text: str, bc_no: str, bank: str) -> list[SecurityDetail]:
    """유가증권 상세명세 추출. PDF의 '상세명세' 헤더 다음 lines 파싱.

    표준 패턴: '계좌(11~16) 종목명(한글) 수량 액면 [기준가] 평가액 [만기] [담보수량 담보종류]'
    예: '25628241101 코스맥스 190,000 163,000.00 30,970,000,000 0'
        '25628241101 코스맥스엔비티 2,500,000 3,500.00 8,750,000,000 0 2,500,000 질권설정'

    줄바꿈(wrap) 처리: 일부 증권사 회신서는 한 종목의 종목명·평가액을 다음
    물리적 line 으로 흘린다. 예)
      한국증권금융 §2:
        '101--31-4-23622 101-314-2362249 외 1,262,000 주 KRW 631,000,000 ...'
        '1건 코스맥스보통주 205,706,000,000'   ← 진짜 종목명·평가액
      신한투자 §2:
        '08312631129 코스맥스 150,000 KRW - 163,000.00 KRW 0 75,000'
        '24,450,000,000'                        ← 진짜 평가액
    따라서 계좌번호로 시작하는 데이터 행 + 그 아래 연속(continuation) line 들을
    한 종목으로 묶어, 평가액 = 1,000,000 이상 원화 금액 중 최댓값으로 본다.
    (기준가 163,000.00·담보수량은 평가액보다 훨씬 작아 자연히 탈락)
    """
    out: list[SecurityDetail] = []

    # 1) 데이터 행(계좌번호 시작)과 그에 딸린 continuation line 들을 묶는다.
    rows: list[list[str]] = []          # 각 row = [main_line, cont1, cont2, ...]
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _is_detail_header(s):
            continue
        if _is_noise(s):
            continue
        tokens = s.split()
        acct = _detail_acct(tokens)
        if acct is not None:
            rows.append([s])
            continue
        # 계좌번호가 없는 line: 진행 중인 row 의 continuation 후보.
        # (은행명·페이지번호·확인자 등은 _is_noise 또는 아래 필터로 제외)
        if not rows:
            continue
        # 은행명 단독 줄(예: '한국증권금융')·페이지('1/5')는 continuation 아님
        if s == bank or re.fullmatch(r"\d+/\d+", s):
            continue
        # continuation 으로 인정: 한글 종목명이 있거나 금액 토큰이 있을 때만
        has_amt = any(_NUM_TOKEN.match(t) for t in tokens)
        has_hangul = bool(_HANGUL_RUN.search(s))
        if has_amt or has_hangul:
            rows[-1].append(s)

    # 2) 각 row(메인 + continuation)를 한 종목으로 파싱
    for parts in rows:
        main_tokens = parts[0].split()
        acct = main_tokens[0]
        all_tokens: list[str] = []
        for p in parts:
            all_tokens.extend(p.split())

        # 숫자 토큰 수집 (계좌번호 토큰은 제외).
        # 채권 상세행 끝의 만기일(YYYYMMDD, 예 '20300531')은 정수 원화로 보면
        # 진짜 평가액(예 5,245,805)보다 커서 max() 가 날짜를 평가액으로 오인한다.
        # → 유효 YYYYMMDD 토큰은 maturity 로 분리하고 금액 후보에서 제외한다.
        # 채권 표 컬럼순: '… 기준가 평가액 만기일' 이라 평가액은 만기일 토큰
        # '바로 앞'의 정수 원화이다(액면·수량은 평가액보다 클 수 있어 max() 부적합).
        nums: list[Decimal] = []                       # 금액 후보 (날짜 제외)
        is_decimal: list[bool] = []                    # nums[i] 가 소수(기준가/단가)인가
        maturity: date | None = None
        val_before_date: Decimal | None = None         # 만기일 직전 정수 원화
        prev_amt: Decimal | None = None                # 직전 금액 토큰 값
        for t in all_tokens[1:]:        # skip 계좌번호
            mat = _maturity_from_token(t)
            if mat is not None:         # 만기일 — 금액 후보에서 제외
                maturity = mat
                # 만기일 바로 앞의 금액(정수 원화)을 평가액 후보로 기억
                if val_before_date is None and prev_amt is not None:
                    val_before_date = prev_amt
                prev_amt = None
                continue
            if "," in t or _NUM_TOKEN.match(t):
                d = _to_dec(t)
                if d is not None:
                    nums.append(d)
                    # 소수점(.dd) 포함 토큰 = 기준가/단가(예 9,947.19·163,000.00).
                    is_decimal.append("." in t)
                    prev_amt = d
                    continue
            prev_amt = None
        # 평가액(valuation) 결정.
        #  ① 만기일 직전 정수 원화가 있으면(일부 채권 표) 그것을 우선.
        #  ② 채권은 수량(첫 큰 정수)이 평가액보다 클 수 있다(기준가 ~9,9xx/10,000
        #     이면 평가액 < 수량). 컬럼순 '수량 액면 기준가(소수) 평가액'에서
        #     평가액은 소수 기준가 '바로 뒤'의 정수 원화다. 큰 금액이 ≥2개이고
        #     소수 기준가 뒤에 큰 금액이 있으면 → 그것을 평가액으로(수량 오인 방지).
        #     예) 미래에셋: 수량 10,650,000 · 기준가 9,947.19 · 평가액 10,593,757
        #         → max()는 수량을 고르므로 부적합. 기준가 뒤 금액 채택.
        #  ③ 그 외(주식 등)는 1,000,000 이상 원화 중 최댓값(기존 동작·KB 회귀 방지).
        #     예) KB증권 코스맥스: 수량 190,000 · 기준가 163,000.00 ·
        #         평가액 30,970,000,000 → 기준가 뒤 금액 = 최댓값이라 동일 결과.
        big = [n for n in nums if n >= _VALUATION_MIN]
        # 소수 기준가 '바로 뒤'에 오는 큰(≥VALUATION_MIN) 정수 원화 후보.
        after_base: Decimal | None = None
        for i in range(1, len(nums)):
            if is_decimal[i - 1] and not is_decimal[i] and nums[i] >= _VALUATION_MIN:
                after_base = nums[i]
                break
        if val_before_date is not None and val_before_date >= _VALUATION_MIN:
            val = val_before_date
        elif after_base is not None and len(big) >= 2:
            val = after_base
        else:
            val = max(big) if big else (max([n for n in nums if n > 0], default=None))
        # 수량 = 평가액·기준가가 아닌 첫 큰 정수 후보 (참고용)
        qty = nums[0] if nums else None
        # 기준가(단가): 소수 토큰 우선, 없으면 100 ~ 10,000,000 정수 중 평가액 아닌 값.
        dec_prices = [n for n, dec in zip(nums, is_decimal) if dec]
        if dec_prices:
            base = dec_prices[0]
        else:
            unit_prices = [n for n in nums if n and 100 <= n <= 10_000_000 and n != val]
            base = unit_prices[0] if unit_prices else None

        # 종목명: 메인+continuation 전 토큰에서 한글 종목명 후보
        ticker = _pick_ticker(all_tokens) or "?"

        # collateral_type: 진짜 처분제한/담보 어휘만 (KRW·계좌조각 garbage 제외)
        coll_words = [w for w in _COLLATERAL_WORDS if w in " ".join(all_tokens)]
        coll_type = coll_words[0] if coll_words else None
        coll_qty = None

        out.append(SecurityDetail(
            bc_no=bc_no, bank=bank,
            account_no=acct, ticker_name=ticker,
            quantity=qty, face_value=None,
            base_price=base, valuation=val, maturity=maturity,
            collateral_qty=coll_qty, collateral_type=coll_type,
        ))
    return out


def parse_ac1_deposit(text: str, bc_no: str, bank: str) -> list[FinancialAsset]:
    """AC1 token-based parser. 은행 예금 + 증권사 자산 모두 처리.

    Strategy:
      1. tokenize by whitespace
      2. acct: 10~18 digit (no comma)
      3. ccy: KRW/USD/...
      4. dates: 8-digit at end (last 1~2)
      5. rate: 0.NNNN
      6. balance: largest numeric token (with comma)
      7. parens: 누적이자 etc — skip
      8. rest = product
    """
    out: list[FinancialAsset] = []
    for line in text.splitlines():
        s = line.strip()
        # 줄바꿈된 종목명 끌어올리기: 직전 증권행의 product 가 참조번호류뿐이고
        # 이 줄이 한글 전용 짧은 종목명이면 직전 행에 붙이고 재분류한다.
        if (
            out
            and _is_wrapped_ticker(s)
            and out[-1].category in ("securities", "bank")
            and _product_is_reference_only(out[-1].product)
            and out[-1].balance > 0
        ):
            _attach_ticker(out[-1], s)
            continue
        if _is_noise(s):
            continue
        # 예금 행 판정: 상품명 키워드가 매칭되거나(빠른 경로), 키워드가
        # 줄바꿈으로 쪼개져(ONE KB ...-보통 / 예금) 못 잡힌 경우에도
        # '계좌번호 토큰(10~18자리 무콤마)'이 있으면 진짜 데이터 행으로 본다.
        # 헤더("금융상품의 종류 ...")·footer·괄호 누적이자 줄은 계좌번호가
        # 없어 자연히 제외된다(당좌개설보증금·ONE KB 행 복구).
        # 헤더 line ("금융상품의 종류 계좌번호 금액 ...") 명시 차단:
        # 통화/금액 토큰이 없고 헤더 단어만 있는 줄.
        if ("계좌번호" in s and "금액" in s) and not _has_ccy_amount_token(s):
            continue
        # 데이터 행 판정: (a) 키워드, (b) 계좌번호 토큰, 또는
        # (c) 통화(KRW/USD/…)+금액 토큰이 함께 있으면 진짜 데이터 행으로 본다.
        # (c)는 계좌번호 없는 당좌개설보증금 행도 살린다.
        if not (
            any(kw in s for kw in _AC1_KEYWORDS)
            or _has_acct_token(s)
            or _has_ccy_amount_token(s)
        ):
            continue
        rec = _parse_line(s, bc_no, bank)
        if rec:
            out.append(rec)
    return out


def _has_acct_token(s: str) -> bool:
    """줄에 계좌번호 형태 토큰이 있는지.

    콤마 없는 10~18자리 숫자, 또는 대시 포함 증권 계좌번호
    (예: '101-187649-10', '423-104775-AA', '150-225094385').
    """
    for t in s.split():
        if "," in t:
            continue
        if re.fullmatch(r"\d{10,18}", t):
            return True
        # 대시 포함 계좌(증권사): 숫자 그룹이 대시로 연결, 숫자만 8자리+
        if "-" in t and re.fullmatch(r"[0-9A-Z\-]{8,22}", t):
            digits = re.sub(r"[^0-9]", "", t)
            if len(digits) >= 8:
                return True
    return False


def _has_ccy_amount_token(s: str) -> bool:
    """줄에 통화 토큰(KRW/USD/…)과 금액 토큰(>0 가능한 숫자)이 함께 있는지.

    계좌번호도 키워드도 없는 데이터 행(예: '당좌개설보증금 KRW 3000000.00')을
    살리기 위한 판정. 통화는 단독 토큰(KRW) 또는 금액에 글루된 접두
    ((KRW)32,023,447,835) 모두 인정. 헤더·footer는 통화+금액 조합이 없다.
    """
    tokens = s.split()
    has_ccy = False
    has_amt = False
    for t in tokens:
        ccy, rest = _strip_ccy_prefix(t)
        if ccy:                       # (KRW)123 형태
            has_ccy = True
            if rest and (_NUM_TOKEN.match(rest) or _PAREN.match(rest)):
                has_amt = True
            continue
        if t in _CCY_SET:
            has_ccy = True
            continue
        if _DATE_8.match(t):
            continue
        if _NUM_TOKEN.match(t) or _PAREN.match(t):
            has_amt = True
    return has_ccy and has_amt


# 한글 종목명(보통주/우선주 등)만 단독으로 다음 줄에 줄바꿈된 wrapped line 판정용.
# 증권사 회신서가 종목명을 데이터 행 아래 줄로 흘리는 경우(좌표 재구성),
# 데이터 행의 상품칸엔 참조번호(101-314-2362249 외 1건)만 남고 진짜 종목명은
# 다음 줄("코스맥스보통주")에 떨어진다. 이 줄을 직전 행의 product 로 끌어올린다.
_HANGUL_ONLY = re.compile(r"^[가-힣()·\s]+$")


def _is_wrapped_ticker(s: str) -> bool:
    """다음 줄로 흘러내린 종목명(한글 전용·짧은 줄)인지.

    숫자·계좌번호·통화·금액 토큰이 전혀 없고, 한글(괄호 포함)만으로 구성된
    짧은 줄(2~20자)이며 AC1 상품 키워드(예금/발행어음 등)를 포함하지 않을 때만
    종목명 wrap 으로 본다. (그 자체가 독립 데이터 행이거나 안내문이면 제외)
    """
    t = s.strip()
    if not (2 <= len(t) <= 20):
        return False
    if not _HANGUL_ONLY.match(t):
        return False
    if any(ch.isdigit() for ch in t):
        return False
    # 독립 상품 행 키워드(예금/발행어음/수익증권 등)면 wrap 아님 — 자기 행으로 파싱
    if any(kw in t for kw in _AC1_KEYWORDS):
        return False
    # 안내·면책 등은 _is_noise 가 이미 걸렀지만 한 번 더 방어
    if _is_noise(t):
        return False
    return True


def _product_is_reference_only(product: str) -> bool:
    """product 가 참조번호/계좌번호류로만 구성돼 진짜 종목명이 없는지.

    한글 2자 이상이 들어 있으면(예: '주식', '코스맥스') 이미 종목명이 있다고 본다.
    숫자·대시·'외 N건'·'상세명세참조' 같은 참조 텍스트만 있으면 True.
    """
    if not product:
        return True
    hangul = re.findall(r"[가-힣]", product)
    # '외', '건', '상세', '명세', '참조' 등 참조 관용어를 뺀 한글 글자 수
    ref_words = ["외", "건", "상세", "명세", "참조", "담보", "제공", "처분", "제한"]
    core = product
    for w in ref_words:
        core = core.replace(w, "")
    core_hangul = re.findall(r"[가-힣]", core)
    return len(core_hangul) < 2


def _attach_ticker(rec: FinancialAsset, ticker: str) -> None:
    """직전 증권행에 wrapped 종목명을 product 로 끌어올리고 재분류."""
    ticker = ticker.strip()
    # 기존 참조번호는 종목명 뒤에 보존(감사 추적용)하되 종목명을 앞세운다.
    old = rec.product or ""
    if old and old not in ticker:
        rec.product = (ticker + " " + old).strip()[:60]
    else:
        rec.product = ticker[:60]
    atype, cat = _classify(rec.product)
    rec.asset_type = atype
    rec.category = cat


def _parse_line(s: str, bc_no: str, bank: str) -> FinancialAsset | None:
    raw_tokens = s.split()
    if len(raw_tokens) < 2:
        return None
    # (KRW)금액 / (USD)금액 글루 접두 분리: 통화는 별도 토큰으로, 잔여는 숫자로.
    # 통화가 줄 전체에서 처음 등장하면 기록(prefix_ccy)해 ccy fallback 보강.
    prefix_ccy = None
    tokens: list[str] = []
    for t in raw_tokens:
        ccy, rest = _strip_ccy_prefix(t)
        if ccy:
            if prefix_ccy is None:
                prefix_ccy = ccy
            tokens.append(ccy)        # 통화 토큰으로 환원
            if rest:                  # 금액 잔여 (e.g. '32,023,447,835')
                tokens.append(rest)
        else:
            tokens.append(t)
    if len(tokens) < 2:
        return None
    atype, cat = _classify(s)

    # extract dates from right (up to 2 trailing 8-digit numbers)
    dates: list[date | None] = []
    while tokens and _DATE_8.match(tokens[-1]):
        dates.insert(0, _parse_yyyymmdd(tokens.pop()))
        if len(dates) >= 2:
            break
    maturity = dates[-1] if len(dates) >= 1 else None
    last_interest = dates[-2] if len(dates) >= 2 else None
    if len(dates) == 1:
        last_interest, maturity = dates[0], None

    # extract rate — 단, 값이 작아야 진짜 이자율(<100). 무콤마 금액
    # (503905003.00)도 `\d+\.\d{2,5}` 패턴에 걸리므로, 100 이상이면
    # 금액으로 보고 rate로 pop하지 않는다 (balance 0 오인 방지).
    rate = None
    if tokens and _RATE_PATTERN.match(tokens[-1]):
        cand = Decimal(tokens[-1])
        if cand < 100:
            rate = cand
            tokens.pop()

    # remove "()" or "(0.00)" interest token
    while tokens and (_PAREN.match(tokens[-1]) or tokens[-1] in {"()","(0.00)"}):
        tokens.pop()

    # extract ccy + numeric tokens from remaining
    ccy = None
    numeric_tokens = []
    other_tokens = []
    acct = None
    for t in tokens:
        if t in _CCY_SET:
            ccy = t
        elif _ACCT_TOKEN.match(t) and "," not in t and acct is None:
            acct = t
        elif _NUM_TOKEN.match(t) or t == "-":
            numeric_tokens.append(t)
        else:
            other_tokens.append(t)

    if not ccy:
        ccy = prefix_ccy or ("USD" if "외화" in s else "KRW")

    # balance: largest numeric (assume the first non-zero, or just first)
    balance = Decimal("0")
    deposit_money = margin = receivable = None
    if cat == "bank":
        if numeric_tokens:
            balance = _to_dec(numeric_tokens[0]) or Decimal("0")
    else:
        # securities: balance, deposit, margin, receivable (in order)
        nums = [_to_dec(t) for t in numeric_tokens]
        if len(nums) >= 1: balance = nums[0] or Decimal("0")
        if len(nums) >= 2: deposit_money = nums[1]
        if len(nums) >= 3: margin = nums[2]
        if len(nums) >= 4: receivable = nums[3]

    # 제한사항 토큰("담보제공·처분제한 / 상세명세참조 / 해당사항없음")은
    # category 와 무관하게 분리한다. 담보로 묶인 예금(bank)도 감사자가
    # 처분제한을 봐야 하고, product(종목명/상품명)도 깨끗해진다.
    restriction_tokens = [t for t in other_tokens if any(k in t for k in ["담보","처분","상세","명세","해당"])]
    product_tokens = [t for t in other_tokens if t not in restriction_tokens]
    product = " ".join(product_tokens).strip()[:60] or " ".join(other_tokens).strip()[:60] or s.split()[0][:60]
    restriction = " ".join(restriction_tokens)[:40] if restriction_tokens else None

    return FinancialAsset(
        bc_no=bc_no, bank=bank, asset_type=atype, category=cat,
        product=product, account_no=acct, currency=ccy,
        balance=balance, interest_rate=rate,
        last_interest_date=last_interest, maturity=maturity,
        deposit_money=deposit_money, margin_deposit=margin, receivable=receivable,
        collateral_restriction=restriction,
    )


def _parse_yyyymmdd(s: str) -> date | None:
    """8자리 YYYYMMDD → date. 00000000 또는 invalid → None."""
    if not s or s == "00000000" or len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, IndexError):
        return None
