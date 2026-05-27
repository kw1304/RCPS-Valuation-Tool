"""B05 Unusual User — HR 비등록·퇴직 후 입력 사용자 분개 적출 룰.

두 가지 sub-check를 수행한다:
    (a) HR에 등록되지 않은 user_id로 입력된 분개
    (b) 퇴직 이후 전기일에 입력된 분개

SYSTEM-* 자동전표는 적출하되 "시스템 계정"으로 별도 표시한다.

전제:
    RuleContext.hr_master가 주입되어 있어야 한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from jet.domain.entities.journal_entry import JournalEntry
from jet.domain.entities.rule_result import Finding, RuleResult
from jet.domain.exceptions import RuleConfigurationError
from jet.domain.rules.base import Rule, RuleContext

logger = logging.getLogger(__name__)

# sub-check 분류
_REASON_NOT_REGISTERED = "HR 미등록"
_REASON_POST_RETIREMENT = "퇴직 후 입력"
_REASON_SYSTEM = "시스템 계정"
_REASON_AFFILIATE = "그룹사 사번"
_REASON_EXTERNAL = "외부/계약직"

# ── 시스템·인터페이스 ID 기본 패턴 ─────────────────────────────────────────────
# 우선순위: 시스템 > 외부/계약직 > 그룹사 > 퇴직후 > 미등록
#
# SAP 표준 운영 ID (정답조서 B05_OK R11~R13 참조):
#   CEP_PO, CEP_BATCH (인터페이스/배치), FF_* (firefighter 긴급작업),
#   BATCH_*, SYSTEM_*, RFC_*, SAP_*, GRC_*, WF_* 등
#
# 한국 ERP 일반 시스템 계정:
#   Z접두사 (^Z[0-9A-Z]+$): SAP에서 Z로 시작하는 ID는 배치/시스템 계정 관행.
#     예: Z001, ZBATCH, ZINTERFACE 등 Z-prefix 커스텀 배치 계정.
#   ^SYSTEM-: SAP 자동전기 시스템 계정 (기존 하드코딩 패턴을 정규식으로 통일)
#   ^BATCH: 배치 처리 계정 (BATCH_ 포함)
#   ^AUTO: 자동전기 계정 (자동결산, 자동환산 등)
_DEFAULT_SYSTEM_USER_PATTERNS: tuple[str, ...] = (
    r"^CEP_",
    r"^FF_",
    r"^BATCH",
    r"^SYSTEM[_-]",
    r"^RFC_",
    r"^SAP_",
    r"^GRC_",
    r"^WF[_-]",
    r"^AUTO",
    r"^Z[0-9A-Z]+$",    # Z접두사 배치·시스템 계정 (SAP 한국 ERP 관행)
    r"^GLOBAL",         # 글로벌 통합 시스템 계정
    r"^OUTSOURCING",    # 아웃소싱 처리 계정
    r"^I[A-Z]",         # 인터페이스/IT 접두사 (IF_, IT_, INTERFACE_ 등)
    r"^9\d{4}$",        # 9로 시작하는 5자리 — 일부 회사 임시·외부 시스템 계정
)

# ── 외부/계약직 사번 기본 패턴 ──────────────────────────────────────────────────
# 한국 기업에서 파견·계약직에 부여하는 사번 패턴:
#   알파벳 접미사 (C, X 등): 사번 마지막이 알파벳으로 끝나는 경우
#   계약직(C), 파견직(X) 등 회사마다 다르나 알파벳 접미사가 공통 패턴.
#   예: 1234567C (계약직), 9876543X (파견직)
#   단, 시스템 계정(Z접두사 등)과 중복되지 않도록 Z접두사는 제외.
_DEFAULT_EXTERNAL_USER_PATTERNS: tuple[str, ...] = (
    r"[A-Z]$",  # 사번 끝이 알파벳 — 파견·계약직 일반 패턴
)


@dataclass
class UnusualUserFinding:
    """B05 비정상 사용자 분개 상세.

    Attributes:
        entry_no: 전표번호
        entry_date: 전기일
        posting_date: 입력일
        user_id: 작성자ID
        reason: 분류 (HR 미등록 / 퇴직 후 입력 / 시스템 계정 / 그룹사 사번)
        retire_date: 퇴직일 (해당하는 경우)
        days_after_retirement: 퇴직 후 경과일수 (해당하는 경우)
        debit_amount: 차변금액
        credit_amount: 대변금액
        user_name: 작성자 성명 (HR 마스터에서 조회, 없으면 빈 문자열)
        detail_type: 세부유형 (시스템 계정 한글명 / 그룹사 prefix / 퇴직·미등록은 빈 문자열)
    """

    entry_no: str
    entry_date: datetime
    posting_date: datetime | None
    user_id: str
    reason: str
    retire_date: date | None
    days_after_retirement: int | None
    debit_amount: float
    credit_amount: float
    user_name: str = ""
    detail_type: str = ""


class B05UnusualUser(Rule):
    """B05 Unusual User.

    HR 인사 마스터와 분개 작성자를 비교하여
    미등록 사용자 및 퇴직 후 입력 분개를 적출한다.
    """

    code = "B05"
    name = "UnusualUser"
    version = "1.1.0"
    severity = 5

    def __init__(self) -> None:
        self._system_patterns: list[re.Pattern] = [
            re.compile(p) for p in _DEFAULT_SYSTEM_USER_PATTERNS
        ]
        self._external_patterns: list[re.Pattern] = [
            re.compile(p) for p in _DEFAULT_EXTERNAL_USER_PATTERNS
        ]
        self._affiliate_patterns: list[re.Pattern] = []

    def configure(self, params: dict) -> None:
        """파라미터 초기화.

        Args:
            params:
                system_user_patterns: 시스템·인터페이스 ID 정규식 목록.
                    HR 미등록이지만 정상 운영성 ID로 분류 (예: ['^CEP_', '^FF_']).
                    지정 시 기본값 전체를 대체한다.
                external_user_patterns: 외부/계약직 사번 정규식 목록.
                    HR 미등록이지만 파견·계약직 패턴으로 분류 (예: ['[A-Z]$']).
                    지정 시 기본값 전체를 대체한다.
                affiliate_user_patterns: 그룹사 사번 정규식 목록.
                    HR 미등록이지만 동일 그룹 계열사 사번으로 분류 (예: ['^12[0-9]{7}$']).
                    기본값은 빈 목록 (정답조서가 그룹사 매핑까지 요구할 때 명시 주입).
        """
        sys_pats = params.get("system_user_patterns")
        if sys_pats is not None:
            if not isinstance(sys_pats, list):
                raise RuleConfigurationError(
                    f"B05 system_user_patterns는 list여야 합니다: {sys_pats}"
                )
            self._system_patterns = [re.compile(str(p)) for p in sys_pats]

        ext_pats = params.get("external_user_patterns")
        if ext_pats is not None:
            if not isinstance(ext_pats, list):
                raise RuleConfigurationError(
                    f"B05 external_user_patterns는 list여야 합니다: {ext_pats}"
                )
            self._external_patterns = [re.compile(str(p)) for p in ext_pats]

        aff_pats = params.get("affiliate_user_patterns")
        if aff_pats is not None:
            if not isinstance(aff_pats, list):
                raise RuleConfigurationError(
                    f"B05 affiliate_user_patterns는 list여야 합니다: {aff_pats}"
                )
            self._affiliate_patterns = [re.compile(str(p)) for p in aff_pats]

    def _is_system_user(self, uid: str) -> bool:
        """시스템·인터페이스 ID 여부를 정규식으로 판정한다."""
        if uid.startswith("SYSTEM-"):
            return True
        return any(p.match(uid) for p in self._system_patterns)

    def _is_external_user(self, uid: str) -> bool:
        """외부/계약직 사번 여부를 정규식으로 판정한다."""
        return any(p.search(uid) for p in self._external_patterns)

    def _is_affiliate_user(self, uid: str) -> bool:
        """그룹사 사번 여부를 정규식으로 판정한다."""
        return any(p.match(uid) for p in self._affiliate_patterns)

    @staticmethod
    def _resolve_system_detail(uid: str, doc_type_master: "dict | None") -> str:
        """SYSTEM-XX 형태의 사번에서 XX prefix를 추출해 전표유형 한글명으로 변환한다.

        doc_type_master가 없거나 매핑이 없으면 "자동전기 (XX)" 형태로 반환한다.
        SYSTEM- 접두어가 없는 시스템 ID(CEP_*, FF_* 등)는 ID 자체를 반환한다.
        """
        if uid.startswith("SYSTEM-"):
            prefix = uid[len("SYSTEM-"):]
            if doc_type_master and prefix in doc_type_master:
                desc = getattr(doc_type_master[prefix], "description", None)
                if desc:
                    return desc
            return f"자동전기 ({prefix})" if prefix else "시스템 자동전기"
        # CEP_PO, FF_*, BATCH_* 등 — ID 자체가 식별자
        return uid

    @staticmethod
    def _resolve_affiliate_detail(uid: str) -> str:
        """그룹사 사번에서 앞 3자리 prefix를 추출해 세부유형 문자열을 반환한다."""
        prefix = uid[:3] if len(uid) >= 3 else uid
        return f"prefix {prefix}"

    def apply(
        self,
        entries: Iterable[JournalEntry],
        context: RuleContext,
    ) -> RuleResult:
        """비정상 사용자 분개를 적출한다."""
        started = datetime.now()
        all_entries = list(entries)

        if context.hr_master is None:
            logger.warning("B05: hr_master 미제공 — 룰 스킵")
            return self._make_result(started, 0, [], {"skipped": "hr_master_not_provided"})

        hr = context.hr_master
        doc_type_master = context.doc_type_master
        unusual: list[UnusualUserFinding] = []

        for e in all_entries:
            uid = e.user_id

            # 분류 우선순위: 시스템 > 외부/계약직 > HR등록(퇴직후) > 그룹사 > 미등록
            # 시스템 > 외부/계약직을 HR 조회 전에 먼저 처리하는 이유:
            #   시스템·외부 계정은 HR 마스터에 등록되지 않는 것이 정상이므로
            #   패턴 매칭 단계에서 조기 분류해야 "미등록" 오분류를 막는다.

            # 1) 시스템·인터페이스 자동전표
            #    (SYSTEM-*, CEP_*, FF_*, BATCH*, AUTO*, Z접두사 등)
            if self._is_system_user(uid):
                detail = self._resolve_system_detail(uid, doc_type_master)
                unusual.append(UnusualUserFinding(
                    entry_no=e.entry_no,
                    entry_date=e.entry_date,
                    posting_date=e.posting_date,
                    user_id=uid,
                    reason=_REASON_SYSTEM,
                    retire_date=None,
                    days_after_retirement=None,
                    debit_amount=float(e.debit_amount),
                    credit_amount=float(e.credit_amount),
                    user_name="",
                    detail_type=detail,
                ))
                continue

            # 2) 외부/계약직 — 알파벳 접미사 등 사번 패턴 (HR 등록 여부 불문)
            #    단, HR에 등록된 경우 HR 경로(퇴직후·재직)로 처리.
            if not hr.is_registered(uid) and self._is_external_user(uid):
                unusual.append(UnusualUserFinding(
                    entry_no=e.entry_no,
                    entry_date=e.entry_date,
                    posting_date=e.posting_date,
                    user_id=uid,
                    reason=_REASON_EXTERNAL,
                    retire_date=None,
                    days_after_retirement=None,
                    debit_amount=float(e.debit_amount),
                    credit_amount=float(e.credit_amount),
                    user_name="",
                    detail_type=self._resolve_external_detail(uid),
                ))
                continue

            # 3) HR 등록 사용자: 퇴직 후 입력 여부만 확인
            if hr.is_registered(uid):
                retire_date = hr.get_retirement_date(uid)
                if retire_date:
                    posting = (
                        e.entry_date.date() if e.posting_date is None
                        else e.posting_date.date()
                    )
                    if posting > retire_date:
                        days_after = (posting - retire_date).days
                        name = hr.get_name_by_id(uid) or ""
                        unusual.append(UnusualUserFinding(
                            entry_no=e.entry_no,
                            entry_date=e.entry_date,
                            posting_date=e.posting_date,
                            user_id=uid,
                            reason=_REASON_POST_RETIREMENT,
                            retire_date=retire_date,
                            days_after_retirement=days_after,
                            debit_amount=float(e.debit_amount),
                            credit_amount=float(e.credit_amount),
                            user_name=name,
                            detail_type="",
                        ))
                continue

            # 4) HR 미등록 — 그룹사 사번 패턴이면 별도 분류
            if self._is_affiliate_user(uid):
                detail = self._resolve_affiliate_detail(uid)
                unusual.append(UnusualUserFinding(
                    entry_no=e.entry_no,
                    entry_date=e.entry_date,
                    posting_date=e.posting_date,
                    user_id=uid,
                    reason=_REASON_AFFILIATE,
                    retire_date=None,
                    days_after_retirement=None,
                    debit_amount=float(e.debit_amount),
                    credit_amount=float(e.credit_amount),
                    user_name="",
                    detail_type=detail,
                ))
                continue

            # 5) HR 미등록 — 실제 검토 대상
            unusual.append(UnusualUserFinding(
                entry_no=e.entry_no,
                entry_date=e.entry_date,
                posting_date=e.posting_date,
                user_id=uid,
                reason=_REASON_NOT_REGISTERED,
                retire_date=None,
                days_after_retirement=None,
                debit_amount=float(e.debit_amount),
                credit_amount=float(e.credit_amount),
                user_name="",
                detail_type="",
            ))

        findings = [
            Finding(
                entry_no=f.entry_no,
                raw_row_index=-1,
                rule_code=self.code,
                rule_name=self.name,
                severity=self.severity,
                reason=self._build_reason(f),
                amount=Decimal(str(max(f.debit_amount, f.credit_amount))),
                entry_date=f.entry_date,
            )
            for f in unusual
        ]

        result = self._make_result(started, len(all_entries), findings, {})
        result.extra["unusual_findings"] = unusual

        # sub-check별 집계
        result.extra["not_registered_count"] = sum(
            1 for f in unusual if f.reason == _REASON_NOT_REGISTERED
        )
        result.extra["post_retirement_count"] = sum(
            1 for f in unusual if f.reason == _REASON_POST_RETIREMENT
        )
        result.extra["system_account_count"] = sum(
            1 for f in unusual if f.reason == _REASON_SYSTEM
        )
        result.extra["affiliate_count"] = sum(
            1 for f in unusual if f.reason == _REASON_AFFILIATE
        )
        result.extra["external_count"] = sum(
            1 for f in unusual if f.reason == _REASON_EXTERNAL
        )

        logger.info(
            "B05 완료: 총 %d건 (미등록 %d / 퇴직후 %d / 시스템 %d / 그룹사 %d / 외부계약직 %d)",
            len(unusual),
            result.extra["not_registered_count"],
            result.extra["post_retirement_count"],
            result.extra["system_account_count"],
            result.extra["affiliate_count"],
            result.extra["external_count"],
        )
        return result

    @staticmethod
    def _resolve_external_detail(uid: str) -> str:
        """외부/계약직 사번 세부유형 문자열을 반환한다."""
        suffix = uid[-1] if uid else ""
        if suffix.isalpha():
            return f"접미사 {suffix} (파견·계약직 패턴)"
        return "외부/계약직 패턴"

    @staticmethod
    def _build_reason(f: UnusualUserFinding) -> str:
        """Finding reason 문자열 생성."""
        if f.reason == _REASON_NOT_REGISTERED:
            return f"HR 미등록 사용자 입력: {f.user_id}"
        if f.reason == _REASON_POST_RETIREMENT:
            return (
                f"퇴직 후 입력: {f.user_id} (퇴직일 {f.retire_date}, "
                f"{f.days_after_retirement}일 후 기표)"
            )
        if f.reason == _REASON_AFFILIATE:
            return f"그룹사 사번 입력: {f.user_id}"
        if f.reason == _REASON_EXTERNAL:
            return f"외부/계약직 사번 입력: {f.user_id} ({f.detail_type})"
        return f"시스템 자동전표: {f.user_id}"
