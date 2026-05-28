from pathlib import Path
from src.domain.sampling import Sampler
from src.domain.financial_account import FinancialAccountClassifier
from src.domain.party_normalize import PartyNormalizer
from src.infrastructure.gl_loader import GLLoader

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs"
FIX = ROOT / "tests" / "fixtures" / "mini_gl.xlsx"


def test_sampling_extracts_financial_parties_only():
    clf = FinancialAccountClassifier.load(CFG / "financial_keywords.yaml")
    norm = PartyNormalizer.load(CFG)
    rows = list(GLLoader(FIX).iter_rows())
    parties = Sampler(clf, norm).sample(rows)
    keys = sorted(p.entity_key() for p in parties)
    # 국민은행 (도메스틱), 신한은행 도쿄지점 (외국), 우리은행 (도메스틱)
    assert "국민은행|" in keys
    assert "신한은행|도쿄지점" in keys
    assert "우리은행|" in keys
    # 공급처A는 금융계정 row 없음 → 제외
    assert all("공급처A" not in k for k in keys)


def test_sampling_aggregates_balance_and_volume():
    clf = FinancialAccountClassifier.load(CFG / "financial_keywords.yaml")
    norm = PartyNormalizer.load(CFG)
    rows = list(GLLoader(FIX).iter_rows())
    parties = Sampler(clf, norm).sample(rows)
    by_key = {p.entity_key(): p for p in parties}
    assert by_key["국민은행|"].bs_amount == 1000000.0       # 보통예금
    assert by_key["신한은행|도쿄지점"].bs_amount == -5000000.0  # 차입금
    assert by_key["우리은행|"].pl_amount == 123456.0         # 이자수익
