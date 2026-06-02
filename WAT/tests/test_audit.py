import pytest
import audit


# --- 질문/세션 검증 (accounting과 동일 계약) ---
def test_validate_question_ok():
    assert audit.validate_question("감사인 독립성?") == "감사인 독립성?"


def test_validate_question_empty_raises():
    with pytest.raises(ValueError):
        audit.validate_question("   ")


def test_validate_conv_id_bad_raises():
    with pytest.raises(ValueError):
        audit.validate_conversation_id("../etc/passwd")


def test_init_db_idempotent(tmp_db):
    audit.init_db(tmp_db)
    audit.init_db(tmp_db)
    assert audit.get_session_id(tmp_db, "no-such-id") is None


def test_upsert_then_get(tmp_db):
    audit.init_db(tmp_db)
    audit.upsert_session(tmp_db, "550e8400-e29b-41d4-a716-446655440000", "sess-1")
    assert audit.get_session_id(tmp_db, "550e8400-e29b-41d4-a716-446655440000") == "sess-1"


# --- framework 토글: 자동/감사기준/윤리·법령 ---
def test_framework_auto_no_prefix():
    assert audit.apply_framework("질문", "auto") == "질문"


def test_framework_audit_prefix():
    out = audit.apply_framework("질문", "audit")
    assert out.endswith("질문")
    assert "회계감사기준" in out


def test_framework_ethics_law_prefix():
    out = audit.apply_framework("질문", "ethics_law")
    assert out.endswith("질문")
    assert ("윤리" in out) and ("외부감사법" in out or "공인회계사법" in out)


def test_framework_unknown_falls_back_to_auto():
    assert audit.validate_framework("garbage") == "auto"
    assert audit.apply_framework("질문", "garbage") == "질문"


# --- mode 검증 (accounting과 동일) ---
def test_mode_unknown_falls_back_to_fast():
    assert audit.validate_mode("garbage") == "fast"


# --- 시스템 프롬프트: 도메인 범위·인용형식·검색우선순위 토큰 ---
def test_prompt_scope_tokens():
    p = audit.audit_system_prompt("fast")
    assert "회계감사기준" in p
    assert "윤리" in p
    assert "외부감사법" in p
    assert "KSA" in p
    assert "거절" in p


def test_prompt_grounded_search_priority():
    p = audit.audit_system_prompt("grounded")
    assert "한국공인회계사회" in p or "한공회" in p
    assert "법제처" in p
    assert "WebSearch" in p


def test_prompt_law_article_consistency_guard():
    """iter1: fast 모드 법령 조문번호 환각·답변 내 불일치 방지 가드."""
    p = audit.audit_system_prompt("fast")
    assert "일관" in p          # 동일 개념 조문번호 일관성
    assert "🔍" in p            # 검색 없이 단정 시 마커 동반


def test_prompt_effective_date_guard():
    """iter1: 기준서 개정 시행일(개시vs종료·연도) 혼동 방지 가드."""
    p = audit.audit_system_prompt("fast")
    assert "시행일" in p
    assert "개시" in p and "종료" in p


def test_prompt_domain_accuracy_guards():
    p = audit.audit_system_prompt("fast")
    assert "재편" in p or "R400" in p
    assert "ISQM" in p


# --- build_command: 모델·툴·resume ---
def test_build_command_has_websearch_and_model():
    cmd = audit.build_command("질문", None, "/tmp/x", "auto", "fast")
    assert "WebSearch" in cmd
    assert "claude-sonnet-4-6" in cmd


def test_build_command_resume_when_session():
    cmd = audit.build_command("질문", "sess-1", "/tmp/x", "auto", "fast")
    assert "--resume" in cmd and "sess-1" in cmd


# --- parse_stream_line: accounting과 동일 파서 ---
def test_parse_token_delta():
    line = '{"type":"stream_event","event":{"delta":{"type":"text_delta","text":"안"}}}'
    assert audit.parse_stream_line(line) == {"type": "token", "text": "안"}


def test_parse_result_done():
    line = '{"type":"result","session_id":"s9","result":"끝"}'
    ev = audit.parse_stream_line(line)
    assert ev["type"] == "done" and ev["sessionId"] == "s9"
