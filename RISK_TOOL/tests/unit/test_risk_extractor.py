"""risk_extractor 단위 — rows_to_years 매핑 + _num edge (네트워크 없음)."""
from risk.infrastructure.dart.risk_extractor import rows_to_years, _num


def test_rows_to_years_maps_accounts():
    rows = [
        {"account_id": "ifrs-full_Revenue", "bsns_year": "2025",
         "thstrm_amount": "1,000", "frmtrm_amount": "900"},
        {"account_id": "ifrs-full_Equity", "bsns_year": "2025",
         "thstrm_amount": "-50", "frmtrm_amount": "100"},
    ]
    years = rows_to_years(rows)
    y2025 = next(y for y in years if y.year == 2025)
    y2024 = next(y for y in years if y.year == 2024)
    assert y2025.revenue == 1000
    assert y2025.total_equity == -50
    assert y2024.revenue == 900
    assert y2024.total_equity == 100


def test_rows_to_years_empty():
    assert rows_to_years([]) == []


def test_rows_to_years_ignores_unknown_account_id():
    rows = [
        {"account_id": "some_unknown_tag", "bsns_year": "2025",
         "thstrm_amount": "1,000", "frmtrm_amount": "900"},
    ]
    assert rows_to_years(rows) == []


def test_rows_to_years_sorted_ascending():
    rows = [
        {"account_id": "ifrs-full_Revenue", "bsns_year": "2025",
         "thstrm_amount": "1,000", "frmtrm_amount": "900"},
    ]
    years = rows_to_years(rows)
    assert [y.year for y in years] == [2024, 2025]


def test_trade_receivables_account_variants():
    # 회사별 변형: CurrentTradeReceivables(삼성)·TradeAndOther… 둘 다 매출채권으로 매핑
    for aid in ("ifrs-full_CurrentTradeReceivables",
                "ifrs-full_TradeAndOtherCurrentReceivables",
                "dart_ShortTermTradeReceivable"):
        rows = [{"account_id": aid, "bsns_year": "2025",
                 "thstrm_amount": "500", "frmtrm_amount": "400"}]
        y = next(y for y in rows_to_years(rows) if y.year == 2025)
        assert y.trade_receivables == 500, aid


def test_account_id_priority_lower_rank_wins():
    # 같은 필드에 두 후보 → rank 낮은(우선) CurrentTradeReceivables가 이김
    rows = [
        {"account_id": "ifrs-full_TradeAndOtherCurrentReceivables", "bsns_year": "2025",
         "thstrm_amount": "999", "frmtrm_amount": "0"},
        {"account_id": "ifrs-full_CurrentTradeReceivables", "bsns_year": "2025",
         "thstrm_amount": "500", "frmtrm_amount": "0"},
    ]
    y = next(y for y in rows_to_years(rows) if y.year == 2025)
    assert y.trade_receivables == 500  # 우선 후보 채택, 순서 무관


def test_trade_payables_account_variants():
    # 매입채무: TradeAndOtherCurrentPayables·dart_ShortTermTradePayable 둘 다 매핑
    for aid in ("ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers",
                "ifrs-full_TradeAndOtherCurrentPayables",
                "dart_ShortTermTradePayables",
                "dart_ShortTermTradePayable",
                "dart_TradePayable"):
        rows = [{"account_id": aid, "bsns_year": "2025",
                 "thstrm_amount": "700", "frmtrm_amount": "600"}]
        y = next(y for y in rows_to_years(rows) if y.year == 2025)
        assert y.trade_payables == 700, aid


def test_num_edge_cases():
    assert _num("-") is None
    assert _num("—") is None
    assert _num("") is None
    assert _num(None) is None
    assert _num("1,234") == 1234.0
    assert _num("-1,234") == -1234.0
    assert _num(" 1 234 ") == 1234.0
    assert _num("abc") is None


def test_classify_statement_adverse_labels():
    # 적자기업·약식라벨: '매출'(원가) + '영업손실' → IS로 인식
    from risk.infrastructure.dart.risk_extractor import _classify_statement
    rows = [("매출", []), ("매출원가", []), ("매출총이익", []),
            ("판매비와관리비", []), ("영업손실", []), ("당기순손실", [])]
    assert _classify_statement(rows) == "IS"
    bs = [("자산총계", []), ("부채총계", []), ("자본총계", [])]
    assert _classify_statement(bs) == "BS"


def test_parse_fs_document_adverse_company():
    # 영업손실·당기순손실·약식 '매출' 라벨 + 천원 단위 파싱
    from risk.infrastructure.dart.risk_extractor import _parse_fs_document
    html = """
    <p>손익계산서 (단위: 천원)</p>
    <TABLE>
      <TR><TD>과목</TD><TD>당기</TD><TD>전기</TD></TR>
      <TR><TD>매출</TD><TD>1,000,000</TD><TD>900,000</TD></TR>
      <TR><TD>매출원가</TD><TD>700,000</TD><TD>600,000</TD></TR>
      <TR><TD>매출총이익</TD><TD>300,000</TD><TD>300,000</TD></TR>
      <TR><TD>영업손실</TD><TD>(50,000)</TD><TD>(30,000)</TD></TR>
      <TR><TD>당기순손실</TD><TD>(80,000)</TD><TD>(40,000)</TD></TR>
    </TABLE>"""
    out = _parse_fs_document(html, 2024)
    cur = out[2024]
    assert cur["revenue"] == 1_000_000 * 1000      # 천원 → 원
    assert cur["cogs"] == 700_000 * 1000
    assert cur["operating_income"] == -50_000 * 1000   # 괄호=음수
    assert cur["net_income"] == -80_000 * 1000
