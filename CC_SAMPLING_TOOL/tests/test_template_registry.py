"""Template Registry 단위 테스트 (Week 2)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from src.infrastructure.report.template_registry import (
    DEFAULT_TEMPLATE_ID,
    get_template,
    list_templates,
    reload_registry,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """각 테스트 전후 레지스트리 캐시 초기화."""
    reload_registry()
    yield
    reload_registry()


def test_list_templates_contains_woongkye_standard():
    """list_templates() 결과에 woongkye_standard 포함."""
    templates = list_templates()
    ids = [t.id for t in templates]
    assert DEFAULT_TEMPLATE_ID in ids, f"woongkye_standard 누락 — 현재: {ids}"


def test_list_templates_has_name_and_firm():
    """woongkye_standard 의 name, firm_name 비어있지 않음."""
    templates = {t.id: t for t in list_templates()}
    meta = templates[DEFAULT_TEMPLATE_ID]
    assert meta.name, "name 비어있음"
    assert meta.firm_name, "firm_name 비어있음"


def test_get_template_sheet_mapping():
    """get_template('woongkye_standard').sheet_mapping에 control 시트명 포함."""
    meta = get_template(DEFAULT_TEMPLATE_ID)
    sheet_map = meta.sheet_mapping
    assert "control" in sheet_map, "control 키 없음"
    # 실제 시트명에 'MUS' 또는 'control' 관련 문자열 포함
    assert sheet_map["control"], "control 시트명 비어있음"


def test_get_template_sheet_mapping_c100_control():
    """sheet_mapping['control'] 이 'C100 조회서 control sheet (MUS)' 임."""
    meta = get_template(DEFAULT_TEMPLATE_ID)
    assert "C100 조회서 control sheet (MUS)" in meta.sheet_mapping.values(), \
        f"C100 control sheet 미매핑 — 현재: {meta.sheet_mapping}"


def test_template_xlsx_exists():
    """templates/cc_template.xlsx 파일 실제 존재."""
    meta = get_template(DEFAULT_TEMPLATE_ID)
    assert meta.xlsx_path.exists(), f"템플릿 xlsx 없음: {meta.xlsx_path}"


def test_template_xlsx_has_expected_sheets():
    """cc_template.xlsx에 sheet_mapping 에 정의된 4개 시트 모두 존재."""
    import openpyxl
    meta = get_template(DEFAULT_TEMPLATE_ID)
    wb = openpyxl.load_workbook(meta.xlsx_path, read_only=True, data_only=True)
    wb_sheets = set(wb.sheetnames)
    wb.close()
    for logical, real in meta.sheet_mapping.items():
        assert real in wb_sheets, f"시트 미존재: {real} (논리명: {logical})"


def test_get_template_invalid_id_raises():
    """등록되지 않은 id 요청 시 KeyError 또는 기본 양식 폴백."""
    # 기본 양식이 있으면 폴백 반환, 없으면 KeyError — 두 경우 모두 허용
    # 단, 이 프로젝트에서는 woongkye_standard 가 존재하므로 폴백 반환이 기대됨
    try:
        meta = get_template("__nonexistent_id__")
        # 폴백 시 기본 양식 반환
        assert meta.id == DEFAULT_TEMPLATE_ID, "폴백이 기본 양식 아님"
    except KeyError:
        pass  # 기본 양식도 없는 경우 — 허용


def test_get_template_none_returns_default():
    """template_id=None 이면 기본 양식 반환."""
    meta = get_template(None)
    assert meta.id == DEFAULT_TEMPLATE_ID


def test_template_meta_column_anchors():
    """column_anchors_c100_2 에 receivable·payable 키 존재."""
    meta = get_template(DEFAULT_TEMPLATE_ID)
    assert "receivable" in meta.column_anchors_c100_2, "receivable 키 없음"
    assert "payable" in meta.column_anchors_c100_2, "payable 키 없음"
