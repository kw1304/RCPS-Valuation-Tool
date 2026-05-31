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
    # ── 코스맥스네오 확장 필드 ─────────────────────────────────────────────
    # 증가/감소 컬럼이 별도로 존재하는 양식(시트별 계정과목 분리)에서 사용.
    # ISA 505 완전성 검토: 채무 under-statement risk는 당기 증가(매입활동)로 측정.
    increase: float = 0.0   # 당기 증가 (차변누계 / 매입발생)
    decrease: float = 0.0   # 당기 감소 (대변누계 / 결제)
    business_no: str = ""   # 사업자번호 (회신서 연계용)


@dataclass
class PartyBalance:
    name: str
    by_account: dict[str, float] = field(default_factory=dict)          # 그룹별 기말 잔액
    total: float = 0.0                                                   # 기말 잔액 합계
    activity: float = 0.0                                                # 당기 활동량 (ISA 505 완전성)
    by_account_activity: dict[str, float] = field(default_factory=dict) # 그룹별 당기 활동량

    def add(self, group: str, amount: float) -> None:
        """기말 잔액 누적."""
        self.by_account[group] = self.by_account.get(group, 0.0) + amount
        self.total += amount

    def add_activity(self, group: str, amount: float) -> None:
        """당기 활동량 누적 — |기초| + |증감|.

        채무 완전성 검토의 핵심 지표: 기말 잔액이 작더라도
        당기 매입활동(activity)이 크면 under-statement risk 존재.
        (ISA 505 / ISA 330·530 완전성 지향 sampling 근거)
        """
        self.by_account_activity[group] = self.by_account_activity.get(group, 0.0) + amount
        self.activity += amount


