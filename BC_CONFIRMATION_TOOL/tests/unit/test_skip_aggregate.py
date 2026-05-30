"""결합본 aggregate(파일명 미식별) 스킵 회귀 가드.

FY2024 온라인 디렉터리의 `new-document-…` 합본 스캔은 모든 개별 BC-N 회신을
중복 포함하면서 'securities' 로 fingerprint 돼 연대보증/담보를 개별 파일과 다른
AC로 mis-route 한다(record_dedup 이 못 잡는 중복 누출). 표준 회신은 항상 BC-N
파일명을 가지므로, parse_filename 이 bc_no·bank 둘 다 없는 파일은 per-institution
회신이 아니라 합본/미상 스캔으로 보고 스킵한다.
"""
from src.infrastructure.pdf.filename_parser import parse_filename
from src.application.parse_response_uc import is_unidentified_aggregate


def test_aggregate_filename_has_no_bcno():
    m = parse_filename("new-document-2025-04-10 12_58.pdf")
    assert not m.get("bc_no"), m


def test_standard_reply_has_bcno():
    m = parse_filename(
        "전자_[BC-1]_코스맥스비티아이(주)_[124-81-22463]_국민은행_[2025년12월31일].pdf"
    )
    assert m.get("bc_no")


def test_aggregate_is_skipped():
    # bc_no·bank 둘 다 없음 → 합본/미상 → 스킵 대상
    assert is_unidentified_aggregate("new-document-2025-04-10 12_58.pdf") is True


def test_online_reply_not_skipped():
    nm = "전자_[BC-1]_코스맥스비티아이(주)_[124-81-22463]_국민은행_[2025년12월31일].pdf"
    assert is_unidentified_aggregate(nm) is False


def test_postal_reply_not_skipped():
    # 우편 BC-N 파일은 bc_no 가 있으므로 절대 스킵하면 안 된다
    assert is_unidentified_aggregate("BC-8_코스맥스비티아이(주)_124-81-22463_한국증권금융_2024-12-31.pdf") is False
