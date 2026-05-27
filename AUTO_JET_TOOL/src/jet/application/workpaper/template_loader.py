"""TemplateLoader — 회사별 감사조서 YAML 템플릿 로딩.

templates/workpapers/*.yaml 파일을 읽어 WorkpaperSpec을 생성한다.
회사별 조서 구성 변경은 코드 수정 없이 YAML만 수정하면 된다(OCP).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml

from jet.application.workpaper.workpaper_spec import ScenarioSpec, WorkpaperSpec

logger = logging.getLogger(__name__)


class TemplateLoader:
    """YAML 파일에서 WorkpaperSpec을 로드하는 Adapter.

    YAML 형식:
        company: "{회사명}"
        period_end: "YYYY-MM-DD"
        preparer: "{작성자}"
        reviewer: "{검토자}"
        prepared_date: "YYYY-MM-DD"    # 없으면 오늘 날짜 자동 사용
        reviewed_date: "YYYY-MM-DD"    # 없으면 오늘 날짜 자동 사용
        workpaper_code: "7400"
        title: "{조서 제목}"
        scenarios:
          - code: A01
            name: "Data Integrity Test"
            objective: "..."
            rule: A01_DataIntegrity
            enabled: true
    """

    def load(self, path: Path) -> WorkpaperSpec:
        """YAML 파일을 읽어 WorkpaperSpec 을 반환한다.

        Args:
            path: 템플릿 YAML 파일 경로

        Returns:
            WorkpaperSpec 인스턴스

        Raises:
            FileNotFoundError: 파일이 없을 때
            ValueError: 필수 키가 누락되었을 때
        """
        if not path.exists():
            raise FileNotFoundError(f"조서 템플릿 파일을 찾을 수 없습니다: {path}")

        logger.info("조서 템플릿 로드: %s", path)
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        self._validate(data, path)

        today = date.today().isoformat()
        scenarios = tuple(
            ScenarioSpec(
                code=str(s["code"]),
                name=str(s["name"]),
                objective=str(s.get("objective", "")),
                rule=s.get("rule"),
                enabled=bool(s.get("enabled", False)),
                params=dict(s.get("params", {})) if s.get("params") else {},
            )
            for s in data.get("scenarios", [])
        )

        # q01_sampling 옵션 로드 (없으면 빈 dict — 기능 비활성)
        q01_sampling_raw = data.get("q01_sampling", {}) or {}
        q01_sampling: dict = {
            "enabled": bool(q01_sampling_raw.get("enabled", False)),
            "method": str(q01_sampling_raw.get("method", "mus")),
            "n_per_rule": int(q01_sampling_raw.get("n_per_rule", 50)),
            "seed": int(q01_sampling_raw.get("seed", 42)),
        }

        # equity_adjustments 옵션 로드 (없으면 빈 dict — 보정 없음)
        equity_adj_raw = data.get("equity_adjustments", {}) or {}
        equity_adjustments: dict[str, float] = {
            str(k): float(v) for k, v in equity_adj_raw.items()
        }

        spec = WorkpaperSpec(
            company=str(data["company"]),
            period_end=str(data["period_end"]),
            preparer=str(data["preparer"]),
            reviewer=str(data["reviewer"]),
            prepared_date=str(data.get("prepared_date", today)),
            reviewed_date=str(data.get("reviewed_date", today)),
            workpaper_code=str(data["workpaper_code"]),
            title=str(data["title"]),
            scenarios=scenarios,
            master_files=dict(data.get("master_files", {})),
            q01_sampling=q01_sampling,
            equity_adjustments=equity_adjustments,
        )
        logger.info(
            "조서 스펙 로드 완료: %s / 시나리오 %d종 (활성 %d종)",
            spec.company,
            len(scenarios),
            len(spec.enabled_scenarios),
        )
        return spec

    @staticmethod
    def _validate(data: dict, path: Path) -> None:
        """필수 키 존재 여부를 검증한다."""
        required_keys = [
            "company", "period_end", "preparer", "reviewer",
            "workpaper_code", "title",
        ]
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise ValueError(
                f"조서 템플릿 필수 키 누락 ({path}): {missing}"
            )
