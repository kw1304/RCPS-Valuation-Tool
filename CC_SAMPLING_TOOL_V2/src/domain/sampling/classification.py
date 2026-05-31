"""KEY / RP / BAD / EXCLUDED 분류.

설계서 5.4. 우선순위:
EXCLUDED_NONPARTY > EXCLUDED_BAD > EXCLUDED_ZERO > FORCED_RP > FORCED_KEY > REP.
"""
from __future__ import annotations
from src.domain.entities import Account, SelectionReason
from src.domain.allowance import is_fully_provisioned


# 외부조회 대상 아닌 항목 — 거래처명 전체가 keyword와 정확/거의 일치해야 제외.
# 부분 포함만 검사 시 정상 거래처 false positive 위험 (예: '한국수수료서비스').
# 짧은 keyword는 단독 사용되는 정형 항목이라 전체 일치 안전.
# 정확 일치 — 거래처명 = keyword 그 자체일 때만 제외
_NON_PARTY_EXACT = {
    "급여", "급여대장", "인건비", "사업소득", "퇴직금", "복리후생",
    "세무서", "국세청", "관세청", "지방세",
    "예수금", "원천세", "부가세", "4대보험",
    "기타거래처", "기타", "미정",
    "공공요금", "전기요금", "수도요금", "가스요금", "통신요금",
    "임직원", "법인카드", "잡손실", "잡지급금", "잡수수료",
}

# Prefix 매칭 — keyword로 시작하는 거래처명 모두 제외
# 예: 건강보험 → 건강보험공단, 건강보험심사평가원
_NON_PARTY_PREFIX = (
    "건강보험", "국민연금", "고용보험", "산재보험",
    "법인세", "부가가치세", "소득세", "재산세", "원천세",
)

# Suffix 매칭 — keyword로 끝나는 거래처명
# 예: 부평세무서, 강남세무서.
# 본사/지사/지점/사무소 제거: 실거래처(예 '○○산업 광주지사', 해외 '도쿄지점',
# '김앤장법률사무소')를 false-exclude → 채권채무 누락. 지점은 별도 entity로 유지.
# 세무서만 명백한 비거래 행정기관이라 안전.
_NON_PARTY_SUFFIX = (
    "세무서",
)


def _is_non_party(name: str) -> bool:
    if not name:
        return False
    import re
    n = re.sub(r"[\s\+\-_.,()/&·㈜]+", "", name).strip()
    if not n:
        return False
    if n in _NON_PARTY_EXACT:
        return True
    if any(n.startswith(p) for p in _NON_PARTY_PREFIX):
        return True
    # suffix는 짧은 이름만 (긴 거래처명에 우연히 포함 case 방지)
    if len(n) <= 12 and any(n.endswith(s) for s in _NON_PARTY_SUFFIX):
        return True
    return False


def classify_population(
    accounts: list[Account],
    key_threshold: float,
    self_name: str = "",
    kind: str = "AR",
) -> tuple[
    list[tuple[Account, SelectionReason]],
    list[tuple[Account, SelectionReason]],
    list[Account],
]:
    """모집단을 강제포함·제외·잔여로 분류.

    Args:
        accounts: 분류 대상.
        key_threshold: |잔액| ≥ threshold면 KEY로 강제포함.
        self_name: 자기 회사명 (project.client). 거래처에 자기 회사 매칭되면
                    self-deal로 제외 (외부조회 대상 X).

    Returns:
        (forced, excluded, remaining).
        forced·excluded는 (account, reason) 페어. remaining은 raw Account.
    """
    from src.domain.party_normalize import (
        normalize_party_name, load_default_synonyms,
    )
    synonym_map = load_default_synonyms()
    self_norm = ""
    if self_name:
        n = normalize_party_name(self_name)
        self_norm = synonym_map.get(n, n)

    forced: list[tuple[Account, SelectionReason]] = []
    excluded: list[tuple[Account, SelectionReason]] = []
    remaining: list[Account] = []

    for acc in accounts:
        # 자기 회사 self-deal 제외
        if self_norm and acc.name:
            n = normalize_party_name(acc.name)
            acc_canon = synonym_map.get(n, n)
            if acc_canon == self_norm:
                excluded.append((acc, SelectionReason.EXCLUDED_ZERO))
                continue
        # 거래처 아닌 항목 (급여·세무서·예수금 등) 자동 제외
        if _is_non_party(acc.name):
            excluded.append((acc, SelectionReason.EXCLUDED_ZERO))
            continue
        if is_fully_provisioned(acc):
            excluded.append((acc, SelectionReason.EXCLUDED_BAD))
            continue
        if abs(acc.balance_krw) < 1e-9:
            # AP(채무) 완전성 검토: 잔액 0이라도 당기 활동량 있으면 남김
            # (paid-off 처리됐으나 실제 채무 누락 의심 케이스).
            if kind == "AP" and (abs(acc.debit_amt) > 1e-9
                                  or abs(acc.credit_amt) > 1e-9):
                pass  # 잔액 0 + 활동량 있음 → REP 후보
            else:
                excluded.append((acc, SelectionReason.EXCLUDED_ZERO))
                continue
        if acc.is_related_party:
            forced.append((acc, SelectionReason.FORCED_RP))
            continue
        # KEY 강제포함 제거 — 잔액 큰 거래처는 PPS 가중 추출로 자연 선정.
        # 강제포함은 RP만 (사용자 명시).
        remaining.append(acc)

    return forced, excluded, remaining
