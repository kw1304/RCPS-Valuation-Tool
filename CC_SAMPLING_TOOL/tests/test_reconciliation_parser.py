"""불일치 소명 xlsx 파서 테스트 — BC-5,12."""
from __future__ import annotations

import pytest
from pathlib import Path

RECON_XLSX = (
    Path(__file__).resolve().parents[1]
    / "input" / "조회서 회수본 및 대체적 절차" / "대체적 증빙"
    / "BC-5,12_채권채무조회서_불일치 소명.xlsx"
)


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_parse_mismatch_sheet():
    """회신-불일치 시트 → MismatchRow 3건 이상 추출."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    assert len(sheets.mismatch_rows) >= 3, f"불일치 행 수 부족: {len(sheets.mismatch_rows)}"


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_mismatch_party_names():
    """회신-불일치 시트 → 거래처명 포함 여부."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    party_names = [r.party_name for r in sheets.mismatch_rows if r.party_name]
    assert len(party_names) >= 2, "거래처명 없음"
    # COSMAX USA 또는 COSMAX California 중 하나
    has_cosmax = any("COSMAX" in p for p in party_names)
    assert has_cosmax, f"예상 거래처 없음: {party_names}"


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_mismatch_amounts():
    """회신-불일치 시트 → 발송금액·차이금액 추출."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    rows_with_amount = [r for r in sheets.mismatch_rows if r.sent_amount is not None]
    assert len(rows_with_amount) >= 1, "발송금액 없음"

    for r in rows_with_amount:
        assert isinstance(r.sent_amount, float)


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_detail_sheets():
    """거래처별 시트 (COSMAX USA, COSMAX California) → 거래 단위 명세 추출."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    assert len(sheets.party_details) >= 1, f"거래처 시트 없음: {list(sheets.party_details.keys())}"


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_cosmax_usa_detail():
    """COSMAX USA 시트 → DetailRow 추출 + 대사구분 필드 확인."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    details = sheets.party_details.get("COSMAX USA")
    if details is None:
        # 시트명 대소문자 차이 허용
        for k, v in sheets.party_details.items():
            if "COSMAX USA" in k.upper():
                details = v
                break
    assert details is not None, f"COSMAX USA 시트 없음: {list(sheets.party_details.keys())}"
    assert len(details) >= 1

    # 대사구분 필드
    has_reconcile_type = any(d.reconcile_type for d in details)
    assert has_reconcile_type, "대사구분 미추출"


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_detail_amounts():
    """거래처별 시트 → 기능통화금액(KRW) 추출."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    all_details = [d for rows in sheets.party_details.values() for d in rows]
    rows_with_func = [d for d in all_details if d.amount_func is not None]
    assert len(rows_with_func) >= 1, "기능통화금액 미추출"


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_summary_by_party():
    """summary_by_party → 거래처별 합산 금액 딕셔너리."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    summary = sheets.summary_by_party()
    assert isinstance(summary, dict)
    assert len(summary) >= 1

    for party, info in summary.items():
        assert "sent_amount" in info
        assert "difference" in info


@pytest.mark.skipif(not RECON_XLSX.exists(), reason="실데이터 없음")
def test_mismatch_parties_list():
    """mismatch_parties 프로퍼티 — 중복 없는 거래처명 목록."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    sheets = parse_reconciliation_xlsx(RECON_XLSX)
    parties = sheets.mismatch_parties
    assert len(parties) >= 1
    # 중복 없음 검증
    assert len(parties) == len(set(parties))


def test_file_not_found():
    """존재하지 않는 파일 → FileNotFoundError."""
    from src.infrastructure.evidence.reconciliation_parser import parse_reconciliation_xlsx

    with pytest.raises(FileNotFoundError):
        parse_reconciliation_xlsx(Path("/nonexistent/test.xlsx"))
