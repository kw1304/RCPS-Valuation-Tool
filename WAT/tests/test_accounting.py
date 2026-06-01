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
