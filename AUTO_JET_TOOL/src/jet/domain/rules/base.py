"""룰 추상 베이스 클래스 및 실행 컨텍스트.

모든 JET 룰은 Rule(ABC)을 상속하며, apply() / configure() 두 메서드를 구현한다.
Strategy 패턴으로 설계되어 있어 룰 추가 시 기존 코드를 수정하지 않는다(OCP).

Plugin Discovery:
    Rule의 __init_subclass__가 하위 클래스를 자동으로 _registry에 등록한다.
    RuleRegistry가 이 레지스트리를 읽어 룰 인스턴스를 조립한다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, ClassVar, Iterable

from jet.domain.entities.journal_entry import JournalEntry
from jet.domain.entities.rule_result import RuleResult
from jet.domain.exceptions import RuleConfigurationError

if TYPE_CHECKING:
    from jet.infrastructure.io.coa_loader import AccountMaster
    from jet.infrastructure.io.doc_type_loader import DocTypeMaster
    from jet.infrastructure.io.hr_loader import HRMaster
    from jet.infrastructure.io.tb_loader import TrialBalance

logger = logging.getLogger(__name__)


@dataclass
class RuleContext:
    """룰 실행에 필요한 감사 컨텍스트.

    회계기간, 중요성 금액(PM), 공휴일 캘린더 등 룰 외부에서 주입되는 정보를 담는다.
    모든 룰이 공통으로 참조하므로 인자 목록을 간결하게 유지해준다.

    Attributes:
        period_start: 감사 대상 회계기간 시작일
        period_end: 감사 대상 회계기간 종료일 (결산일)
        performance_materiality: 수행중요성 금액(원 단위); None이면 대형금액 룰 비활성
        holiday_calendar: 공휴일 판정기 (IHolidayCalendar 구현체); None이면 R02 비활성
        coa_master: 계정과목 마스터 (B01~B04, A03에서 사용)
        doc_type_master: 전표유형 마스터 (B08에서 사용)
        hr_master: HR 인사 마스터 (B05에서 사용)
        tb_master: 합계잔액시산표 당기 (A03, B03에서 사용)
        tb_master_prior: 합계잔액시산표 전기 (B03 신규계정 fallback 용도).
            COA created_date가 없을 때 전기 TB와 비교하여 신규계정을 식별한다.
            None이면 B03 TB-비교 fallback 비활성.
        extra: 룰별 추가 컨텍스트 (확장 예약)
    """

    period_start: date
    period_end: date
    performance_materiality: float | None = None
    holiday_calendar: object | None = None  # IHolidayCalendar — 순환 참조 방지
    coa_master: "dict[str, AccountMaster] | None" = None
    doc_type_master: "dict[str, DocTypeMaster] | None" = None
    hr_master: "HRMaster | None" = None
    tb_master: "dict[str, TrialBalance] | None" = None
    tb_master_prior: "dict[str, TrialBalance] | None" = None
    extra: dict = field(default_factory=dict)


class Rule(ABC):
    """JET 룰 전략(Strategy) 추상 베이스.

    하위 클래스 정의만으로 플러그인 등록이 일어난다(__init_subclass__).
    RuleRegistry가 _registry를 통해 등록된 룰 목록을 읽는다.

    Class Variables:
        code: 룰 코드 (예: 'R01') — 하위 클래스에서 반드시 재정의
        name: 룰 명칭 (예: 'PeriodEndProximity') — 하위 클래스에서 반드시 재정의
        version: 룰 버전 (기본 '1.0.0') — 보고서 재현성용
        severity: 기본 위험도 1~5 — 하위 클래스에서 반드시 재정의
    """

    code: ClassVar[str] = ""
    name: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    severity: ClassVar[int] = 3

    # Plugin 레지스트리: {code: 클래스}
    _registry: ClassVar[dict[str, type["Rule"]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        """하위 클래스가 정의될 때 자동으로 레지스트리에 등록."""
        super().__init_subclass__(**kwargs)
        if cls.code:
            Rule._registry[cls.code] = cls
            logger.debug("룰 등록: %s (%s)", cls.code, cls.name)

    @abstractmethod
    def apply(
        self,
        entries: Iterable[JournalEntry],
        context: RuleContext,
    ) -> RuleResult:
        """분개 목록에 룰을 적용하고 결과를 반환한다.

        Args:
            entries: 정규화된 분개 목록
            context: 감사 실행 컨텍스트 (회계기간, PM 등)

        Returns:
            이 룰의 탐지 결과 (Finding 목록 포함)
        """

    @abstractmethod
    def configure(self, params: dict) -> None:
        """YAML에서 로드된 파라미터로 룰을 초기화한다.

        Args:
            params: 룰별 파라미터 딕셔너리

        Raises:
            RuleConfigurationError: 파라미터가 룰의 불변식을 위반할 때
        """

    def _make_result(
        self,
        executed_at: datetime,
        total_evaluated: int,
        findings: list,
        params: dict,
    ) -> RuleResult:
        """RuleResult 생성 헬퍼 — 반복 코드 제거용."""
        return RuleResult(
            rule_code=self.code,
            rule_name=self.name,
            rule_version=self.version,
            severity=self.severity,
            params=params,
            executed_at=executed_at,
            total_entries_evaluated=total_evaluated,
            findings=findings,
        )

    @classmethod
    def get_registry(cls) -> dict[str, type["Rule"]]:
        """등록된 룰 클래스 딕셔너리를 반환한다."""
        return dict(cls._registry)

    def _validate_positive(self, value: float | int, param_name: str) -> None:
        """파라미터가 양수인지 검증하는 공통 헬퍼."""
        if value <= 0:
            raise RuleConfigurationError(
                f"{self.code} {param_name}은 양수여야 합니다: {value}"
            )
