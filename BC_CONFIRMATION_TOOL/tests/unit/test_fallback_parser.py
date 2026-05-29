from src.infrastructure.pdf.row_parsers.fallback import fallback_parse

def test_fallback_flags_manual_review():
    text = "신한은행 홍콩 USD 예금 잔액 100,000"
    recs = fallback_parse(text, bc_no="BC-26", bank="신한은행 홍콩")
    assert all(r["needs_manual_review"] for r in recs)
    assert recs and recs[0]["ac_section"] == "AC1"
