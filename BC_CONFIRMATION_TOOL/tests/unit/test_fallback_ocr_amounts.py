"""우편/OCR 회신서의 OCR-노이즈 금액(점·콤마 혼용 천단위) 파싱 + AC7 부보금액 추출.

스캔 보험사 회신서(흥국화재·예별/MG손해보험)는 디지털 텍스트가 0이라 OCR 해야 하고,
OCR 은 천단위 구분자를 점(.)·콤마(,) 로 뒤섞어 인식한다:
  20,215.243,773  /  5.135.784,000  /  20.215.243.773  →  모두 정수 원화.
fallback_parse 가 이런 토큰을 올바른 정수로 복원하고, 보험사(AC7) 행은 가장 큰 금액을
부보금액으로 잡아야 한다(참고조서 AC7 부보금액 정합).
"""
from decimal import Decimal

from src.infrastructure.pdf.row_parsers.fallback import fallback_parse, _ocr_amounts


def test_ocr_amount_mixed_dot_comma():
    # 점·콤마가 뒤섞인 천단위 그룹은 모두 구분자로 보고 정수 복원
    assert _ocr_amounts("20,215.243,773") == [Decimal("20215243773")]
    assert _ocr_amounts("5.135.784,000") == [Decimal("5135784000")]
    assert _ocr_amounts("20.215.243.773") == [Decimal("20215243773")]


def test_ocr_amount_clean_comma_unchanged():
    assert _ocr_amounts("26,329,689,846") == [Decimal("26329689846")]
    assert _ocr_amounts("7,971,566") == [Decimal("7971566")]


def test_ocr_amount_ignores_dates_and_rates():
    # 24.11.07 (날짜), 0.00% (이자율) 은 금액 아님
    amts = _ocr_amounts("Policy 20240258411 24.11.07~ 25.12.14 20,215.243,773 7,810,732 0.00%")
    assert Decimal("20215243773") in amts
    assert Decimal("7810732") in amts
    assert Decimal("24") not in amts  # 날짜 조각 아님


def test_insurer_ocr_row_coverage_is_largest():
    # 예별손해보험 OCR 행: 부보금액(20.2B) = 행 최대 금액 → AC7 payload 의 coverage_amount
    line = "PackageInsurancePolicy 20240258411 24.11.07~ 25.12.14 20,215.243,773 7,810,732 7.810,732"
    recs = fallback_parse(line, bc_no="BC-25", bank="예별손해보험")
    ac7 = [r for r in recs if r["ac_section"] == "AC7"]
    assert ac7, recs
    covs = [Decimal(str(a)) for r in ac7 for a in r["payload"]["amounts"]]
    assert Decimal("20215243773") == max(covs)


def test_insurer_ocr_subtotal_row_dropped():
    # OCR 합계행(증권번호·상품명 없는 순수 금액 행)은 부보금액 이중계상 → 제외.
    text = (
        "PackageInsurancePolicy 20240258411 24.11.07~ 25.12.14 20,215.243,773 7,810,732 7.810,732\n"
        "20250063608 25.03.11~26.03.11 5.135.784,000 10.098,200 10,098.200\n"
        "20240056896 24.03.11~25.03.11 5.135.784,000 10,746.800 10.746.800\n"
        "30,486.811,773 28.655,732 28,655.732 10.098,200\n"  # 합계행 — 제외돼야
    )
    recs = fallback_parse(text, bc_no="BC-25", bank="예별손해보험")
    row_max = sorted(max(Decimal(str(a)) for a in r["payload"]["amounts"]) for r in recs)
    # 부보금액 3건(20.2B, 5.1B, 5.1B)만 남고 합계 30.4B 는 없어야 한다.
    assert Decimal("30486811773") not in row_max, row_max
    assert Decimal("20215243773") in row_max
    assert row_max.count(Decimal("5135784000")) == 2


def test_heungkuk_subtotal_row_dropped():
    text = (
        "Policy 12512730180000 26,329,689,846 7,971,566 0.00%\n"
        "26,329,689,846 7,971,566\n"  # 합계행 — 제외돼야 (이중계상 방지)
    )
    recs = fallback_parse(text, bc_no="BC-30", bank="흥국화재")
    maxes = [max(Decimal(str(a)) for a in r["payload"]["amounts"]) for r in recs]
    assert maxes.count(Decimal("26329689846")) == 1, maxes


def test_insurer_with_text_label_kept():
    # 증권번호 없어도 한글 라벨(보험증권/부보)이 있는 행은 실데이터로 보존(기존 동작).
    recs = fallback_parse("흥국화재 보험증권 100,000,000 부보", bc_no="BC-30", bank="흥국화재")
    assert any(r["ac_section"] == "AC7" for r in recs)


def test_heungkuk_clean_comma_coverage():
    line = "Policy 12512730180000 26,329,689,846 7,971,566 0.00%"
    recs = fallback_parse(line, bc_no="BC-30", bank="흥국화재")
    ac7 = [r for r in recs if r["ac_section"] == "AC7"]
    assert ac7
    covs = [Decimal(str(a)) for r in ac7 for a in r["payload"]["amounts"]]
    assert Decimal("26329689846") == max(covs)
