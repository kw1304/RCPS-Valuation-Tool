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
    from_financial: bool = False   # True iff 금융계정(예금·차입·유가증권·보험 등) row에서 매칭 — 0잔액이어도 조회대상

    def entity_key(self) -> str:
        return self.party.entity_key()


class Sampler:
    """Step A: 금융계정 row에서 거래처 추출 (B/S+P/L)
       Step B: 일반계정 row에서 alias 매칭으로 추가
       Step C: entity_key 기준 dedupe + 합산"""

    def __init__(self, classifier: FinancialAccountClassifier, normalizer: PartyNormalizer):
        self.classifier = classifier
        self.normalizer = normalizer

    # 무시할 컬럼 (alias scan 대상 외)
    _NON_TEXT_COLS = {"금액","Ld","CoCd","회계","입력일","일자","계정","문서 번호","전표 번호","전표 종류"}

    def _scan_all_texts(self, row: dict, exclude: set[str] = None) -> list[tuple[str, str]]:
        """row의 모든 문자열 컬럼을 sweep. exclude 컬럼은 제외.
        Returns list of (column_name, text) for scanning."""
        out = []
        skip = self._NON_TEXT_COLS | (exclude or set())
        for col, val in row.items():
            if col in skip:
                continue
            if not isinstance(val, str):
                continue
            s = val.strip()
            if s:
                out.append((col, s))
        return out

    def sample(self, rows: list[dict]) -> list[SampledParty]:
        agg: dict[str, SampledParty] = {}
        for row in rows:
            acc = (row.get("계정 과목") or "").strip()
            party_raw = (row.get("거래처") or "").strip()
            memo = (row.get("적요") or "").strip()
            amount = self._to_float(row.get("금액"))
            bucket = self.classifier.classify(acc)
            # Step A: 금융계정 row — 거래처 우선, 그 다음 적요, 그 다음 모든 텍스트 sweep (단 매칭된 경우만)
            if bucket:
                # 1. 거래처
                np_party = self.normalizer.normalize(party_raw) if party_raw else None
                if np_party and np_party.matched:
                    self._add(agg, np_party, bucket, acc, amount, conf=1.0)
                    continue
                # 2. 적요
                if memo:
                    np_memo = self.normalizer.normalize(memo)
                    if np_memo.matched:
                        self._add(agg, np_memo, bucket, acc, amount, conf=0.85)
                        continue
                # 3. 모든 다른 텍스트 컬럼 sweep (계정명, 문서메모 등)
                added = False
                for col, text in self._scan_all_texts(row, exclude={"거래처","적요"}):
                    np = self.normalizer.normalize(text)
                    if np.matched:
                        self._add(agg, np, bucket, acc, amount, conf=0.7)
                        added = True
                        break
                if added:
                    continue
                # 매칭 실패한 financial-account row → skip
                continue
            # Step B: 일반계정 — 모든 텍스트 컬럼 sweep
            for col, text in self._scan_all_texts(row):
                conf = 0.7 if col == "거래처" else 0.6 if col == "적요" else 0.5
                np = self.normalizer.normalize(text)
                if np.matched:
                    self._add(agg, np, "기타", acc, amount, conf=conf)
                    break
        # G/L에 등장한 모든 금융기관(거래처·계정명·적요 언급 포함)을 표본 후보로 — 잔액 0 무관.
        # (계정과목·메모문장·IT'뱅크'·렌탈 vendor 등 비금융 noise는 normalize 단계에서 이미 배제됨)
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
        if bucket != "기타":
            sp.from_financial = True   # 금융계정 출처 → 0잔액이어도 표본 유지
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
