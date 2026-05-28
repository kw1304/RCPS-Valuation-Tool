from pathlib import Path
from src.domain.financial_account import FinancialAccountClassifier

CFG = Path(__file__).resolve().parents[2] / "configs" / "financial_keywords.yaml"

def test_classify_bs_deposit():
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("보통예금") == "예금"
    assert clf.classify("정기예금") == "예금"

def test_classify_pl_interest():
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("이자수익") == "이자손익"
    assert clf.classify("차입금이자") == "이자손익"

def test_classify_unknown():
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("매출원가") is None

def test_classify_partial_match():
    # 부분 매칭: "단기금융상품-우리은행" → "예금" 분류
    clf = FinancialAccountClassifier.load(CFG)
    assert clf.classify("단기금융상품-우리은행") == "예금"
