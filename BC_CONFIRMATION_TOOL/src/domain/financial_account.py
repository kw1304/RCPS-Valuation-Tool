from pathlib import Path
import yaml


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

        # exact match first
        if account_name in self.buckets:
            return self.buckets[account_name]

        # substring match (긴 keyword 우선)
        for kw in sorted(self.buckets.keys(), key=len, reverse=True):
            if kw in account_name:
                return self.buckets[kw]

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
