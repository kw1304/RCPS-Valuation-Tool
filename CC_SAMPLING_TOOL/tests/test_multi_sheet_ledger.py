"""test_multi_sheet_ledger.py — 다중 시트 원장 인식 검증

코스맥스네오 양식처럼 시트별 계정과목이 분리된 원장을 자동 인식·통합하는
기능을 검증한다. 7620 단일 시트 방식과 공존 가능해야 한다.

검증 항목:
  1. detect_multi_account_sheets: 12개 시트 → 채권 6개 / 채무 6개
  2. is_multi_sheet_ledger: 다중 시트 방식 판정
  3. load_multi_sheet_ledger: 채권 통합 DataFrame 로드
  4. load_ledger_rows + account_name_override: 시트명 = 계정과목명 주입
  5. 집계 행("합계") 자동 제외
  6. 7620 단일 시트 방식은 영향 없음 (회귀 보호)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from src.infrastructure.schemas.ledger_schema import (
    detect_multi_account_sheets,
    is_multi_sheet_ledger,
    detect_ledger_sheets,
    detect_ledger_columns,
)
from src.domain.population import load_ledger_rows, LedgerRow


# ── 픽스처: 코스맥스네오 12개 시트 이름 ────────────────────────────────────
NEO_SHEETS = [
    "외상매출금", "받을어음", "단기대여금", "미수금", "선급금", "임차보증금",
    "외상매입금", "지급어음", "미지급금", "선수금", "단기차입금", "임대보증금",
]

# ── 픽스처: 7620 단일 시트 이름 ─────────────────────────────────────────────
LEGACY_SHEETS = ["채권", "채무", "특관자"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. detect_multi_account_sheets
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_multi_account_receivable():
    """채권 계정과목 시트 6개 자동 감지."""
    result = detect_multi_account_sheets(NEO_SHEETS)
    expected_r = {"외상매출금", "받을어음", "단기대여금", "미수금", "선급금", "임차보증금"}
    assert set(result["receivable"]) == expected_r


def test_detect_multi_account_payable():
    """채무 계정과목 시트 6개 자동 감지."""
    result = detect_multi_account_sheets(NEO_SHEETS)
    expected_p = {"외상매입금", "지급어음", "미지급금", "선수금", "단기차입금", "임대보증금"}
    assert set(result["payable"]) == expected_p


def test_detect_multi_account_empty_for_legacy():
    """7620 단일 시트 방식은 다중 계정과목 시트로 인식되지 않는다."""
    result = detect_multi_account_sheets(LEGACY_SHEETS)
    assert result["receivable"] == []
    assert result["payable"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. is_multi_sheet_ledger
# ─────────────────────────────────────────────────────────────────────────────

def test_is_multi_sheet_neo():
    """코스맥스네오 12개 시트 → 다중 시트 방식 판정 True."""
    assert is_multi_sheet_ledger(NEO_SHEETS) is True


def test_is_multi_sheet_legacy():
    """7620 단일 시트 방식 → False."""
    assert is_multi_sheet_ledger(LEGACY_SHEETS) is False


def test_is_multi_sheet_partial():
    """채권 시트 2개 이상 → True."""
    assert is_multi_sheet_ledger(["외상매출금", "받을어음", "기타시트"]) is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. detect_ledger_sheets — 다중 시트 방식에서는 단일 채권/채무 시트 미감지
# ─────────────────────────────────────────────────────────────────────────────

def test_detect_ledger_sheets_neo_returns_none():
    """다중 시트 방식에서는 단일 "채권"/"채무" 시트를 None으로 반환.

    이때 호출 측은 detect_multi_account_sheets()로 전환해야 한다.
    """
    result = detect_ledger_sheets(NEO_SHEETS)
    # "외상매출금" 등이 부분매칭("매출")에 걸리지 않도록 설계되어야 함
    # → 채권 계정과목 시트 자체는 단일 채권 시트로 오인하지 않음
    assert result["receivable"] is None
    assert result["payable"] is None


def test_detect_ledger_sheets_legacy_still_works():
    """7620 단일 시트 방식은 기존 결과 그대로."""
    result = detect_ledger_sheets(LEGACY_SHEETS)
    assert result["receivable"] == "채권"
    assert result["payable"] == "채무"


# ─────────────────────────────────────────────────────────────────────────────
# 4. 컬럼 감지 — 코스맥스네오 헤더
# ─────────────────────────────────────────────────────────────────────────────

def _make_neo_df(rows=None, account="외상매출금"):
    """코스맥스네오 양식 DataFrame 생성."""
    cols = ["코드", "거래처명", "사업자번호", "전기(월)이월", "증가", "감소", "잔액",
            "거래처분류코드", "거래처분류명", "국가코드", "국가명", "대표자성명"]
    data = rows or [
        [1, "코스맥스(주)", "143-81-19635", 3_186_512_341, 55_756_730_224, 54_054_888_121, 4_888_354_444, None, None, None, None, "이병만"],
        [123, "(주)코스모코스", "139-81-11288", 0, 78_334_905, 56_233_650, 22_101_255, None, None, None, None, "강석창"],
    ]
    df = pd.DataFrame(data, columns=cols)
    df["_sheet_account_name"] = account
    return df


def test_detect_neo_columns():
    """코스맥스네오 헤더 → 컬럼 인덱스 정확 감지."""
    df = _make_neo_df()
    col_map = detect_ledger_columns(df)

    assert col_map["code_col"] == 0       # 코드
    assert col_map["name_col"] == 1       # 거래처명
    assert col_map["business_no"] == 2    # 사업자번호
    assert col_map["beginning"] == 3      # 전기(월)이월
    assert col_map["increase"] == 4       # 증가
    assert col_map["decrease"] == 5       # 감소
    assert col_map["ending"] == 6         # 잔액


def test_detect_neo_beginning_not_equal_ending():
    """beginning과 ending이 서로 다른 컬럼으로 감지된다 (충돌 해소 검증)."""
    df = _make_neo_df()
    col_map = detect_ledger_columns(df)
    assert col_map["beginning"] != col_map["ending"]
    assert col_map["ending"] == 6  # "잔액" 컬럼


# ─────────────────────────────────────────────────────────────────────────────
# 5. load_ledger_rows + account_name_override
# ─────────────────────────────────────────────────────────────────────────────

def test_load_rows_with_account_override():
    """account_name_override='외상매출금' → 모든 LedgerRow에 주입."""
    df = _make_neo_df(account="외상매출금")
    col_map = detect_ledger_columns(df)
    rows = load_ledger_rows(
        df, kind="receivable", col_map=col_map,
        account_name_override="외상매출금",
    )
    assert all(r.account_name == "외상매출금" for r in rows)


def test_load_rows_increase_populated():
    """증가 컬럼 값이 LedgerRow.increase 에 정확히 주입."""
    df = _make_neo_df()
    col_map = detect_ledger_columns(df)
    rows = load_ledger_rows(df, kind="receivable", col_map=col_map,
                             account_name_override="외상매출금")
    # 첫 번째 행: 증가 = 55,756,730,224
    assert rows[0].increase == pytest.approx(55_756_730_224)
    assert rows[0].ending == pytest.approx(4_888_354_444)
    assert rows[0].beginning == pytest.approx(3_186_512_341)


def test_load_rows_business_no_populated():
    """사업자번호 컬럼이 LedgerRow.business_no에 주입."""
    df = _make_neo_df()
    col_map = detect_ledger_columns(df)
    rows = load_ledger_rows(df, kind="receivable", col_map=col_map,
                             account_name_override="외상매출금")
    assert rows[0].business_no == "143-81-19635"
    assert rows[1].business_no == "139-81-11288"


# ─────────────────────────────────────────────────────────────────────────────
# 6. 집계 행("합계") 제외
# ─────────────────────────────────────────────────────────────────────────────

def test_load_rows_skips_total_row():
    """'합계' 거래처명 행은 자동 제외된다."""
    data = [
        [1,    "코스맥스(주)",  "143-81-19635", 1_000_000, 5_000_000, 4_000_000, 2_000_000, None, None, None, None, ""],
        ["합계", "합계",        None,           1_000_000, 5_000_000, 4_000_000, 2_000_000, None, None, None, None, ""],
    ]
    df = _make_neo_df(rows=data)
    col_map = detect_ledger_columns(df)
    rows = load_ledger_rows(df, kind="receivable", col_map=col_map,
                             account_name_override="외상매출금")
    names = [r.name for r in rows]
    assert "합계" not in names
    assert len(rows) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. 실제 코스맥스네오 파일 통합 테스트 (파일 존재 시만 실행)
# ─────────────────────────────────────────────────────────────────────────────

NEO_LEDGER_PATH = ROOT / "input" / "코스맥스네오" / "채권채무조회서 (3)" / "코스맥스네오_거래처원장_26.01.21.xlsx"


@pytest.mark.skipif(not NEO_LEDGER_PATH.exists(), reason="코스맥스네오 원장 파일 없음")
def test_neo_multi_sheet_load_receivable():
    """코스맥스네오 실제 파일 — 채권 6시트 통합 로드."""
    from src.infrastructure.loaders import load_multi_sheet_ledger
    from src.domain.population import load_ledger_rows

    merged_df, col_map = load_multi_sheet_ledger(NEO_LEDGER_PATH, kind="receivable")

    assert "_sheet_account_name" in merged_df.columns
    account_names = set(merged_df["_sheet_account_name"].unique())
    expected = {"외상매출금", "받을어음", "단기대여금", "미수금", "선급금", "임차보증금"}
    assert expected == account_names, f"감지된 채권 시트: {account_names}"

    # 통합 로드 후 LedgerRow 생성
    rows_all = []
    for acct, sub in merged_df.groupby("_sheet_account_name", sort=False):
        rows_all.extend(
            load_ledger_rows(sub.reset_index(drop=True), kind="receivable",
                             col_map=col_map, account_name_override=str(acct))
        )

    assert len(rows_all) > 0
    # 집계 행 제외 확인
    assert all(r.name.strip() not in ("합계", "소계") for r in rows_all)
    # increase 컬럼 주입 확인
    assert any(r.increase > 0 for r in rows_all)


@pytest.mark.skipif(not NEO_LEDGER_PATH.exists(), reason="코스맥스네오 원장 파일 없음")
def test_neo_multi_sheet_load_payable():
    """코스맥스네오 실제 파일 — 채무 6시트 통합 로드."""
    from src.infrastructure.loaders import load_multi_sheet_ledger
    from src.domain.population import load_ledger_rows

    merged_df, col_map = load_multi_sheet_ledger(NEO_LEDGER_PATH, kind="payable")

    account_names = set(merged_df["_sheet_account_name"].unique())
    expected = {"외상매입금", "지급어음", "미지급금", "선수금", "단기차입금", "임대보증금"}
    assert expected == account_names, f"감지된 채무 시트: {account_names}"
