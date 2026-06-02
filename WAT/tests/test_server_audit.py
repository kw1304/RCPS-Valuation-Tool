import json
import pytest
import server as srv
import audit


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "audit.db")
    audit.init_db(db)
    monkeypatch.setattr(srv, "AUDIT_DB", db)
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def test_audit_ask_rejects_empty_body(client):
    r = client.post("/api/audit/ask", json={})
    assert r.status_code == 400


def test_audit_ask_streams_sse(client, monkeypatch):
    def fake_ask_stream(db, cid, q, framework="auto", mode="fast", runner=None):
        yield {"type": "tool", "label": "WebSearch 실행 중…"}
        yield {"type": "token", "text": "독립성"}
        yield {"type": "done", "sessionId": "s1", "text": "독립성"}

    monkeypatch.setattr(audit, "ask_stream", fake_ask_stream)
    r = client.post("/api/audit/ask", json={
        "conversationId": "550e8400-e29b-41d4-a716-446655440000",
        "question": "감사인 독립성?",
    })
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    body = r.get_data(as_text=True)
    assert "done" in body


def test_healthz_still_ok(client):
    r = client.get("/healthz")
    data = json.loads(r.get_data(as_text=True))
    assert data["status"] == "ok"
