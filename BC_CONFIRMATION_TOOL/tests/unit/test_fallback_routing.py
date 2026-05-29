from src.infrastructure.pdf.row_parsers.fallback import fallback_parse


def test_insurer_postal_to_ac7():
    recs = fallback_parse("흥국화재 보험증권 100,000,000 부보", bc_no="BC-30", bank="흥국화재")
    assert recs and all(r["ac_section"] != "AC1" for r in recs)
    assert any(r["ac_section"] == "AC7" for r in recs)


def test_nonfinancial_not_ac1():
    recs = fallback_parse("카일이삼제스퍼 50,000,000", bc_no="BC-29", bank="카일이삼제스퍼")
    assert all(r["ac_section"] != "AC1" for r in recs), [r["ac_section"] for r in recs]


def test_bank_postal_stays_ac1():
    recs = fallback_parse("신한은행 홍콩 예금 잔액 100,000,000", bc_no="BC-26", bank="신한은행")
    assert any(r["ac_section"] == "AC1" for r in recs)
