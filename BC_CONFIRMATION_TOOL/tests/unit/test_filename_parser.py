from src.infrastructure.pdf.filename_parser import parse_filename

def test_online_format():
    r = parse_filename("전자_[BC-10]_코스맥스비티아이（주）_[124-81-22463]_대신증권_[2025년12월31일].pdf")
    assert r["bc_no"] == "BC-10"
    assert r["bank_raw"] == "대신증권"
    assert r["channel"] == "online"

def test_online_alt_paren():
    r = parse_filename("전자_[BC-1]_코스맥스비티아이(주)_[124-81-22463]_국민은행_[2025년12월31일].pdf")
    assert r["bc_no"] == "BC-1"
    assert r["bank_raw"] == "국민은행"

def test_postal_simple():
    r = parse_filename("BC-26_신한은행 홍콩.pdf")
    assert r["bc_no"] == "BC-26"
    assert r["bank_raw"] == "신한은행 홍콩"
    assert r["channel"] == "postal"

def test_postal_with_company():
    r = parse_filename("BC-25_코스맥스비티아이_예별손해보험.pdf")
    assert r["bc_no"] == "BC-25"
    assert r["bank_raw"] == "예별손해보험"

def test_unknown_returns_none():
    r = parse_filename("randomfile.pdf")
    assert r["bc_no"] is None
