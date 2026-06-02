def test_routes_registered():
    from risk.interface.api.app import app
    paths = {r.path for r in app.routes}
    assert "/healthz" in paths
    assert "/api/assess" in paths
    assert "/api/export" in paths
