"""DART 재무 전계정 추출 → FinancialYear 5개년.

fnlttSinglAcntAll.json은 row마다 account_id·sj_div(BS/IS/CIS/CF)·thstrm_amount(당기)
·frmtrm_amount(전기)를 준다. 표준 IFRS account_id로 FinancialYear 필드를 채운다
(계정명 변형에 강건). 한 사업연도 호출이 당기·전기 2개년 → end·end-2·end-4 3건으로
5~6개년을 합친다.

커버리지:
  - 상장사·사업보고서 제출 비상장 : 구조화 API (CFS 우선, 없으면 OFS)
  - 순수 외감 비상장(감사보고서만)   : 구조화 API status≠000 → 감사보고서 원문 파싱 fallback
    (표 인식 기반이라 BS/CF 계정 인식 품질 변동 — 조용히 0 채우지 않고 결측은 None 유지)
"""
from __future__ import annotations
import logging
import re

from risk.domain.financial import FinancialYear

log = logging.getLogger("risk.dart.extractor")

# FinancialYear 필드 → account_id 후보(우선순위). 회사별 태그 변형에 강건.
# 같은 필드에 여러 id가 잡히면 앞선(낮은 rank) id가 이김 — 라이브 검증서 변형 보강.
_FIELD_IDS = {
    "revenue": ["ifrs-full_Revenue"],
    "cogs": ["ifrs-full_CostOfSales"],
    "operating_income": ["dart_OperatingIncomeLoss",
                         "ifrs-full_ProfitLossFromOperatingActivities"],
    "net_income": ["ifrs-full_ProfitLoss"],
    "pretax_income": ["ifrs-full_ProfitLossBeforeTax"],
    "tax_expense": ["ifrs-full_IncomeTaxExpenseContinuingOperations",
                    "ifrs-full_IncomeTaxExpenseBenefit"],
    "finance_costs": ["ifrs-full_FinanceCosts"],
    "operating_cf": ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
    "total_assets": ["ifrs-full_Assets"],
    "current_assets": ["ifrs-full_CurrentAssets"],
    "total_liabilities": ["ifrs-full_Liabilities"],
    "current_liabilities": ["ifrs-full_CurrentLiabilities"],
    # 연결: ifrs-full_Equity(지배+비지배 총자본) 우선, 없으면 지배지분
    "total_equity": ["ifrs-full_Equity",
                     "ifrs-full_EquityAttributableToOwnersOfParent"],
    # 매출채권: 회사별로 CurrentTradeReceivables(삼성 등) 또는 TradeAndOther… 사용
    "trade_receivables": ["ifrs-full_CurrentTradeReceivables",
                          "ifrs-full_TradeAndOtherCurrentReceivables",
                          "dart_ShortTermTradeReceivable"],
    "inventory": ["ifrs-full_Inventories"],
    # 매입채무: 삼성 등은 …PayablesToTradeSuppliers, 두산 등은 dart_ShortTermTradePayables(복수)
    "trade_payables": ["ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers",
                       "ifrs-full_TradeAndOtherCurrentPayables",
                       "dart_ShortTermTradePayables",
                       "dart_ShortTermTradePayable",
                       "dart_TradePayable"],
}

# account_id → (field, rank). rank 작을수록 우선.
_ACCOUNT_MAP: dict[str, tuple[str, int]] = {
    aid: (field, rank)
    for field, ids in _FIELD_IDS.items()
    for rank, aid in enumerate(ids)
}


def _num(s):
    """'1,234' · '-' · '' → float|None. comma/공백 제거, 비숫자 None."""
    t = re.sub(r"[,\s]", "", str(s or ""))
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def rows_to_years(rows: list[dict]) -> list[FinancialYear]:
    """fnlttSinglAcntAll rows → FinancialYear 리스트(당기·전기). bsns_year 기준 오름차순.

    한 필드에 여러 account_id 후보가 잡히면 rank 낮은(우선) id가 이긴다.
    """
    acc: dict[int, dict] = {}
    ranks: dict[tuple[int, str], int] = {}  # (year, field) → 채택된 id의 rank

    def _set(year, field, val, rank):
        if val is None:
            return
        key = (year, field)
        if key in ranks and ranks[key] <= rank:
            return  # 이미 더 우선한 id로 채워짐
        acc.setdefault(year, {})[field] = val
        ranks[key] = rank

    for r in rows:
        hit = _ACCOUNT_MAP.get((r.get("account_id") or "").strip())
        if not hit:
            continue
        field, rank = hit
        by = int(re.sub(r"\D", "", str(r.get("bsns_year") or "0")) or 0)
        if not by:
            continue
        _set(by, field, _num(r.get("thstrm_amount")), rank)
        _set(by - 1, field, _num(r.get("frmtrm_amount")), rank)
    return [FinancialYear(year=y, **fields) for y, fields in sorted(acc.items())]


