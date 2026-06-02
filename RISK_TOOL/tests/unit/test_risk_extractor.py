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


def test_num_edge_cases():
    assert _num("-") is None
    assert _num("—") is None
    assert _num("") is None
    assert _num(None) is None
    assert _num("1,234") == 1234.0
    assert _num("-1,234") == -1234.0
    assert _num(" 1 234 ") == 1234.0
    assert _num("abc") is None
