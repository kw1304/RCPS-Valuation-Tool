import pytest
import accounting


def test_validate_question_ok():
    assert accounting.validate_question("리스 회계처리는?") == "리스 회계처리는?"


def test_validate_question_strips():
    assert accounting.validate_question("  질문  ") == "질문"


def test_validate_question_empty_raises():
    with pytest.raises(ValueError):
        accounting.validate_question("   ")


def test_validate_question_too_long_raises():
    with pytest.raises(ValueError):
        accounting.validate_question("가" * 4001)


def test_validate_conv_id_ok():
    cid = "550e8400-e29b-41d4-a716-446655440000"
    assert accounting.validate_conversation_id(cid) == cid


def test_validate_conv_id_bad_raises():
    with pytest.raises(ValueError):
        accounting.validate_conversation_id("../etc/passwd")


def test_init_db_creates_table(tmp_db):
    accounting.init_db(tmp_db)
    # 재호출 멱등
    accounting.init_db(tmp_db)
    assert accounting.get_session_id(tmp_db, "no-such-id") is None


def test_upsert_then_get(tmp_db):
    accounting.init_db(tmp_db)
    cid = "550e8400-e29b-41d4-a716-446655440000"
    accounting.upsert_session(tmp_db, cid, "sess-abc")
    assert accounting.get_session_id(tmp_db, cid) == "sess-abc"


def test_upsert_updates_session(tmp_db):
    accounting.init_db(tmp_db)
    cid = "550e8400-e29b-41d4-a716-446655440000"
    accounting.upsert_session(tmp_db, cid, "sess-1")
    accounting.upsert_session(tmp_db, cid, "sess-2")
    assert accounting.get_session_id(tmp_db, cid) == "sess-2"


def test_build_command_new_session():
    cmd = accounting.build_command("질문", session_id=None, workdir="/tmp/x")
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "질문" in cmd
    # 외부 환경 훅(caveman 등) 차단 — user 설정 미로드, 인증(keychain)은 유지
    assert "--setting-sources" in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == "project,local"
    assert "--bare" not in cmd
    assert "WebSearch" in cmd
    # 도구 화이트리스트는 WebSearch만
    i = cmd.index("--allowedTools")
    assert cmd[i + 1] == "WebSearch"
    assert "--dangerously-skip-permissions" not in cmd
    assert "--resume" not in cmd
    assert "stream-json" in cmd
    assert "--verbose" in cmd
    # 시스템 프롬프트 주입
    assert "--system-prompt" in cmd
    sp = cmd[cmd.index("--system-prompt") + 1]
    assert "회계감사기준" in sp
    # 속도: Sonnet 고정 + 토큰 실시간 스트리밍
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--include-partial-messages" in cmd


def test_build_command_resume():
    cmd = accounting.build_command("질문", session_id="sess-9", workdir="/tmp/x")
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == "sess-9"


def test_build_command_adddir():
    cmd = accounting.build_command("질문", session_id=None, workdir="/tmp/iso")
    assert "--add-dir" in cmd
    assert cmd[cmd.index("--add-dir") + 1] == "/tmp/iso"


import json


def test_parse_assistant_text_ignored_uses_deltas():
    # 본문은 stream_event 델타로 전달되므로 assistant 텍스트는 무시(중복 방지)
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "리스는 K-IFRS 1116"}]},
        "session_id": "s1",
    })
    assert accounting.parse_stream_line(line) is None


def test_parse_text_delta_token():
    line = json.dumps({
        "type": "stream_event",
        "event": {"type": "content_block_delta", "index": 0,
                  "delta": {"type": "text_delta", "text": "리스는"}},
    })
    assert accounting.parse_stream_line(line) == {"type": "token", "text": "리스는"}


def test_parse_thinking_delta_ignored():
    line = json.dumps({
        "type": "stream_event",
        "event": {"type": "content_block_delta",
                  "delta": {"type": "thinking_delta", "thinking": "..."}},
    })
    assert accounting.parse_stream_line(line) is None


def test_parse_assistant_tool_use():
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "K-IFRS 1116 리스"}}
        ]},
        "session_id": "s1",
    })
    ev = accounting.parse_stream_line(line)
    assert ev["type"] == "tool"
    assert "WebSearch" in ev["label"]


def test_parse_result():
    line = json.dumps({
        "type": "result", "subtype": "success",
        "result": "최종답변", "session_id": "s9",
    })
    ev = accounting.parse_stream_line(line)
    assert ev == {"type": "done", "sessionId": "s9", "text": "최종답변"}


def test_parse_system_init():
    line = json.dumps({"type": "system", "subtype": "init", "session_id": "s0"})
    ev = accounting.parse_stream_line(line)
    assert ev == {"type": "session", "sessionId": "s0"}


def test_parse_hook_noise_ignored():
    line = json.dumps({"type": "system", "subtype": "hook_started", "session_id": "x"})
    assert accounting.parse_stream_line(line) is None


def test_parse_rate_limit_ignored():
    assert accounting.parse_stream_line(json.dumps({"type": "rate_limit_event"})) is None