# ---------- 감사보고서 원문 파싱 (외감 비상장 fallback) ----------

def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").replace("&cr;", "").strip()


def _cell_num(c: str):
    """표 셀 → float. 괄호=음수, 콤마 제거, 비숫자=None."""
    c = (c or "").strip()
    neg = c.startswith("(") and c.endswith(")")
    d = re.sub(r"[^0-9]", "", c)
    if not d:
        return None
    v = float(d)
    return -v if neg else v


def _doc_unit_scale(text: str) -> float:
    """재무제표 표기 단위 → 원 환산 배수. '천원'→1000, '백만원'→1e6, 기본 원=1.

    단위 선언은 각 재무제표 표 머리에 '(단위: 원/천원/백만원)'으로 붙는다. 약식·적자
    라벨(매출/영업손실)도 앵커로 잡아 실제 FS 영역의 단위를 읽는다(문서 앞 요약표의
    엉뚱한 단위 오검출 방지).
    """
    m = re.search(r"재무상태표|자산\s*총계|매출\s*원가|영업\s*손실|영업\s*이익|"
                  r"매출\s*액|영업\s*수익", text)
    pos = m.start() if m else 0
    region = text[max(0, pos - 4000): pos + 400]
    units = re.findall(r"단위\s*[:：]?\s*(백만원|천원|원)", region)
    if units:
        return {"백만원": 1e6, "천원": 1e3, "원": 1.0}[units[-1]]
    return 1.0


def _parse_table_rows(tbl: str):
    """<TABLE> 내부 → [(라벨(공백제거), [숫자셀...])]."""
    rows = []
    for tr in re.findall(r"<TR[^>]*>(.*?)</TR>", tbl, re.S | re.I):
        tds = [_strip_tags(td) for td in re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.S | re.I)]
        if not tds:
            continue
        nums = [n for n in (_cell_num(c) for c in tds[1:]) if n is not None]
        rows.append((tds[0].replace(" ", ""), nums))
    return rows


def _classify_statement(rows):
    """행 시그니처로 재무제표 종류 판정. BS/IS/CF/None.

    적자기업·약식라벨 대응: '매출액'뿐 아니라 '매출'(매출원가가 있으면 IS), 영업'이익'뿐
    아니라 영업'손실'도 인식.
    """
    labs = " ".join(l for l, _ in rows)
    if "자산총계" in labs and "부채총계" in labs:
        return "BS"
    has_sales = "매출액" in labs or "영업수익" in labs or "매출원가" in labs
    has_op = "영업이익" in labs or "영업손실" in labs
    if has_sales and has_op:
        return "IS"
    if "영업활동" in labs and ("현금흐름" in labs or "영업활동으로" in labs):
        return "CF"
    return None


def _parse_fs_document(text: str, base_year: int) -> dict:
    """감사보고서 원문(HTML 표) → {연도: {FinancialYear 필드}}.

    <TABLE> 단위로 쪼개 계정 시그니처로 BS/IS/CF 분류(주석 유사표 배제).
    각 행 마지막 2개 숫자셀 = (당기=base_year, 전기=base_year-1).
    rcps 버전이 IS/CF 일부만 뽑던 것을 BS·CF 잔액계정까지 _ACCOUNT_MAP 전 범위로 확장.
    표 파싱이라 계정 인식 품질 변동 — 미발견 필드는 None 유지.
    """
    scale = _doc_unit_scale(text)
    found = {}  # 'BS'|'IS'|'CF' -> rows (각 종류 첫 표 = 1차 재무제표)
    for tbl in re.findall(r"<TABLE[^>]*>(.*?)</TABLE>", text, re.S | re.I):
        rows = _parse_table_rows(tbl)
        if not rows:
            continue
        if not re.search(r"당\)?\s*기|\(당\)|전\)?\s*기|\(전\)", tbl):
            continue
        kind = _classify_statement(rows)
        if kind and kind not in found:
            found[kind] = rows

    def pick(rows, *keys, exclude=()):
        for lab, nums in rows or []:
            if any(k in lab for k in keys) and not any(e in lab for e in exclude) \
                    and len(nums) >= 2:
                return nums[-2], nums[-1]
        return None

    cur, prev = {}, {}

    def put(field, got, absval=False):
        if not got:
            return
        c, p = got
        cur[field] = (abs(c) if absval else c) * scale
        prev[field] = (abs(p) if absval else p) * scale

    is_rows = found.get("IS")
    bs_rows = found.get("BS")
    cf_rows = found.get("CF")

    # 손익계산서 (적자기업: 영업손실·당기순손실, 약식라벨: 바로 '매출')
    put("revenue", pick(is_rows, "매출액", "영업수익", "수익(매출액)", "매출",
                        exclude=("원가", "총이익", "총손실", "채권", "구성", "증가", "할인")))
    put("cogs", pick(is_rows, "매출원가"))
    put("operating_income", pick(is_rows, "영업이익", "영업손실", exclude=("률", "이익률")))
    put("pretax_income", pick(is_rows, "법인세비용차감전", "법인세차감전순"))
    put("tax_expense", pick(is_rows, "법인세비용", exclude=("차감전",)))
    put("net_income", pick(is_rows, "당기순이익", "당기순손실", "당기순손익",
                           exclude=("률", "주당")))
    put("finance_costs", pick(is_rows, "금융원가", "금융비용", exclude=("순",)))

    # 재무상태표
    put("total_assets", pick(bs_rows, "자산총계"))
    put("current_assets", pick(bs_rows, "유동자산", exclude=("비유동",)))
    put("total_liabilities", pick(bs_rows, "부채총계"))
    put("current_liabilities", pick(bs_rows, "유동부채", exclude=("비유동",)))
    put("total_equity", pick(bs_rows, "자본총계"))
    put("trade_receivables", pick(bs_rows, "매출채권"))
    put("inventory", pick(bs_rows, "재고자산"))

    # 현금흐름표
    put("operating_cf", pick(cf_rows, "영업활동현금흐름", "영업활동으로인한현금흐름",
                             "영업활동순현금흐름"))

    out = {}
    if cur:
        out[base_year] = cur
    if prev:
        out[base_year - 1] = prev
    return out


