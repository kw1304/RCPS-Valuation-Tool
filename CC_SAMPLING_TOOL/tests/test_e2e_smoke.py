"""End-to-end smoke test — 실제 회사자료로 조서 생성"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.infrastructure.loaders import load_related_parties
from src.orchestrator import SamplingParams, run_sampling, write_report


def main():
    ledger_path = ROOT / "input" / "회사자료" / "채권채무조회서 거래처별 원장.XLSX"
    df_ar = pd.read_excel(ledger_path, sheet_name="채권")

    조서_path = ROOT / "input" / "조서" / "7620_코스맥스비티아이_C100_AA100 채권 채무 조회_FY25.xlsx"
    rp = load_related_parties(조서_path, sheet="특관자리스트")
    print(f"특관자 {len(rp)}건 로드")

    params = SamplingParams(
        company_name="코스맥스비티아이",
        period_end=date(2025, 12, 31),
        kind="receivable",
        performance_materiality=2_738_000_000,
        risk_level="유의적위험",
        control_reliance="Y",
        key_item_ratio_override=0.75,
        confidence_factor_override=1.4,
        fs_amounts_by_group={
            "외상매출금": 34_327_474_929,
            "받을어음": 12_770_444_374,
            "미수금": 1_804_332_594,
            "선급금": 2_424_082_067,
            "장기대여금": 108_162_000_187,
            "임차보증금": 671_903_200,
            "기타보증금": 66_568_000,
        },
        excluded_parties={"helloBiome safe": "금융상품으로 잡기 전 임시 선급금, 채권성격 아님"},
        related_parties=rp,
        force_include_related=True,
        random_seed=42,
        preparer="이슬기",
        reviewer="이병기",
    )

    result = run_sampling(df_ar, params)
    print(f"\n=== 샘플링 결과 ===")
    print(f"모집단: {result.population_amount:,.0f}")
    print(f"PM: {params.performance_materiality:,.0f}")
    print(f"Key item 기준금액: {result.size_result.key_item_threshold:,.0f}")
    print(f"Key item 개수: {sum(1 for d in result.decisions if d.is_key_item)}")
    print(f"Representative: {sum(1 for d in result.decisions if d.is_representative and not d.is_key_item)}")
    print(f"특관자 포함: {sum(1 for d in result.decisions if d.is_related_party and d.final_sampled)}")
    print(f"최종 샘플링: {sum(1 for d in result.decisions if d.final_sampled)}")
    print(f"Final sample size: {result.size_result.final_sample_size}")
    print(f"표본간격: {result.size_result.sample_interval:,.0f}")

    out_path = ROOT / "output" / "C100_smoke.xlsx"
    write_report(result, params, out_path)
    print(f"\n[OK] 조서 저장: {out_path}")


if __name__ == "__main__":
    main()
