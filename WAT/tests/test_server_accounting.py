import json
import pytest
import server as srv
import accounting


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "acct.db")
    accounting.init_db(db)
    monkeypatch.setattr(srv, "ACCOUNTING_DB", db)
    srv.app.config["TESTING"] = True
    return srv.app.test_client()


def test_ask_rejects_bad_json(client):
    r = client.post("/api/accounting/ask", json={})
    assert r.status_code == 400


def test_ask_streams_sse(client, monkeypatch):
    def fake_ask_stream(db, cid, q, runner=None):
        yield {"type": "tool", "label": "WebSearch 실행 중…"}
        yield {"type": "token", "text": "답변"}
        yield {"type": "done", "sessionId": "s1", "text": "답변"}

    monkeypatch.setattr(accounting, "ask_stream", fake_ask_stream)
    r = client.post("/api/accounting/ask", json={
        "conversationId": "550e8400-e29b-41d4-a716-446655440000",
        "question": "리스?",
    })
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    body = r.get_data(as_text=True)
    assert "event: token" in body or '"type": "token"' in body
    assert "done" in body


def test_healthz_has_claude_cli(client):
    r = client.get("/healthz")
    data = json.loads(r.get_data(as_text=True))
    assert "claude_cli" in data
