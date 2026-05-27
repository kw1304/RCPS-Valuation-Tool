"""Template Registry — 조서 양식 메타데이터 시스템.

역할:
  - configs/templates/<id>.yaml 에서 양식 메타데이터 로드
  - 시트명·셀 앵커를 TemplateMeta 로 추상화하여 template_reporter 에 공급
  - 기본 양식 "woongkye_standard" → cc_template.xlsx (7620 회귀 PASS 유지)

설계 원칙:
  - 새 양식 추가 = YAML 파일 1개 신설만으로 완결 (코드 수정 불필요)
  - 양식별 셀 위치 하드코딩 → YAML 외부화 완료
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]   # CC_SAMPLING_TOOL/
_TEMPLATE_DIR = _ROOT / "configs" / "templates"

DEFAULT_TEMPLATE_ID = "woongkye_standard"


@dataclass
class TemplateMeta:
    """조서 양식 1건의 메타데이터.

    sheet_mapping: 논리명 → 실제 시트명 매핑
      - "control", "size", "key_item", "mus"
    cell_anchors: 헤더 셀 위치 (row, col)
    column_anchors_c100_2: 계정그룹 → 컬럼 번호 (채권/채무 구분)
    size_sheet_anchors / mus_sheet_anchors: 계산 셀 위치
    """

    id: str
    name: str
    firm_name: str
    template_xlsx_path: str          # ROOT 기준 상대 경로

    sheet_mapping: dict[str, str] = field(default_factory=dict)
    cell_anchors: dict[str, Any] = field(default_factory=dict)
    column_anchors_c100_2: dict[str, dict[str, int]] = field(default_factory=dict)
    party_matrix_start_row: int = 47
    size_sheet_anchors: dict[str, list[int]] = field(default_factory=dict)
    mus_sheet_anchors: dict[str, Any] = field(default_factory=dict)

    @property
    def xlsx_path(self) -> Path:
        """절대 경로 반환."""
        return _ROOT / self.template_xlsx_path

    def sheet(self, logical: str) -> str:
        """논리명 → 시트명. 없으면 logical 그대로 반환."""
        return self.sheet_mapping.get(logical, logical)

    def anchor(self, key: str) -> tuple[int, int]:
        """헤더 앵커 (row, col) 반환. 없으면 (1, 1)."""
        val = self.cell_anchors.get(key, [1, 1])
        return (int(val[0]), int(val[1]))

    def group_col(self, kind: str) -> dict[str, int]:
        """계정그룹 → 컬럼 매핑. kind: "receivable" | "payable"."""
        return self.column_anchors_c100_2.get(kind, {})

    def size_anchor(self, key: str) -> tuple[int, int]:
        """표본규모 시트 셀 위치."""
        val = self.size_sheet_anchors.get(key, [1, 1])
        return (int(val[0]), int(val[1]))

    def mus_anchor(self, key: str) -> Any:
        """MUS 시트 셀 위치 또는 int."""
        return self.mus_sheet_anchors.get(key)


def _load_from_yaml(path: Path) -> TemplateMeta:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return TemplateMeta(
        id=data["id"],
        name=data["name"],
        firm_name=data.get("firm_name", ""),
        template_xlsx_path=data["template_xlsx_path"],
        sheet_mapping=data.get("sheet_mapping", {}),
        cell_anchors=data.get("cell_anchors", {}),
        column_anchors_c100_2=data.get("column_anchors_c100_2", {}),
        party_matrix_start_row=data.get("party_matrix_start_row", 47),
        size_sheet_anchors=data.get("size_sheet_anchors", {}),
        mus_sheet_anchors=data.get("mus_sheet_anchors", {}),
    )


@lru_cache(maxsize=None)
def _registry() -> dict[str, TemplateMeta]:
    """YAML 파일 전체 로드 (프로세스당 1회 캐시)."""
    reg: dict[str, TemplateMeta] = {}
    if not _TEMPLATE_DIR.exists():
        return reg
    for yaml_path in sorted(_TEMPLATE_DIR.glob("*.yaml")):
        try:
            meta = _load_from_yaml(yaml_path)
            reg[meta.id] = meta
        except Exception as e:
            import logging
            logging.getLogger("cc_sampling").warning(f"Template 로드 실패 {yaml_path}: {e}")
    return reg


def list_templates() -> list[TemplateMeta]:
    """등록된 양식 목록 반환."""
    return list(_registry().values())


def get_template(template_id: str | None = None) -> TemplateMeta:
    """template_id 로 양식 조회. None 이면 기본 양식 반환.
    등록되지 않은 id 요청 시 기본 양식 폴백 (7620 회귀 보호).
    """
    tid = template_id or DEFAULT_TEMPLATE_ID
    reg = _registry()
    if tid in reg:
        return reg[tid]
    # 폴백: 기본 양식
    if DEFAULT_TEMPLATE_ID in reg:
        import logging
        logging.getLogger("cc_sampling").warning(
            f"Template '{tid}' 미등록 — '{DEFAULT_TEMPLATE_ID}' 폴백"
        )
        return reg[DEFAULT_TEMPLATE_ID]
    raise KeyError(f"Template '{tid}' 및 기본 양식을 찾을 수 없습니다.")


def reload_registry() -> None:
    """테스트용 — 캐시 초기화."""
    _registry.cache_clear()