def load_ledger_rows(
    df: pd.DataFrame,
    kind: str = "receivable",
    col_map: dict[str, int | None] | None = None,
    account_name_override: str | None = None,
) -> list[LedgerRow]:
    """거래처별 원장 DataFrame → LedgerRow 리스트

    col_map: detect_ledger_columns() 결과 dict.
             None이면 7620 기본 컬럼 순서(0~7)를 사용 — 하위 호환.
    account_name_override: 다중 시트 방식에서 시트명 = 계정과목명으로 주입.
                           None이면 col_map["account_name"] 에서 읽음.

    7620 기본 컬럼 순서: 코드|명|계정과목|계정과목명|통화|기초|증감|기말
    코스맥스네오 컬럼 순서: 코드|거래처명|사업자번호|전기(월)이월|증가|감소|잔액|...
        → increase/decrease/business_no 컬럼을 col_map에서 읽어 LedgerRow에 주입.
        → account_name_override 로 계정과목명(시트명) 주입.
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

    # 신규 필드 인덱스 (없으면 None)
    increase_idx: int | None = col_map.get("increase") if col_map else None
    decrease_idx: int | None = col_map.get("decrease") if col_map else None
    bizno_idx: int | None = col_map.get("business_no") if col_map else None

    def _safe_float(series_row, idx: int | None) -> float:
        if idx is None:
            return 0.0
        v = series_row.iloc[idx]
        if pd.isna(v):
            return 0.0
        try:
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    rows: list[LedgerRow] = []
    for _, r in df.iterrows():
        name = str(r.iloc[m["name_col"]]) if pd.notna(r.iloc[m["name_col"]]) else ""
        if not name.strip():
            continue
        # 집계 행("합계") 제외
        if name.strip() in ("합계", "소계", "total", "subtotal"):
            continue
        code = str(r.iloc[m["code_col"]]) if pd.notna(r.iloc[m["code_col"]]) else ""
        acct_code = str(r.iloc[m["account_code"]]) if pd.notna(r.iloc[m["account_code"]]) else ""
        # 계정과목명: override(시트명 주입) 우선, 없으면 컬럼에서 읽기
        if account_name_override is not None:
            acct_name = account_name_override
        else:
            acct_name = str(r.iloc[m["account_name"]]) if pd.notna(r.iloc[m["account_name"]]) else ""
        ccy = str(r.iloc[m["currency"]]) if pd.notna(r.iloc[m["currency"]]) else "KRW"
        try:
            beg = float(r.iloc[m["beginning"]]) if pd.notna(r.iloc[m["beginning"]]) else 0.0
            chg = float(r.iloc[m["change"]]) if pd.notna(r.iloc[m["change"]]) else 0.0
            end = float(r.iloc[m["ending"]]) if pd.notna(r.iloc[m["ending"]]) else 0.0
        except (ValueError, TypeError):
            continue

        inc = _safe_float(r, increase_idx)
        dec = _safe_float(r, decrease_idx)
        bizno = ""
        if bizno_idx is not None:
            bv = r.iloc[bizno_idx]
            bizno = str(bv).strip() if pd.notna(bv) and str(bv).strip() not in ("nan", "None", "") else ""

        rows.append(LedgerRow(
            code=code, name=name, account_code=acct_code, account_name=acct_name,
            currency=ccy, beginning=beg, change=chg, ending=end,
            increase=inc, decrease=dec, business_no=bizno,
        ))
    return rows


def aggregate_by_party(
    rows: Iterable[LedgerRow],
    kind: str = "receivable",
    sign_normalize: bool = True,
) -> dict[str, PartyBalance]:
    """거래처별 그룹화.

    채무는 원장에서 음수로 적재되므로 sign_normalize=True 시 절대값화.

    활동량 계산 (ISA 505 완전성 검토용):
        우선순위 1 (증가 컬럼 존재 시): max(0, 증가 - |기말|) = paid-off 추정액.
                   증가 컸지만 기말 작음 → 결제 많음/일부 누락 의심 → metric 큼.
                   증가·기말 모두 큼 → 정상 거래(기말잔액 sample에서 포착) → metric 작음.
        우선순위 2 (순증감만 존재 시): |기초| + |change|.
    당기 매입활동이 활발하지만 기말 잔액이 작은 거래처(지급 완료 등)는
    단순 기말 잔액 sampling에서 누락되어 채무 under-statement risk를 놓칠 수 있다.
    activity 기준을 채무 MUS에 사용하면 이 risk를 포착한다.
    (ISA 330·530 / ISA 505 채무 완전성 원칙)
    """
    group_map = _load_account_group_map(kind)  # keys are normalized (lowercase)
    parties: dict[str, PartyBalance] = {}
    for r in rows:
        norm_acct = _normalize_account_name(r.account_name)
        group = group_map.get(norm_acct, r.account_name)

        # 기말 잔액 (채권: 실재성 기준 / 채무: 재무제표 대사용 기말 잔액)
        amt_ending = abs(r.ending) if sign_normalize else r.ending

        # ── 당기 활동량 결정 (ISA 505 채무 완전성) ────────────────────────────
        # under-statement risk = 매입 활발한데 기말 잔액 작은 거래처
        # 산식: max(0, 증가 - 기말)
        #   - 증가 컸지만 기말 작으면: 결제 많이 했거나 일부 누락 → metric 큼
        #   - 증가 크고 기말도 큰 거래처: 정상 거래 → metric 작음 (잔액 sample에서 이미 포착)
        if r.increase > 0:
            amt_activity = max(0.0, r.increase - abs(r.ending))
        else:
            amt_activity = abs(r.beginning) + abs(r.change)

        if r.name not in parties:
            parties[r.name] = PartyBalance(name=r.name)
        parties[r.name].add(group, amt_ending)
        parties[r.name].add_activity(group, amt_activity)
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
    balance: float               # sampling 기준값 (채권: 기말 잔액 / 채무: 당기 활동량)
    is_excluded: bool            # 발송제외
    is_related_party: bool       # 특관자
    is_key_item: bool            # Key item (balance ≥ 기준금액)
    is_representative: bool      # MUS 추출 표본
    final_sampled: bool          # 최종 샘플링 대상
    exclusion_reason: str = ""
    by_account: dict[str, float] = field(default_factory=dict)   # 계정그룹별 기말 잔액
    ending_balance: float = 0.0  # 기말 잔액 원본 (채무 조서 표기용)
    activity: float = 0.0        # 당기 활동량 (채무 완전성 검토, ISA 505)
    suspect_flag: bool = False   # 활동 크고 기말 소 — under-statement 의심 거래처


def classify_parties(
    parties: dict[str, PartyBalance],
    key_item_threshold: float,
    related_party_names: set[str],
    excluded_parties: dict[str, str] | None = None,   # {name: reason}
    kind: str = "receivable",
    suspect_activity_ratio: float = 1.5,
    suspect_ending_ratio: float = 0.1,
    performance_materiality: float = 0.0,
) -> list[PartyDecision]:
    """거래처 분류.

    채권(receivable): balance = 기말 잔액 — 실재성(over-statement risk) 검토.
    채무(payable):    balance = 당기 활동량(|기초|+|증감|) — 완전성(under-statement risk) 검토.
        ISA 505: 채무 조회는 기말 잔액 작아도 거래량 큰 거래처 포함.
        ISA 330/530: 매입 활동 클수록 누락 가능성 ↑ → activity 기반 MUS.

    suspect_flag: activity > PM × suspect_activity_ratio AND ending < PM × suspect_ending_ratio
        → 활동량 크지만 기말 잔액 소 — under-statement 의심 거래처 별도 표시.
    """
    excluded_parties = excluded_parties or {}
    is_payable = (kind == "payable")
    decisions: list[PartyDecision] = []
    for pb in parties.values():
        excl = pb.name in excluded_parties
        rp = _is_related_party(pb.name, related_party_names)

        # 채무: activity 기준 / 채권: 기말 잔액 기준
        sample_basis = pb.activity if is_payable else pb.total
        ki = (sample_basis >= key_item_threshold) and not excl

        # under-statement 의심 거래처 — 채무 전용
        suspect = False
        if is_payable and performance_materiality > 0:
            suspect = (
                pb.activity > performance_materiality * suspect_activity_ratio
                and pb.total < performance_materiality * suspect_ending_ratio
            )

        decisions.append(PartyDecision(
            name=pb.name,
            balance=sample_basis,        # MUS 기준값
            is_excluded=excl,
            is_related_party=rp,
            is_key_item=ki,
            is_representative=False,
            final_sampled=False,
            exclusion_reason=excluded_parties.get(pb.name, ""),
            by_account=dict(pb.by_account),
            ending_balance=pb.total,     # 기말 잔액 원본 보존
            activity=pb.activity,
            suspect_flag=suspect,
        ))
    decisions.sort(key=lambda d: d.name)
    return decisions


def _is_related_party(name: str, rp_set: set[str]) -> bool:
    """특관자 매칭 — exact normalize 또는 길이비 0.7 이상 substring 일치만.

    "코스맥스" 같은 prefix만 가지고 SK(주)·삼성웰스토리 등이 잘못 매칭되는 false positive 차단.
    """
    norm = _normalize(name)
    if not norm:
        return False
    for rp in rp_set:
        rp_norm = _normalize(rp)
        if not rp_norm:
            continue
        if rp_norm == norm:
            return True
        # substring 매칭은 길이비 0.7 이상 + 짧은 쪽이 5자 이상일 때만
        short, long = (rp_norm, norm) if len(rp_norm) < len(norm) else (norm, rp_norm)
        if len(short) >= 5 and len(short) / len(long) >= 0.7 and short in long:
            return True
    return False


def _normalize(s: str) -> str:
    """거래처명 정규화 — 괄호 별명·법인 접미사·구두점·공백 제거."""
    import re as _re
    # 1) 괄호 내 내용 통째로 제거 ("씨엠테크 주식회사 (CMTech Co.,Ltd)" → "씨엠테크 주식회사")
    s = _re.sub(r"\s*[\(（][^)）]*[\)）]\s*", "", s)
    # 2) 영문 법인 접미사 (대소문자 무관)
    s = _re.sub(r"\bCo\.?,?\s*Ltd\.?|\bInc\.?|\bCorp\.?|\bLLC\.?|\bLLP\.?|\bCorporation|\bCompany|\bLimited|\bSdn\.?\s*Bhd\.?|\bPty\.?\s*Ltd\.?", "", s, flags=_re.IGNORECASE)
    # 3) 공백·구두점·한국 법인 접미사 제거
    return (
        s.replace(" ", "")
        .replace(",", "")
        .replace(".", "")
        .replace("㈜", "")
        .replace("(주)", "")
        .replace("주식회사", "")
        .replace("유한회사", "")
        .upper()
    )
