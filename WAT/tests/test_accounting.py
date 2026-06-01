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
    assert "--bare" in cmd
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


def test_build_command_resume():
    cmd = accounting.build_command("질문", session_id="sess-9", workdir="/tmp/x")
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == "sess-9"


def test_build_command_adddir():
    cmd = accounting.build_command("질문", session_id=None, workdir="/tmp/iso")
    assert "--add-dir" in cmd
    assert cmd[cmd.index("--add-dir") + 1] == "/tmp/iso"
