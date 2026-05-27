"""
7620 조서 기준값 회귀 테스트

조서 C100-1 표본규모 결정 시트 값:
  모집단 = 158,586,818,738
  PM = 2,738,000,000
  Key item 기준금액 = 2,053,500,000  (PM × 75%)
  Key item 합계 = 150,984,925,323 (6건)
  잔여 모집단 = 7,601,893,415
  Base sample size = 2.776440253834916
  Confidence factor = 1.4
  Final sample size = 4
  표본간격 = 1,900,473,353.75

K-IFRS 1109 잔액 평가는 본 툴 범위 밖.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import math
import pytest

from src.domain.mus import run_mus
from src.domain.sample_size import SampleSizeInput, compute_sample_size


def test_size_decision_matches_7620():
    inp = SampleSizeInput(
        population_amount=158_586_818_738,
        performance_materiality=2_738_000_000,
        risk_level="유의적위험",
        control_reliance="Y",
        key_item_amount=150_984_925_323,
    )
    r = compute_sample_size(inp)

    assert r.key_item_threshold == pytest.approx(2_053_500_000, rel=1e-9)
    assert r.key_item_ratio == pytest.approx(0.75, rel=1e-9)
    assert r.confidence_factor == pytest.approx(1.4, rel=1e-9)
    assert r.remaining_population == pytest.approx(7_601_893_415, rel=1e-9)
    assert r.base_sample_size == pytest.approx(2.776440253834916, rel=1e-9)
    assert r.final_sample_size == 4
    assert r.sample_interval == pytest.approx(1_900_473_353.75, rel=1e-9)


def test_mus_algorithm_with_known_start():
    """조서 R16: 임의출발점 530,816,314 → R28(COSMAX Thailand 누적 22,981,954), R41(科美州 누적 464,712,545) hit"""
    pool = [
        ("(주) 삼정트레이딩", 3_773_000),
        ("(주)미르인터내셔날", 12_540_000),
        ("(주)믹스앤매치", 10_802_550),
        ("(주)씨아이디코리아(CID KOREA corp.)", 28_617_600),
        ("(주)이화피엔씨", 1_430_000),
        ("AZELIS TURKIYE", 152_749_549),
        ("COSMAX (Thailand) Co., Ltd.", 343_885_569),
        ("COSMAX BIO TECH, INC.", 65_188_798),
        ("COSMAX JAPAN, INC.", 13_879_057),
        ("COSMAX MALAYSIA SDN. BHD", 2_990_565),
        ("COSMAX NBT AUSTRALIA PTY. LTD", 87_652_937),
        ("COSMAX NBT SHANGHAI CO.LTD", 24_307_023),
        ("COSMAX NBT SINGAPORE, INC", 1_084_885),
        ("COSMAX NBT USA, INC.", 16_345_353),
        ("Cosmax USA, Corp.", 1_010_458_852),
        ("Guangzhou Batai International Trade", 22_479_280),
        ("New Future International Trade Co.", 196_426_955),
        ("Shanghai Nahui International Trade", 138_909_336),
        ("강요엘", 85_200),
        ("科#美#(#州)化#品有限公司", 762_395_704),
    ]
    result = run_mus(
        pool=pool,
        sample_size=4,
        sample_interval=1_900_473_353.75,
        random_start=530_816_314,
    )
    hit_names = [s.name for s in result.selections if s.hit]
    # 조서: COSMAX (Thailand), 科美州 hit
    assert "COSMAX (Thailand) Co., Ltd." in hit_names
    assert "科#美#(#州)化#品有限公司" in hit_names


if __name__ == "__main__":
    test_size_decision_matches_7620()
    test_mus_algorithm_with_known_start()
    print("[OK] All tests passed")
