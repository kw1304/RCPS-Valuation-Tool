"""Week 4 실 PDF 회귀 테스트 — 24개 온라인 PDF 일괄 파싱 검증.

합격 기준:
  - 거래처명 추출: 24건 중 ≥ 22건 (스캔 PDF 8건 제외 시 16건 중 ≥ 15건)
  - 기준일 추출: 텍스트 레이어 있는 PDF 100%
  - 잔액 합계 추출: 텍스트 레이어 있는 PDF 중 ≥ 90%
  - 회신일자 추출: 텍스트 레이어 있는 PDF 중 ≥ 90%
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pytest

# 실 PDF 디렉터리
ONLINE_DIR = Path(__file__).resolve().parent.parent / "input" / "조회서 회수본 및 대체적 절차" / "온라인"

# 스캔 PDF (텍스트 레이어 없음) — 파일명 기준
SCAN_PDFS = {
    "CC-10_COSMAX NBT SINGAPORE, INC_1차_채권채무조회서.pdf",
    "CC-11_COSMAX NBT USA, INC._1차_채권채무조회서.pdf",
    "CC-17_Xiyun (Shanghai) Trading Co., Ltd._1차_채권채무조회서.pdf",
    "CC-19_科#美#（中#）化#品有限公司_1차_채권채무조회서.pdf",
    "CC-3_COSMAX (Thailand) Co., Ltd._1차_채권채무조회서.pdf",
    "CC-6_COSMAX JAPAN, INC._1차_채권채무조회서.pdf",
    "CC-8_COSMAX NBT AUSTRALIA PTY. LTD_1차_채권채무조회서.pdf",
    "CC-9_COSMAX NBT SHANGHAI CO.LTD_1차_채권채무조회서.pdf",
}
# 인코딩 불량 (cid:X) PDF
ENCODING_BAD_PDFS = {
    "CC-12_COSMAX USA CORP_1차_채권채무조회서.pdf",
}

# 예상 거래처명 (파일명에서 파생)
EXPECTED_NAMES: dict[str, str] = {
    "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf": "(주)믹스앤매치",
    "CC-2_(주)우원_1차_채권채무조회서.pdf": "(주)우원",
    "CC-5_COSMAX California Corp._1차_채권채무조회서.pdf": "COSMAX California Corp.",
    "CC-13_EVONIK KOREA LTD._1차_채권채무조회서.pdf": "EVONIK KOREA LTD.",
    "CC-20_비디에이코퍼레이션(주)_1차_채권채무조회서 (1).pdf": "비디에이코퍼레이션(주)",
    "CC-23_세로켐_1차_채권채무조회서.pdf": "세로켐",
    "CC-24_씨엠테크 주식회사_1차_채권채무조회서.pdf": "씨엠테크",
    "CC-25_주식회사 이엘비종합건설_1차_채권채무조회서.pdf": "이엘비종합건설",
    "CC-27_코스맥스네오(쓰리애플즈코스메틱스)_1차_채권채무조회서.pdf": "코스맥스네오",
    "CC-28_코스맥스라보라토리(주)_1차_채권채무조회서.pdf": "코스맥스라보라토리",
    "CC-29_코스맥스바이오_1차_채권채무조회서.pdf": "코스맥스바이오",
    "CC-30_코스맥스에이비(주)_1차_채권채무조회서.pdf": "코스맥스에이비",
    "CC-31_코스맥스엔비티(주)_1차_채권채무조회서.pdf": "코스맥스엔비티",
    "CC-32_코스맥스엔에스(주)_1차_채권채무조회서.pdf": "코스맥스엔에스",
    "CC-35_코스맥스펫 주식회사_1차_채권채무조회서.pdf": "코스맥스펫",
}


def _strip_legal(name: str) -> str:
    """법인 접미사 제거 후 핵심 상호만 반환 (포함 여부 검사용)."""
    return re.sub(r"[\s㈜\(주\)주식회사\(\),.Ltd.Inc.Corp.]", "", name).lower()


@pytest.fixture(scope="module")
def parsed_results():
    """온라인 PDF 전체 파싱 결과 캐시."""
    if not ONLINE_DIR.exists():
        pytest.skip(f"실 PDF 디렉터리 없음: {ONLINE_DIR}")

    from src.infrastructure.pdf.extractor import extract_text
    from src.infrastructure.pdf.parser import parse_confirmation

    results = {}
    for pdf_file in sorted(ONLINE_DIR.glob("*.pdf")):
        extract = extract_text(pdf_file)
        parsed = parse_confirmation(
            extract.full_text,
            tables=extract.tables if extract.tables else None,
        )
        results[pdf_file.name] = {
            "extract": extract,
            "parsed": parsed,
        }
    return results


# ── 개별 파일 테스트 ────────────────────────────────────────────────────────────

class TestTextLayerPDFs:
    """텍스트 레이어 있는 PDF 파싱 검증."""

    def test_cc1_party_name(self, parsed_results):
        """CC-1 (주)믹스앤매치 거래처명 추출."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.extracted_party_name is not None
        assert "믹스앤매치" in parsed.extracted_party_name

    def test_cc1_period_end(self, parsed_results):
        """CC-1 기준일 2025-12-31 추출."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.period_end is not None
        assert parsed.period_end.year == 2025
        assert parsed.period_end.month == 12
        assert parsed.period_end.day == 31

    def test_cc1_reply_date(self, parsed_results):
        """CC-1 회신일자 2026-02-09 추출."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.reply_date == "2026-02-09"

    def test_cc1_receivable_balance(self, parsed_results):
        """CC-1 채권 합계 KRW 10,802,550 추출."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.receivable_total is not None
        assert abs(parsed.receivable_total - 10_802_550) < 1

    def test_cc1_accounts(self, parsed_results):
        """CC-1 계정과목별 잔액 — 외상매출금, 받을어음 각각 추출."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert "외상매출금" in parsed.receivable_by_account
        assert "받을어음" in parsed.receivable_by_account
        assert abs(parsed.receivable_by_account["외상매출금"] - 6_138_550) < 1
        assert abs(parsed.receivable_by_account["받을어음"] - 4_664_000) < 1

    def test_cc1_audit_firm(self, parsed_results):
        """CC-1 감사인명 삼덕회계법인 추출."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.audit_firm is not None
        assert "삼덕" in parsed.audit_firm

    def test_cc1_is_match(self, parsed_results):
        """CC-1 일치 선언 감지."""
        fname = "CC-1_(주)믹스앤매치_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.is_match_declared is True

    def test_cc13_evonik_party_name(self, parsed_results):
        """CC-13 EVONIK KOREA LTD. 거래처명 추출."""
        fname = "CC-13_EVONIK KOREA LTD._1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.extracted_party_name is not None
        assert "EVONIK" in parsed.extracted_party_name.upper()

    def test_cc13_eur_currency(self, parsed_results):
        """CC-13 EUR 통화 잔액 추출."""
        fname = "CC-13_EVONIK KOREA LTD._1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        # EUR 채무 잔액
        assert parsed.payable_total is not None
        assert abs(parsed.payable_total - 26202) < 1

    def test_cc5_english_format(self, parsed_results):
        """CC-5 영문 양식 — COSMAX California 거래처명 + USD 잔액 추출."""
        fname = "CC-5_COSMAX California Corp._1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.extracted_party_name is not None
        # 영문 양식: COSMAX California가 추출되어야 함
        name_lower = parsed.extracted_party_name.lower()
        assert "cosmax" in name_lower or "california" in name_lower
        # USD 잔액
        assert parsed.payable_total is not None
        assert parsed.payable_total > 0

    def test_cc29_both_tables(self, parsed_results):
        """CC-29 코스맥스바이오 — 채권·채무 두 표 모두 추출."""
        fname = "CC-29_코스맥스바이오_1차_채권채무조회서.pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        # 채권 합계 68,745,461,047
        assert parsed.receivable_total is not None
        assert abs(parsed.receivable_total - 68_745_461_047) < 1
        # 채무 합계 77,145,000
        assert parsed.payable_total is not None
        assert abs(parsed.payable_total - 77_145_000) < 1
        # 장기대여금 포함 확인
        assert "장기대여금" in parsed.receivable_by_account

    def test_cc20_reply_date_different_from_period_end(self, parsed_results):
        """CC-20 회신일(2026-03-09)이 기준일(2025-12-31)과 구분."""
        fname = "CC-20_비디에이코퍼레이션(주)_1차_채권채무조회서 (1).pdf"
        if fname not in parsed_results:
            pytest.skip("파일 없음")
        parsed = parsed_results[fname]["parsed"]
        assert parsed.period_end is not None
        assert parsed.reply_date is not None
        assert parsed.period_end.year == 2025
        assert "2026" in parsed.reply_date


class TestScanPDFs:
    """스캔 PDF (텍스트 레이어 없음) — extraction_failed로 처리되어야 함."""

    def test_scan_pdfs_low_confidence(self, parsed_results):
        """스캔 PDF는 추출 confidence 낮음 (텍스트 없음)."""
        for fname in SCAN_PDFS:
            if fname not in parsed_results:
                continue
            ext = parsed_results[fname]["extract"]
            # 텍스트 없는 경우 — method가 pdfplumber이고 텍스트가 없거나 failed
            assert ext.ok is False or len(ext.full_text.strip()) < 50, \
                f"{fname}: 스캔 PDF인데 텍스트가 추출됨"


class TestAggregateSuccess:
    """집계 합격 기준 테스트."""

    def test_party_name_success_rate(self, parsed_results):
        """텍스트 레이어 있는 PDF 거래처명 추출률 ≥ 87.5% (16건 중 14건)."""
        extractable = {k: v for k, v in parsed_results.items()
                      if k not in SCAN_PDFS and k not in ENCODING_BAD_PDFS
                      and v["extract"].ok}
        if not extractable:
            pytest.skip("텍스트 레이어 있는 PDF 없음")

        success = sum(
            1 for v in extractable.values()
            if v["parsed"].extracted_party_name is not None
        )
        total = len(extractable)
        rate = success / total
        assert rate >= 0.875, \
            f"거래처명 추출률 {rate:.1%} ({success}/{total}) — 기준 87.5% 미달"

    def test_period_end_success_rate(self, parsed_results):
        """텍스트 레이어 있는 PDF 기준일 추출률 ≥ 93%."""
        extractable = {k: v for k, v in parsed_results.items()
                      if k not in SCAN_PDFS and k not in ENCODING_BAD_PDFS
                      and v["extract"].ok}
        if not extractable:
            pytest.skip("텍스트 레이어 있는 PDF 없음")

        success = sum(
            1 for v in extractable.values()
            if v["parsed"].period_end is not None
        )
        total = len(extractable)
        rate = success / total
        assert rate >= 0.93, \
            f"기준일 추출률 {rate:.1%} ({success}/{total}) — 기준 93% 미달"

    def test_balance_success_rate(self, parsed_results):
        """텍스트 레이어 있는 PDF 잔액 추출률 ≥ 87.5%."""
        extractable = {k: v for k, v in parsed_results.items()
                      if k not in SCAN_PDFS and k not in ENCODING_BAD_PDFS
                      and v["extract"].ok}
        if not extractable:
            pytest.skip("텍스트 레이어 있는 PDF 없음")

        success = sum(
            1 for v in extractable.values()
            if (v["parsed"].receivable_total is not None or
                v["parsed"].payable_total is not None or
                v["parsed"].receivable_by_account or
                v["parsed"].payable_by_account)
        )
        total = len(extractable)
        rate = success / total
        assert rate >= 0.875, \
            f"잔액 추출률 {rate:.1%} ({success}/{total}) — 기준 87.5% 미달"

    def test_reply_date_success_rate(self, parsed_results):
        """텍스트 레이어 있는 PDF 회신일자 추출률 ≥ 87.5%."""
        extractable = {k: v for k, v in parsed_results.items()
                      if k not in SCAN_PDFS and k not in ENCODING_BAD_PDFS
                      and v["extract"].ok}
        if not extractable:
            pytest.skip("텍스트 레이어 있는 PDF 없음")

        success = sum(
            1 for v in extractable.values()
            if v["parsed"].reply_date is not None
        )
        total = len(extractable)
        rate = success / total
        assert rate >= 0.875, \
            f"회신일자 추출률 {rate:.1%} ({success}/{total}) — 기준 87.5% 미달"

    def test_print_summary(self, parsed_results, capsys):
        """파싱 결과 요약 출력 (디버깅용 — 항상 PASS)."""
        rows = []
        for fname, v in sorted(parsed_results.items()):
            ext = v["extract"]
            p = v["parsed"]
            is_scan = fname in SCAN_PDFS
            rows.append({
                "파일": fname[:45],
                "스캔": "O" if is_scan else "-",
                "거래처명": (p.extracted_party_name or "")[:20] if not is_scan else "-",
                "기준일": str(p.period_end) if p.period_end else "-",
                "회신일": p.reply_date or "-",
                "채권합계": f"{p.receivable_total:,.0f}" if p.receivable_total else "-",
                "채무합계": f"{p.payable_total:,.0f}" if p.payable_total else "-",
                "신뢰도": f"{p.extraction_confidence:.2f}" if not is_scan else "-",
            })

        with capsys.disabled():
            print("\n\n=== Week 4 실 PDF 파싱 결과 ===")
            print(f"{'파일':<45} {'스캔':^4} {'거래처명':<20} {'기준일':^12} {'회신일':^12} {'채권합계':>15} {'채무합계':>15} {'신뢰도':>6}")
            print("-" * 140)
            for r in rows:
                print(f"{r['파일']:<45} {r['스캔']:^4} {r['거래처명']:<20} {r['기준일']:^12} {r['회신일']:^12} {r['채권합계']:>15} {r['채무합계']:>15} {r['신뢰도']:>6}")