class RiskExtractor:
    def __init__(self, client):  # client: DartClient
        self.client = client

    def fetch(self, corp_code: str, end_year: int,
              max_years: int = 5) -> list[FinancialYear]:
        """end_year·end_year-2·end_year-4 호출 → 당기·전기 병합 → 최근 max_years.

        CFS(연결) 우선, 없으면 OFS(별도) — 연결 위험 신호 보수적.
        구조화 API가 전무하면 감사보고서 원문 파싱 fallback.
        둘 다 비면 [] (호출측 수기입력 — 조용히 0 금지).
        """
        merged: dict[int, FinancialYear] = {}
        for yr in (end_year, end_year - 2, end_year - 4):
            rows = self._fetch_all(corp_code, yr)
            for fy in rows_to_years(rows):
                merged.setdefault(fy.year, fy)  # 앞선(최신·CFS) 호출 우선
        if not merged:
            audit = self._fetch_from_audit_reports(corp_code, end_year, max_years)
            for fy in audit:
                merged.setdefault(fy.year, fy)
        years = [merged[y] for y in sorted(merged)][-max_years:]
        return years

    def _fetch_all(self, corp_code, bsns_year):
        for fs_div in ("CFS", "OFS"):
            body = self.client.fnlttSinglAcntAll(corp_code, bsns_year, fs_div)
            if body:
                return body
        return []

    def _fetch_from_audit_reports(self, corp_code: str, end_year: int,
                                  max_years: int) -> list[FinancialYear]:
        """외감 비상장: 감사보고서 원문(document.xml) 파싱으로 5개년 합성.

        보고서 1건 = 당기·전기 2개년. 연결감사보고서 우선, 없으면 (별도)감사보고서.
        표 파싱 실패·자료 없음 시 빈 리스트(조용히 0 금지). 기능 미보유 client면 [].
        """
        if not (hasattr(self.client, "list_audit_reports")
                and hasattr(self.client, "fetch_document")):
            return []
        try:
            reports = self.client.list_audit_reports(corp_code)  # [(year, rcept, consol)]
        except Exception as e:  # noqa: BLE001 — fallback은 조용히 degrade
            log.warning("audit list fail %s: %s", corp_code, e)
            return []
        if not reports:
            return []

        # 연결 우선, 없으면 별도 pool
        con = {y: rc for y, rc, c in reports if c}
        sep = {y: rc for y, rc, c in reports if not c}
        pool = con or sep
        if not pool:
            return []

        avail = sorted(pool.keys(), reverse=True)
        start = next((y for y in avail if y <= end_year), avail[0])
        need_year, chosen = start, []
        # 보고서 1건당 2개년 → max_years 커버할 만큼 end·end-2·end-4… 선택
        while need_year >= start - max_years and len(chosen) * 2 < max_years + 1:
            cand = next((y for y in avail if y <= need_year), None)
            if cand is None:
                break
            if cand not in [c[0] for c in chosen]:
                chosen.append((cand, pool[cand]))
            need_year = cand - 2

        merged: dict[int, dict] = {}
        for yr, rcept in chosen:
            try:
                text = self.client.fetch_document(rcept)
            except Exception as e:  # noqa: BLE001
                log.warning("audit doc fetch fail %s: %s", rcept, e)
                continue
            if not text:
                continue
            try:
                fields = _parse_fs_document(text, yr)
            except Exception as e:  # noqa: BLE001
                log.warning("audit FS parse fail %s: %s", rcept, e)
                continue
            for y, f in fields.items():
                merged.setdefault(y, {}).update(f)

        return [FinancialYear(year=y, **f) for y, f in sorted(merged.items())]
