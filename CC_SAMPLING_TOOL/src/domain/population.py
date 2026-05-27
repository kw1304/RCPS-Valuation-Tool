"""
모집단 완전성 검토 + 발송제외 + Key item 추출

처리:
1. 거래처별 원장 → 거래처별 합계 잔액 (계정과목 그룹별로도)
2. 회사 제시 명세서 합계 ↔ 재무제표 대사
3. 발송제외 거래처 reconcile (채권성격 아님, 임직원 등)
4. 특관자 자동 표시
5. Key item 추출 (잔액 ≥ 기준금액)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd


def _normalize_account_name(name: str) -> str:
    """계정과목명 정규화 — 영문 대소문자·공백·특수문자 통일.

    예: "Accounts Receivable" → "accounts receivable"
        "A/R" → "a/r"
    """
    return name.strip().lower()


def _load_account_group_map(kind: str) -> dict[str, str]:
    """configs/account_groups/default.yaml 로드.
    파일 없거나 파싱 실패 시 하드코딩 dict fallback 사용.

    반환값: {normalize(원장계정과목명) → 표준그룹명} — case-insensitive 검색용.
    """
    _CONFIG = (
        Path(__file__).resolve().parents[2]
        / "configs" / "account_groups" / "default.yaml"
    )
    try:
        import yaml  # type: ignore
        with open(_CONFIG, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        section = data.get(kind, {})
        if isinstance(section, dict) and section:
            # normalize 키 → 대소문자 무관 매핑 구축
            return {_normalize_account_name(k): v for k, v in section.items()}
    except Exception:
        pass
    # fallback: 하드코딩 dict (하단 정의)
    if kind == "receivable":
        return {_normalize_account_name(k): v for k, v in _FALLBACK_RECEIVABLE.items()}
    return {_normalize_account_name(k): v for k, v in _FALLBACK_PAYABLE.items()}


# 표준 계정 그룹 매핑 (원장 계정과목명 → 그룹)
# 직접 참조 시 호환성 유지 — 내부적으로는 YAML 로드 결과를 우선 사용
ACCOUNT_GROUP_MAP_RECEIVABLE: dict[str, str] = {
    "외상매출금": "외상매출금",
    "외상매출금(국내)": "외상매출금",
    "외상매출금(관계사)": "외상매출금",
    "외상매출금(관계사조정)": "외상매출금",
    "받을어음": "받을어음",
    "미수금": "미수금",
    "미수금(국내)": "미수금",
    "미수금(관계사)": "미수금",
    "선급금": "선급금",
    "선급금(국내)": "선급금",
    "단기대여금": "단기대여금",
    "장기대여금": "장기대여금",
    "임차보증금": "임차보증금",
    "기타보증금": "기타보증금",
}

ACCOUNT_GROUP_MAP_PAYABLE: dict[str, str] = {
    "외상매입금": "외상매입금",
    "외상매입금(국내)": "외상매입금",
    "외상매입금(관계사)": "외상매입금",
    "외담대외상매입금": "지급어음(외담대외상매입금)",
    "지급어음": "지급어음(외담대외상매입금)",
    "미지급금": "미지급금",
    "미지급금(국내)": "미지급금",
    "미지급금(국외)": "미지급금",
    "미지급금(관계사)": "미지급금",
    "외담대미지급금": "미지급금",
    "선수금": "선수금",
    "임대보증금": "임대보증금",
}

# YAML 로드 실패 시 fallback 용 내부 참조
_FALLBACK_RECEIVABLE = dict(ACCOUNT_GROUP_MAP_RECEIVABLE)
_FALLBACK_PAYABLE = dict(ACCOUNT_GROUP_MAP_PAYABLE)


@dataclass
class LedgerRow:
    code: str           # 거래처 코드
    name: str           # 거래처명
    account_code: str
    account_name: str
    currency: str
    beginning: float
    change: float
    ending: float


@dataclass
class PartyBalance:
    name: str
    by_account: dict[str, float] = field(default_factory=dict)   # 그룹별 잔액
    total: float = 0.0

    def add(self, group: str, amount: float) -> None:
        self.by_account[group] = self.by_account.get(group, 0.0) + amount
        self.total += amount


def load_ledger_rows(
    df: pd.DataFrame,
    kind: str = "receivable",
    col_map: dict[str, int | None] | None = None,
) -> list[LedgerRow]:
    """거래처별 원장 DataFrame → LedgerRow 리스트

    col_map: detect_ledger_columns() 결과 dict.
             None이면 7620 기본 컬럼 순서(0~7)를 사용 — 하위 호환.
    예상 컬럼: 코드|명|계정과목|계정과목명|통화|기초|증감|기말
    """
    # col_map 미제공 시 7620 기본 순서 사용 (하위 호환)
    _default: dict[str, int] = {
        "code_col": 0, "name_col": 1, "account_code": 2, "account_name": 3,
        "currency": 4, "beginning": 5, "change": 6, "ending": 7,
    }
    m: dict[str, int] = {}
    if col_map:
        for k, default_idx in _default.items():
            v = col_map.get(k)
            m[k] = v if v is not None else default_idx
    else:
        m = dict(_default)

    rows: list[LedgerRow] = []
    for _, r in df.iterrows():
        name = str(r.iloc[m["name_col"]]) if pd.notna(r.iloc[m["name_col"]]) else ""
        if not name.strip():
            continue
        code = str(r.iloc[m["code_col"]]) if pd.notna(r.iloc[m["code_col"]]) else ""
        acct_code = str(r.iloc[m["account_code"]]) if pd.notna(r.iloc[m["account_code"]]) else ""
        acct_name = str(r.iloc[m["account_name"]]) if pd.notna(r.iloc[m["account_name"]]) else ""
        ccy = str(r.iloc[m["currency"]]) if pd.notna(r.iloc[m["currency"]]) else "KRW"
        try:
            beg = float(r.iloc[m["beginning"]]) if pd.notna(r.iloc[m["beginning"]]) else 0.0
            chg = float(r.iloc[m["change"]]) if pd.notna(r.iloc[m["change"]]) else 0.0
            end = float(r.iloc[m["ending"]]) if pd.notna(r.iloc[m["ending"]]) else 0.0
        except (ValueError, TypeError):
            continue
        rows.append(LedgerRow(code, name, acct_code, acct_name, ccy, beg, chg, end))
    return rows


def aggregate_by_party(
    rows: Iterable[LedgerRow],
    kind: str = "receivable",
    sign_normalize: bool = True,
) -> dict[str, PartyBalance]:
    """거래처별 그룹화. 채무는 음수로 적재되므로 sign_normalize=True 시 절대값화."""
    group_map = _load_account_group_map(kind)  # keys are normalized (lowercase)
    parties: dict[str, PartyBalance] = {}
    for r in rows:
        norm_acct = _normalize_account_name(r.account_name)
        group = group_map.get(norm_acct, r.account_name)
        amt = abs(r.ending) if sign_normalize else r.ending
        if r.name not in parties:
            parties[r.name] = PartyBalance(name=r.name)
        parties[r.name].add(group, amt)
    return parties


@dataclass
class CompletenessCheck:
    by_group: list[dict]      # [{group, ledger, fs, diff, note}, ...]
    total_ledger: float
    total_fs: float
    total_diff: float


def check_completeness(
    parties: dict[str, PartyBalance],
    fs_amounts: dict[str, float],
    notes: dict[str, str] | None = None,
) -> CompletenessCheck:
    """그룹별 원장합계 vs 재무제표 비교"""
    notes = notes or {}
    ledger_by_group: dict[str, float] = {}
    for pb in parties.values():
        for g, amt in pb.by_account.items():
            ledger_by_group[g] = ledger_by_group.get(g, 0.0) + amt

    all_groups = sorted(set(ledger_by_group) | set(fs_amounts))
    rows = []
    for g in all_groups:
        led = ledger_by_group.get(g, 0.0)
        fs = fs_amounts.get(g, 0.0)
        rows.append({"group": g, "ledger": led, "fs": fs, "diff": led - fs, "note": notes.get(g, "")})

    return CompletenessCheck(
        by_group=rows,
        total_ledger=sum(r["ledger"] for r in rows),
        total_fs=sum(r["fs"] for r in rows),
        total_diff=sum(r["diff"] for r in rows),
    )


@dataclass
class PartyDecision:
    name: str
    balance: float
    is_excluded: bool          # 발송제외
    is_related_party: bool     # 특관자
    is_key_item: bool          # Key item (잔액 ≥ 기준금액)
    is_representative: bool    # MUS 추출 표본
    final_sampled: bool        # 최종 샘플링 대상
    exclusion_reason: str = ""
    by_account: dict[str, float] = field(default_factory=dict)   # 계정그룹별 잔액


def classify_parties(
    parties: dict[str, PartyBalance],
    key_item_threshold: float,
    related_party_names: set[str],
    excluded_parties: dict[str, str] | None = None,   # {name: reason}
) -> list[PartyDecision]:
    excluded_parties = excluded_parties or {}
    decisions: list[PartyDecision] = []
    for pb in parties.values():
        excl = pb.name in excluded_parties
        rp = _is_related_party(pb.name, related_party_names)
        ki = (pb.total >= key_item_threshold) and not excl
        decisions.append(PartyDecision(
            name=pb.name,
            balance=pb.total,
            is_excluded=excl,
            is_related_party=rp,
            is_key_item=ki,
            is_representative=False,
            final_sampled=False,
            exclusion_reason=excluded_parties.get(pb.name, ""),
            by_account=dict(pb.by_account),
        ))
    decisions.sort(key=lambda d: d.name)
    return decisions


def _is_related_party(name: str, rp_set: set[str]) -> bool:
    """이름 유사 매칭 (특관자리스트가 표기 변형 많음)"""
    norm = _normalize(name)
    return any(_normalize(rp) == norm or _normalize(rp) in norm or norm in _normalize(rp) for rp in rp_set)


def _normalize(s: str) -> str:
    return (
        s.replace(" ", "")
        .replace(",", "")
        .replace(".", "")
        .replace("㈜", "")
        .replace("(주)", "")
        .replace("주식회사", "")
        .upper()
    )
