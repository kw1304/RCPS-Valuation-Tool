"""E2E — Phase 2 마일스톤: 드롭 → 합산 표본 표시 직전까지."""
import pytest
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
from api.app import create_app
from src.infrastructure.db.session import make_engine, make_session
from src.infrastructure.db.models import Base


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def fixtures_ready():
    for name in ("dummy_ledger", "dummy_fs", "dummy_rp", "dummy_allowance"):
        if not (FIXTURES / f"{name}.xlsx").exists():
            pytest.skip(f"fixture {name}.xlsx missing — run build_dummy.py")


@pytest.fixture
def client(fixtures_ready):
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SF = make_session(engine)

    fx_mock = MagicMock()
    fx_mock.lookup.return_value = 1300.0

    app = create_app(testing=True, session_factory=SF)
    app.config["FX_CLIENT"] = fx_mock
    return app.test_client()


def _file(name):
    return (open(FIXTURES / f"{name}.xlsx", "rb"), f"{name}.xlsx")


def test_e2e_drop_to_sampling(client):
    r = client.post("/api/projects", json={
        "client": "DUMMY_CLIENT", "period_end": "2025-12-31",
        "base_ccy": "KRW", "materiality": 50_000_000, "tolerable": 25_000_000,
    })
    pid = r.get_json()["id"]

    data = {
        "ledger": _file("dummy_ledger"),
        "fs": _file("dummy_fs"),
        "rp": _file("dummy_rp"),
        "allowance": _file("dummy_allowance"),
    }
    r = client.post(f"/api/projects/{pid}/ingest",
                    data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    ing = r.get_json()
    assert ing["ar_count"] == 120
    assert ing["ap_count"] == 80
    assert ing["confidence_ar"] >= 0.95
    assert ing["confidence_ap"] >= 0.95
    assert ing["fs_totals"]["AR"] == 250_000_000

    r = client.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AR", "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
    })
    assert r.status_code == 200
    ar = r.get_json()
    assert ar["n_total"] >= 5

    r = client.post(f"/api/projects/{pid}/sampling/design", json={
        "kind": "AP", "confidence": 0.95, "expected_ms_pct": 0.0,
        "key_threshold": 5_000_000, "n_strata": 4, "seed": 42,
    })
    assert r.status_code == 200
    ap = r.get_json()
    assert ap["n_total"] > 0

    r = client.get(f"/api/projects/{pid}/state")
    body = r.get_json()
    assert body["populations"]["AR"]["count"] == 120
    assert body["populations"]["AP"]["count"] == 80
    assert body["samples"]["AR"]["count"] == ar["n_total"]
    assert body["samples"]["AP"]["count"] == ap["n_total"]
    ar_items = body["samples"]["AR"]["items"]
    ap_items = body["samples"]["AP"]["items"]
    assert any(i["selection_reason"] == "FORCED_RP" for i in ar_items)
    for item in ar_items + ap_items:
        if item["is_bad_debt"] and item["selection_reason"] in ("FORCED_KEY", "REP"):
            pytest.fail(f"부실거래처가 표본 포함: {item}")
