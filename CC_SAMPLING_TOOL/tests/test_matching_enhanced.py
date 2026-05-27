"""test_matching_enhanced — UploadGuide 동적 alias, 한자 자동 매칭, 파일명 CJK 매핑."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from src.domain.matching import match_party, reload_aliases


@pytest.fixture(autouse=True)
def reset_alias_cache():
    """각 테스트 전에 alias 캐시를 초기화하여 party_aliases.yaml 변경 반영."""
    reload_aliases()
    yield


# ── 기본 매칭 (기존 호환) ─────────────────────────────────────────────────────

def test_exact_match_basic():
    result = match_party("코스맥스㈜", ["코스맥스㈜", "삼성전자"])
    assert result.matched_name == "코스맥스㈜"
    assert result.confidence == 1.0


def test_alias_from_yaml_cosmax_china():
    """party_aliases.yaml — COSMAX CHINA → 科丝美诗（中国）化妆品有限公司."""
    candidates = ["科丝美诗（中国）化妆品有限公司", "코스맥스이스트㈜"]
    result = match_party("COSMAX CHINA", candidates)
    assert result.matched_name == "科丝美诗（中国）化妆品有限公司"
    assert result.method == "alias"


def test_alias_from_yaml_cosmax_guangzhou():
    candidates = ["科丝美诗(广州)化妆品有限公司", "과거거래처"]
    result = match_party("코스맥스 광저우", candidates)
    assert result.matched_name == "科丝美诗(广州)化妆品有限公司"
    assert result.method == "alias"


def test_alias_sanduk_kunda():
    """山东昆达 alias 매핑 검증."""
    candidates = ["山东昆达生物科技有限公司", "코스맥스㈜"]
    result = match_party("산둥쿤다", candidates)
    assert result.matched_name == "山东昆达生物科技有限公司"
    assert result.method == "alias"


def test_alias_sanduk_ruino():
    candidates = ["山东瑞诺生物科技有限公司", "기타거래처"]
    result = match_party("산둥루이눠", candidates)
    assert result.matched_name == "山东瑞诺生物科技有限公司"
    assert result.method == "alias"


# ── UploadGuide 동적 alias ────────────────────────────────────────────────────

def _make_upload_guide(name_list):
    """테스트용 UploadGuideData mock."""
    from src.infrastructure.loaders import UploadGuideData, PartyContact
    contacts = [PartyContact(name=n) for n in name_list]
    ug = UploadGuideData(send_targets=contacts)
    return ug


def test_upload_guide_dynamic_alias_exact():
    """UploadGuide에 있는 거래처명과 candidates가 동일할 때 동적 alias."""
    ug = _make_upload_guide(["코스맥스㈜", "삼성전자"])
    result = match_party("코스맥스㈜", ["코스맥스㈜", "현대자동차"], upload_guide_data=ug)
    assert result.matched_name == "코스맥스㈜"


def test_upload_guide_dynamic_alias_fuzzy():
    """UploadGuide 거래처명이 candidates와 fuzzy 매칭되면 alias로 연결."""
    ug = _make_upload_guide(["코스맥스비티아이"])
    result = match_party("코스맥스비티아이", ["코스맥스비티아이㈜", "삼성전자"], upload_guide_data=ug)
    # UploadGuide에 "코스맥스비티아이" 가 있고 candidates에 "코스맥스비티아이㈜" 가 있으면
    # fuzzy partial ≥ 90으로 연결
    assert result.matched_name is not None


# ── 파일명 CJK 자동 매핑 ─────────────────────────────────────────────────────

def test_filename_cjk_auto_mapping():
    """파일명의 CJK 블록과 candidates의 CJK 블록이 겹치면 매핑."""
    candidates = ["科丝美诗（中国）化妆品有限公司", "기타거래처"]
    # 파일명: CC-19_科丝美诗（中国）化妝品有限公司.pdf
    result = match_party(
        "CC-19_科丝美诗",  # extracted_name (파일명에서 추출)
        candidates,
        filename_hint="CC-19_科丝美诗（中国）化妝品有限公司.pdf",
    )
    # CJK 블록 매핑으로 연결되어야 함
    assert result.matched_name == "科丝美诗（中国）化妆品有限公司"


def test_filename_hint_new_future():
    """'New Future' 관련 alias 파일명 매핑."""
    candidates = ["뉴퓨처인터내셔널", "코스맥스㈜"]
    result = match_party(
        "New Future International",
        candidates,
        filename_hint="BC-14_New Future International Trade Co.pdf",
    )
    assert result.matched_name == "뉴퓨처인터내셔널"
    assert result.method == "alias"


# ── CJK 음독 힌트 기반 매칭 ──────────────────────────────────────────────────

def test_cjk_hint_cosmax():
    """科丝美诗 → alias 사전 또는 CJK 힌트로 매칭.
    candidates에 alias 사전의 canonical이 있으면 alias로 매핑.
    """
    # party_aliases.yaml에 "코스맥스 중국"이 과거 aliases 에 등록됨
    candidates = ["科丝美诗（中国）化妆品有限公司", "삼성전자"]
    result = match_party("COSMAX CHINA", candidates)
    # alias: "COSMAX CHINA" → "科丝美诗（中国）化妆품有限公司"
    assert result.matched_name is not None
    assert result.method == "alias"


def test_cjk_hint_fuzzy_korean():
    """CJK 이름에서 한국어 힌트 추출 → fuzzy partial 매칭."""
    # 코스맥스 중국 candidates에 한국어 표기
    candidates = ["코스맥스(중국)", "삼성전자"]
    # "코스맥스 중국"은 alias에 포함됨
    result = match_party("코스맥스 중국", candidates)
    # partial_ratio가 90 이상이거나 alias 매핑
    assert result.matched_name is not None


# ── 매칭 실패 케이스 ──────────────────────────────────────────────────────────

def test_failed_returns_top3():
    """매칭 실패 시 top-3 후보 반환."""
    candidates = ["코스맥스㈜", "삼성전자", "현대자동차", "LG화학"]
    result = match_party("알 수 없는 거래처 XXXYYYZZZ", candidates)
    assert result.method == "failed"
    assert result.matched_name is None
    assert len(result.candidates) <= 3


# ── 사업자번호 역조회 ──────────────────────────────────────────────────────────

def test_business_no_match():
    """사업자번호가 UploadGuide에 있으면 해당 거래처와 매핑."""
    from src.infrastructure.loaders import UploadGuideData, PartyContact
    contact = PartyContact(name="코스맥스㈜", business_no="123-45-67890")
    ug = UploadGuideData(send_targets=[contact])
    result = match_party(
        "알 수 없는 이름",
        ["코스맥스㈜"],
        upload_guide_data=ug,
        business_no="123-45-67890",
    )
    assert result.matched_name == "코스맥스㈜"
    assert result.method == "alias"
