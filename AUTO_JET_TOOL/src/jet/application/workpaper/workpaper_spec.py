"""WorkpaperSpec — 회사별 감사조서 스펙 정의.

감사조서를 생성하는 데 필요한 회사 정보, 결산 정보,
시나리오 목록 등을 담는 불변 데이터 구조.

ExcelReporter가 이 스펙을 받아 조서 Excel을 생성한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScenarioSpec:
    """JET 시나리오(룰) 하나의 스펙.

    Attributes:
        code: 시나리오 코드 (예: 'A01', 'B01')
        name: 시나리오 영문명 (예: 'Data Integrity Test')
        objective: 목적 설명 (한국어)
        rule: 매핑된 룰 클래스 코드 (None이면 placeholder)
        enabled: 이번 실행에서 수행 여부
        params: 룰별 파라미터 딕셔너리 (YAML params 키에서 로드)
        result_summary: 수행 결과 요약 (자동 채움; 기본 빈 문자열)
    """

    code: str
    name: str
    objective: str
    rule: str | None
    enabled: bool
    params: dict = field(default_factory=dict)
    result_summary: str = ""


@dataclass(frozen=True)
class WorkpaperSpec:
    """감사조서 생성에 필요한 전체 스펙.

    Attributes:
        company: 회사명
        period_end: 결산일 (예: '2025-12-31')
        preparer: 작성자명
        reviewer: 검토자명
        prepared_date: 작성일 (예: '2026-03-03')
        reviewed_date: 검토일 (예: '2026-03-06')
        workpaper_code: 조서 코드 (예: '7400')
        title: 조서 제목 (예: '정보시스템조직의 회계관리 입출력')
        scenarios: 시나리오 목록
        master_files: 마스터 파일 기본 경로 딕셔너리 (hr/coa/tb/doctype)
    """

    company: str
    period_end: str
    preparer: str
    reviewer: str
    prepared_date: str
    reviewed_date: str
    workpaper_code: str
    title: str
    scenarios: tuple[ScenarioSpec, ...] = field(default_factory=tuple)
    master_files: dict = field(default_factory=dict)
    # Q01 표본추출 옵션: enabled, method(mus/random/systematic), n_per_rule, seed
    q01_sampling: dict = field(default_factory=dict)
    # 자본 결산이체 보정: {계정코드: 보정금액(signed)}
    equity_adjustments: dict = field(default_factory=dict)

    @property
    def enabled_scenarios(self) -> list[ScenarioSpec]:
        """수행 대상 시나리오만 반환한다."""
        return [s for s in self.scenarios if s.enabled]

    @property
    def disabled_scenarios(self) -> list[ScenarioSpec]:
        """이번 실행에서 제외된 시나리오를 반환한다."""
        return [s for s in self.scenarios if not s.enabled]
