"""프로젝트 E2E 통합 테스트

플로우: 신규 프로젝트 생성 → 파일 업로드 (7620 원장) → 샘플링 실행 →
        DB 저장 확인 → 프로젝트 재조회 (재기동 시뮬레이션)

실제 회사자료 파일을 사용하므로 input/회사자료/ 경로 필요.
파일 없으면 skip.
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

LEDGER_PATH = ROOT / "input" / "회사자료" / "채권채무조회서 거래처별 원장.XLSX"
WORKPAPER_PATH = ROOT / "input" / "조서" / "7620_코스맥스비티아이_C100_AA100 채권 채무 조회_FY25.xlsx"


@pytest.fixture
def app_client(tmp_path):
    """Flask 테스트 클라이언트 — 독립 SQLite DB 사용."""
    import os
    # 테스트용 DB 경로 override
    os.environ["CC_TEST_DB"] = str(tmp_path / "test.db")

    import importlib
    import api.app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    app_module.app.config["UPLOAD_DIR"] = str(tmp_path)

    with app_module.app.test_client() as c:
        yield c, app_module

    if "CC_TEST_DB" in os.environ:
        del os.environ["CC_TEST_DB"]


@pytest.mark.skipif(not LEDGER_PATH.exists(), reason="회사자료 없음 — 로컬 전용")
def test_full_project_flow():
    """실제 7620 파일로 전체 플로우 검증."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.infrastructure.persistence.models import Base
    from src.infrastructure.persistence.repos import ProjectRepository, WorkpaperRepository
    from src.infrastructure.loaders import load_related_parties
    from src.orchestrator import SamplingParams, run_sampling

    import pandas as pd

    # 1. 독립 DB 준비
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as s:
        # 2. 프로젝트 생성
        proj_repo = ProjectRepository(s)
        proj = proj_repo.create(
            company_name="코스맥스비티아이",
            period_end="2025-12-31",
            kind="receivable",
            created_by_email="tester@firm.com",
        )
        s.flush()
        assert proj.id is not None

        # 3. 워크페이퍼 생성
        wp_repo = WorkpaperRepository(s)
        wp = wp_repo.get_or_create(proj.id, "receivable")
        s.flush()

        # 4. 샘플링 실행
        df = pd.read_excel(LEDGER_PATH, sheet_name="채권")
        rp = load_related_parties(WORKPAPER_PATH)

        params = SamplingParams(
            company_name="코스맥스비티아이",
            period_end=date(2025, 12, 31),
            kind="receivable",
            performance_materiality=2_738_000_000,
            risk_level="유의적위험",
            control_reliance="Y",
            key_item_ratio_override=0.75,
            confidence_factor_override=1.4,
            excluded_parties={"helloBiome safe": "채권성격 아님"},
            related_parties=rp,
            force_include_related=True,
            random_seed=42,
        )
        result = run_sampling(df, params)

        # 5. 결과 DB 저장
        wp_repo.save_sampling_result(
            wp.id,
            params_dict={"kind": "receivable"},
            result_dict={"final_sample_size": result.size_result.final_sample_size},
        )
        s.commit()

        # 6. 재기동 시뮬레이션 — 새 세션에서 재조회
    with Session() as s2:
        proj2 = ProjectRepository(s2).get(proj.id)
        assert proj2 is not None
        assert proj2.company_name == "코스맥스비티아이"
        wps = proj2.workpapers
        assert len(wps) >= 1
        assert wps[0].step1_completed_at is not None

    # 7. 핵심 값 확인 (E2E는 FS 금액 미제공 → final_sample_size 다름)
    # Key item 기준금액은 PM × 0.75 = 2,053,500,000 고정
    assert result.size_result.key_item_threshold == pytest.approx(2_053_500_000, rel=1e-9)
    # 샘플링 실행 자체가 성공적으로 완료됨
    assert result.size_result.final_sample_size >= 1


@pytest.mark.skipif(not LEDGER_PATH.exists(), reason="회사자료 없음 — 로컬 전용")
def test_schema_detect_on_real_file():
    """실제 7620 파일에서 시트명·컬럼 자동 감지 검증."""
    import openpyxl
    import pandas as pd
    from src.infrastructure.schemas.ledger_schema import detect_ledger_sheets, detect_ledger_columns

    wb = openpyxl.load_workbook(LEDGER_PATH, read_only=True, data_only=True)
    sheets = detect_ledger_sheets(wb.sheetnames)
    assert sheets["receivable"] is not None, "채권 시트 감지 실패"

    df = pd.read_excel(LEDGER_PATH, sheet_name=sheets["receivable"])
    col_map = detect_ledger_columns(df)
    # 핵심 컬럼 4종 이상 감지
    detected = sum(1 for v in col_map.values() if v is not None)
    assert detected >= 4, f"컬럼 감지 부족: {col_map}"
