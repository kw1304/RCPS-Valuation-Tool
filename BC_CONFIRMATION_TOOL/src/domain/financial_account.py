from pathlib import Path
import yaml

# 짧은 키워드(주식·채권 등)가 비금융 계정과목에 부분일치하는 오분류 차단.
# 예: '매출채권'(채권)·'주식발행초과금'·'자기주식'(주식)은 금융상품 계정이 아니다.
_NONFIN_ACCOUNT_MARKERS: tuple[str, ...] = (
    "매출채권", "받을채권", "미수채권", "공사미수금",
    "주식발행초과금", "자기주식", "주식매수선택권", "주식보상",
)

# P/L 손익 계정 접미사 — B/S 키워드에 부분일치해도 B/S 버킷으로 오귀속 금지.
_PL_SUFFIXES: tuple[str, ...] = (
    "손실", "손익", "이익", "차익", "차손", "환입", "환급",
)


class FinancialAccountClassifier:
    def __init__(self, direct_accounts: dict[str, list[str]]):
        """Initialize with direct_accounts mapping from YAML."""
        self.buckets: dict[str, str] = {}
        for bucket, keywords in direct_accounts.items():
            for k in keywords:
                self.buckets[k] = bucket

    @classmethod
    def load(cls, yaml_path: Path) -> "FinancialAccountClassifier":
        """Load classifier from YAML config file."""
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(data["direct_accounts"])

    def classify(self, account_name: str) -> str | None:
        """Returns bucket name ('예금','차입',...) or None.

        Logic:
        1. Exact match first
        2. Substring match (긴 keyword 우선 - longest first)
        """
        if not account_name:
            return None

        # 비금융 계정 제외(짧은 키워드 오분류 방지): 매출채권→채권, 주식발행초과금→주식 등.
        if any(m in account_name for m in _NONFIN_ACCOUNT_MARKERS):
            return None

        # exact match first
        if account_name in self.buckets:
            return self.buckets[account_name]

        # substring match (긴 keyword 우선)
        for kw in sorted(self.buckets.keys(), key=len, reverse=True):
            if kw in account_name:
                bucket = self.buckets[kw]
                # P/L 손익 계정이 B/S 키워드에 부분일치하면(현금성자산처분손실→예금) B/S로
                # 오귀속 금지 — 손익 접미사면 그 B/S 매칭은 무시하고 다음(손익) 키워드 탐색.
                if self.is_balance_sheet(bucket) and account_name.endswith(_PL_SUFFIXES):
                    continue
                return bucket

        return None

    def is_financial(self, account_name: str) -> bool:
        """Check if account is classified as financial."""
        return self.classify(account_name) is not None

    def is_balance_sheet(self, bucket: str) -> bool:
        """Check if bucket is balance sheet category."""
        return bucket in {"예금", "차입", "파생", "보증", "담보", "유가증권", "보험"}

    def is_profit_loss(self, bucket: str) -> bool:
        """Check if bucket is profit & loss category."""
        return bucket in {"이자손익", "외환", "평가손익", "수수료", "배당", "보험비용"}
