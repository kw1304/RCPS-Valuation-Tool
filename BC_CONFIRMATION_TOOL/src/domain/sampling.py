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

    def entity_key(self) -> str:
        return self.party.entity_key()


class Sampler:
    """Step A: 금융계정 row에서 거래처 추출 (B/S+P/L)
       Step B: 일반계정 row에서 alias 매칭으로 추가
       Step C: entity_key 기준 dedupe + 합산"""

    def __init__(self, classifier: FinancialAccountClassifier, normalizer: PartyNormalizer):
        self.classifier = classifier
        self.normalizer = normalizer

    def sample(self, rows: list[dict]) -> list[SampledParty]:
        agg: dict[str, SampledParty] = {}
        for row in rows:
            acc = (row.get("계정 과목") or "").strip()
            party_raw = (row.get("거래처") or "").strip()
            memo = (row.get("적요") or "").strip()
            amount = self._to_float(row.get("금액"))
            bucket = self.classifier.classify(acc)
            party_text = party_raw or memo
            if not party_text:
                continue
            # Step A: 금융계정 row
            if bucket:
                np = self.normalizer.normalize(party_text)
                self._add(agg, np, bucket, acc, amount, conf=1.0)
                continue
            # Step B: 일반계정에서 alias 매칭
            np = self.normalizer.normalize(party_text)
            if np.canonical != party_text and np.canonical != "":
                # canonical 매칭이 있으면 추가 (하지만 confidence 낮춤)
                self._add(agg, np, "기타", acc, amount, conf=0.6)
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