def test_parse_garbage_ignored():
    assert accounting.parse_stream_line("not json") is None
    assert accounting.parse_stream_line("") is None


def _fake_runner(lines):
    """build_command를 무시하고 미리 준비한 stream-json 라인들을 yield."""
    def runner(cmd):
        for ln in lines:
            yield ln
    return runner


def test_ask_stream_happy_path(tmp_db):
    accounting.init_db(tmp_db)
    cid = "550e8400-e29b-41d4-a716-446655440000"
    lines = [
        json.dumps({"type": "system", "subtype": "init", "session_id": "newsess"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "x"}}]}}),
        json.dumps({"type": "stream_event", "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "답변 본문"}}}),
        json.dumps({"type": "result", "subtype": "success",
                    "result": "답변 본문", "session_id": "newsess"}),
    ]
    events = list(accounting.ask_stream(
        tmp_db, cid, "리스 질문", runner=_fake_runner(lines)))
    types = [e["type"] for e in events]
    assert "tool" in types
    assert "token" in types
    assert types[-1] == "done"
    # 세션 저장 확인
    assert accounting.get_session_id(tmp_db, cid) == "newsess"


def test_ask_stream_resumes_existing(tmp_db):
    accounting.init_db(tmp_db)
    cid = "550e8400-e29b-41d4-a716-446655440000"
    accounting.upsert_session(tmp_db, cid, "oldsess")
    captured = {}

    def runner(cmd):
        captured["cmd"] = cmd
        yield json.dumps({"type": "result", "subtype": "success",
                          "result": "ok", "session_id": "oldsess"})

    list(accounting.ask_stream(tmp_db, cid, "후속질문", runner=runner))
    assert "--resume" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--resume") + 1] == "oldsess"


def test_ask_stream_bad_question_yields_error(tmp_db):
    accounting.init_db(tmp_db)
    cid = "550e8400-e29b-41d4-a716-446655440000"
    events = list(accounting.ask_stream(
        tmp_db, cid, "   ", runner=_fake_runner([])))
    assert events[0]["type"] == "error"


def test_parse_non_dict_json_ignored():
    assert accounting.parse_stream_line(json.dumps([1, 2, 3])) is None
    assert accounting.parse_stream_line(json.dumps(42)) is None
    assert accounting.parse_stream_line(json.dumps(None)) is None
    assert accounting.parse_stream_line(json.dumps("hi")) is None


def test_parse_mixed_text_and_tool_use_prefers_tool():
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "text", "text": "검색하겠습니다"},
            {"type": "tool_use", "name": "WebSearch", "input": {"query": "q"}},
        ]},
    })
    ev = accounting.parse_stream_line(line)
    assert ev["type"] == "tool"


def test_ask_stream_semaphore_timeout_yields_error(tmp_db, monkeypatch):
    accounting.init_db(tmp_db)
    cid = "550e8400-e29b-41d4-a716-446655440000"
    monkeypatch.setattr(accounting, "SUBPROC_TIMEOUT", 0.1)
    # 3개 슬롯 모두 점유 → acquire 실패 경로
    for _ in range(3):
        accounting._SEM.acquire()
    try:
        def runner(cmd):
            raise AssertionError("runner must not be called on timeout")
            yield  # pragma: no cover
        events = list(accounting.ask_stream(tmp_db, cid, "질문", runner=runner))
        assert events == [{"type": "error", "message": "서버 혼잡 — 잠시 후 재시도"}]
    finally:
        for _ in range(3):
            accounting._SEM.release()


def test_resolve_claude_none_when_absent(monkeypatch):
    monkeypatch.setattr(accounting.shutil, "which", lambda _: None)
    assert accounting.resolve_claude() is None


def test_resolve_claude_unwraps_windows_cmd(monkeypatch, tmp_path):
    shim = tmp_path / "claude.CMD"
    shim.write_text("@echo")
    binexe = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    binexe.parent.mkdir(parents=True)
    binexe.write_text("")
    monkeypatch.setattr(accounting.shutil, "which", lambda _: str(shim))
    monkeypatch.setattr(accounting.os, "name", "nt")
    assert accounting.resolve_claude() == str(binexe)


def test_resolve_claude_passthrough_posix(monkeypatch):
    monkeypatch.setattr(accounting.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(accounting.os, "name", "posix")
    assert accounting.resolve_claude() == "/usr/bin/claude"


def test_resolve_claude_env_override(monkeypatch, tmp_path):
    exe = tmp_path / "myclaude.exe"
    exe.write_text("")
    monkeypatch.setenv("WAT_CLAUDE_PATH", str(exe))
    monkeypatch.setattr(accounting.shutil, "which", lambda _: None)
    assert accounting.resolve_claude() == str(exe)


def test_resolve_claude_env_override_missing_falls_back(monkeypatch):
    monkeypatch.setenv("WAT_CLAUDE_PATH", "C:/nope/missing.exe")
    monkeypatch.setattr(accounting.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(accounting.os, "name", "posix")
    assert accounting.resolve_claude() == "/usr/bin/claude"
