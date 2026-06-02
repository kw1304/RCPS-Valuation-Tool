# WAT 감사·윤리기준 리서치 AI 툴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 감사기준(KSA/ISA)·공인회계사 윤리기준·관련 법령(공회법·외감법)을 질의응답으로 리서치하는 WAT 탭을, 회계기준 AI 툴(`accounting.py`) 아키텍처를 복제해 도메인만 교체하여 만든다.

**Architecture:** Flask SSE 서버가 `claude -p` 서브프로세스를 감싸 토큰 스트리밍. `accounting.py`를 `audit.py`로 복제하고 시스템프롬프트·framework토글·검색우선순위·테이블명만 교체. UI는 `accounting/index.html`의 CSS를 그대로 쓰되 JS는 읽기 가능한 새 버전으로 작성(엔드포인트·localStorage키·토글 라벨 교체).

**Tech Stack:** Python 3, Flask, sqlite3, `claude` CLI(stream-json), pytest, 순수 HTML/JS(빌드 없음).

**참조 스펙:** `docs/superpowers/specs/2026-06-02-wat-audit-ethics-ai-design.md`

---

## File Structure

- **Create** `WAT/audit.py` — 핵심 로직(검증·세션·프롬프트·파싱·오케스트레이션). `accounting.py` 복제 + 도메인 교체. 함수 시그니처는 `accounting.py`와 동일 유지(`validate_question`, `validate_conversation_id`, `init_db`, `get_session_id`, `upsert_session`, `audit_system_prompt`, `validate_mode`, `validate_framework`, `apply_framework`, `build_command`, `parse_stream_line`, `resolve_claude`, `ask_stream`). 테이블명 `audit_conv`.
- **Create** `WAT/audit/index.html` — UI. `accounting/index.html`의 `<style>`는 그대로 복사, `<body>`+`<script>`는 읽기 가능한 새 JS로 작성. 엔드포인트 `/api/audit/ask`, localStorage 키 `audit_*`, 토글 `[자동/감사기준/윤리·법령]`.
- **Modify** `WAT/server.py` — `import audit`, `AUDIT_DB` 상수, `audit.init_db`, `/api/audit/ask` 라우트, `/healthz`에 audit 표시.
- **Create** `WAT/tests/test_audit.py` — 도메인 단위테스트(framework prefix·validate·프롬프트 토큰).
- **Create** `WAT/tests/test_server_audit.py` — SSE 라우트 테스트.

모든 명령은 `WAT/` 디렉토리에서 실행: `cd c:\Claude\WAT`.

---

## Task 1: audit.py 핵심 로직 (도메인 교체 복제)

**Files:**
- Create: `WAT/audit.py`
- Test: `WAT/tests/test_audit.py`

- [ ] **Step 1: 실패 테스트 작성** — framework prefix·validate·프롬프트 도메인 토큰 검증

Create `WAT/tests/test_audit.py`:

```python
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
    assert "회계감사기준" in p          # 범위
    assert "윤리" in p                  # 범위
    assert "외부감사법" in p            # 범위
    assert "KSA" in p                   # 인용형식
    assert "거절" in p                  # 범위 게이트


def test_prompt_grounded_search_priority():
    p = audit.audit_system_prompt("grounded")
    assert "한국공인회계사회" in p or "한공회" in p   # 검색 1순위
    assert "법제처" in p                              # 법령 원문
    assert "WebSearch" in p


def test_prompt_domain_accuracy_guards():
    """스펙 §11.2 도메인 정확성 함정 반영 확인."""
    p = audit.audit_system_prompt("fast")
    assert "재편" in p or "R400" in p   # IESBA 재편번호 함정
    assert "ISQM" in p                  # 품질관리 세대교체


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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd c:\Claude\WAT && python -m pytest tests/test_audit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'audit'`

- [ ] **Step 3: audit.py 작성** — accounting.py 구조 복제, 도메인 교체

Create `WAT/audit.py` (전체):

```python
"""WAT 감사·윤리기준 AI Q&A — 핵심 로직.

accounting.py 구조를 복제하고 도메인(범위·인용형식·검색우선순위·framework)만 교체.
server.py가 import해 /api/audit/* SSE 라우트에 배선한다. Flask 비의존 → 단위테스트 용이.
"""
import re

MAX_QUESTION_LEN = 4000
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def validate_question(q):
    if not isinstance(q, str):
        raise ValueError("question must be string")
    q = q.strip()
    if not q:
        raise ValueError("question is empty")
    if len(q) > MAX_QUESTION_LEN:
        raise ValueError(f"question exceeds {MAX_QUESTION_LEN} chars")
    return q


def validate_conversation_id(cid):
    if not isinstance(cid, str) or not _UUID_RE.match(cid):
        raise ValueError("invalid conversationId (uuid required)")
    return cid


import sqlite3
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS audit_conv (
                 id            TEXT PRIMARY KEY,
                 session_id    TEXT,
                 created_at    TEXT NOT NULL,
                 last_used_at  TEXT NOT NULL
               )"""
        )
        con.commit()
    finally:
        con.close()


def get_session_id(db_path, conv_id):
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT session_id FROM audit_conv WHERE id = ?", (conv_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def upsert_session(db_path, conv_id, session_id):
    now = _now()
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """INSERT INTO audit_conv (id, session_id, created_at, last_used_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 session_id = excluded.session_id,
                 last_used_at = excluded.last_used_at""",
            (conv_id, session_id, now, now),
        )
        con.commit()
    finally:
        con.close()


_BASE_PROMPT = (
    "당신은 회계감사기준(KSA·ISA)·공인회계사 윤리기준·관련 법령(공인회계사법·"
    "외부감사법) 전문가다. 한국어로 답한다.\n"
    "- 범위 제한(중요): 회계감사·감사품질관리·공인회계사 윤리·독립성·"
    "공인회계사법·외부감사법(주식회사 등의 외부감사에 관한 법률)·내부회계관리제도"
    "(ICFR) 감사/검토·감독(감리) 관련 질문에만 답하라. 무관한 질문(프로그래밍·"
    "일반상식·시사·잡담·순수 세무·순수 회계처리 등)은 답하지 말고 한 문장으로"
    " 정중히 거절하라:\n"
    "  '본 도구는 감사기준·윤리기준·관련 법령 질의응답 전용입니다. 관련 질문을"
    " 입력해 주세요.'\n"
    "  (회계감사 맥락의 회계기준 질문 — 예: '감사인이 보는 수익인식 위험' — 은"
    " 감사 관점에서 답해도 된다.)\n"
    "- 불필요한 서두·인사말 없이 곧바로 [결론]부터 시작하라.\n"
    "- 답변 길이는 질문에 맞춰 조절: 단순 길찾기(예: '핵심감사사항은 어느"
    " 기준서?')는 핵심만 2~4줄. 해석/적용 질문은 [결론] -> [근거 기준·조문] ->"
    " [적용 논리] -> [유의사항] 구조로 상세히(마지막 유의사항까지 끊김 없이 완결).\n"
    "- 인용 형식(정확히 표기):\n"
    "  · 감사기준: 'KSA NNN 문단 N'(예: KSA 240 문단 32), 국제기준 병기 시"
    " '(ISA 240)'. 한국은 ISA를 채택(KSA 200~810)했으나 한국 미채택 조항을"
    " 채택분인 양 단정하지 마라.\n"
    "  · 품질관리: 'ISQM 1 문단 N'(2022년 ISQC 1 대체 — 구 ISQC로 답하지 마라),"
    " 한공회 채택본은 '품질관리기준(KQM/KQCS)'.\n"
    "  · 윤리: '한공회 윤리기준 제N조' / IESBA 'Code 섹션 NNN'. 단 IESBA Code는"
    " 2018년 전면 재편(restructured)됐다 — 옛 290번대 독립성 번호는 현행"
    " Part 4A/4B(R400·R600번대 등)로 바뀌었으니 현행 재편 번호를 우선하고,"
    " 불확실하면 단정 말고 원문 확인을 권고하라.\n"
    "  · 법령: '공인회계사법 제N조 제N항', '외부감사법 제N조', '동법 시행령"
    " 제N조'. 공회법·외감법은 개정이 잦으니(외감법 2018 전부개정 '신외감법')"
    " 조문번호가 불확실하면 단정 말고 정밀검색·원문 확인을 권고하라.\n"
    "- 교차 사안 통합: 독립성 위반처럼 윤리규정·외감법·감사기준에 동시 걸리는"
    " 사안은 영역을 쪼개지 말고 관련 조문을 모두 인용해 통합 답변하라.\n"
    "- 답변은 마크다운(제목 ##, 굵게 **, 표)으로 구조화. 수식은 LaTeX 대신 일반"
    " 텍스트로.\n"
    "- 조문·기준서 번호를 정확히 제시하고, 확실치 않으면 단정하지 말고 '원문"
    " 확인 권고'로 명시하라.\n"
    "- 한국 회계·감사 용어를 정확히: 장부가(O)/도서가(X), 핵심감사사항(KAM),"
    " 계속기업, 독립성 등.\n"
    "- 답변 끝에 반드시: '본 답변은 참고용이며 최종 판단과 책임은 사용자에게"
    " 있습니다.'"
)

_MODE_SUFFIX = {
    "fast": (
        "\n- [응답 모드: 빠른답변] 보유 지식으로 즉시 답하되 기준서·조문 번호를"
        " 정확히 제시하라. 핵심이 불확실할 때만 WebSearch를 1회 사용하고 과도한"
        " 재검색은 금지한다."
        "\n- (무결성) 검색하지 않았으므로 구체적 출처 URL을 임의로 생성하지 마라."
        " 링크가 필요하면 'URL은 정밀검색 모드에서 확인'이라고만 안내하라."
        "\n- (정확성) 법령 조문번호·윤리코드 번호는 개정·재편으로 기억과 다를 수"
        " 있다. 기준서 번호(예: KSA 701)는 비교적 확실하나 세부 문단·조문 번호가"
        " 불확실하면 추측하지 말고 기준서·법령 수준으로만 제시하고 '🔍정밀검색"
        " 확인 권고'를 명시하라. 특히 IESBA 재편 번호와 공회법·외감법 개정 조문은"
        " 오류 위험이 크다."
    ),
    "grounded": (
        "\n- [응답 모드: 정밀검색] **답변을 작성하기 전에 반드시 먼저 WebSearch를"
        " 호출하라.** 검색 없이 답변 시작은 금지된다. 핵심 근거 확보에 필요한"
        " 만큼(1회 이상, 최대 3~4회) 검색하라. 검색·신뢰 우선순위:\n"
        "  ① 한국공인회계사회(한공회) 윤리위·감사기준위 질의회신·적용지침\n"
        "  ② 금융감독원 감리지적사례·회계감독, 증선위/감리위 결정\n"
        "  ③ 법령 원문 — 공인회계사법·외부감사법·시행령/규칙(법제처 국가법령정보)\n"
        "  ④ 금융위원회 외감법 유권해석\n"
        "  ⑤ IAASB·IESBA 국제감사기준·윤리기준 원문\n"
        " 관련 질의회신이 있으면 번호·제목과 직접 접속 가능한 출처 URL(전체"
        " https, 실제 확인된 것만)을 답변에 명시하라.\n"
        "- 검색을 마치면 추가 검색 없이 답변을 시작해 **끝까지 완결**하라.\n"
        "- 실제로 WebSearch를 하지 않은 경우 출처 URL을 임의로 만들지 말고"
        " 조문번호로만 근거를 제시하라(미검증 URL 생성 금지)."
    ),
}
ANSWER_MODES = set(_MODE_SUFFIX)


def validate_mode(mode):
    return mode if mode in _MODE_SUFFIX else "fast"


def audit_system_prompt(mode):
    return _BASE_PROMPT + _MODE_SUFFIX[validate_mode(mode)]


# 적용 영역 토글 — 질문에 prefix 주입(매 턴 적용, --resume 무관)
FRAMEWORKS = {
    "auto": "",
    "audit": "[적용 영역: 회계감사기준(KSA/ISA)·품질관리기준(ISQM) 한정. "
             "이 영역으로만 답하라.] ",
    "ethics_law": "[적용 영역: 공인회계사 윤리기준·공인회계사법·외부감사법 한정. "
                  "이 영역으로만 답하라.] ",
}


def validate_framework(framework):
    """알 수 없는 값은 'auto'로 관대 처리(차단보다 기본동작 우선)."""
    return framework if framework in FRAMEWORKS else "auto"


def apply_framework(question, framework):
    """검증된 질문에 적용영역 지시를 prefix. auto면 원문 그대로."""
    return FRAMEWORKS[validate_framework(framework)] + question


def build_command(question, session_id, workdir, framework="auto", mode="fast"):
    question = apply_framework(question, framework)
    effort = "low" if validate_mode(mode) == "fast" else "medium"
    cmd = [
        "claude", "-p", question,
        "--setting-sources", "project,local",
        "--system-prompt", audit_system_prompt(mode),
        "--allowedTools", "WebSearch",
        "--permission-mode", "default",
        "--add-dir", workdir,
        "--model", "claude-sonnet-4-6",
        "--effort", effort,
        "--exclude-dynamic-system-prompt-sections",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


import json as _json


def parse_stream_line(line):
    """stream-json 한 줄 -> SSE 이벤트 dict 또는 None(무시). accounting.py와 동일."""
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = _json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    t = obj.get("type")

    if t == "stream_event":
        delta = (obj.get("event") or {}).get("delta") or {}
        if delta.get("type") == "text_delta":
            txt = delta.get("text", "")
            if txt:
                return {"type": "token", "text": txt}
        return None

    if t == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "tool")
                return {"type": "tool", "label": f"{name} 실행 중…"}
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        joined = "".join(texts).strip()
        if joined:
            return {"type": "assistant_text", "text": joined}
        return None

    if t == "result":
        return {
            "type": "done",
            "sessionId": obj.get("session_id"),
            "text": obj.get("result", ""),
        }

    if t == "system" and obj.get("subtype") == "init":
        return {"type": "session", "sessionId": obj.get("session_id")}

    return None


import os
import shutil
import subprocess
import tempfile
import threading

_SEM = threading.Semaphore(3)
SUBPROC_TIMEOUT = 150


def resolve_claude():
    """직접 실행 가능한 claude 실행파일 경로. 없으면 None. accounting.py와 동일."""
    override = os.environ.get("WAT_CLAUDE_PATH", "").strip()
    if override and os.path.exists(override):
        return override
    p = shutil.which("claude")
    if not p:
        return None
    if os.name == "nt" and p.lower().endswith((".cmd", ".bat")):
        exe = os.path.join(
            os.path.dirname(p),
            "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe",
        )
        if os.path.exists(exe):
            return exe
    return p


def _default_runner(cmd):
    """실제 claude 실행. stdout 라인 순차 yield. timeout 시 kill."""
    exe = resolve_claude()
    if exe:
        cmd = [exe] + cmd[1:]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", bufsize=1,
    )
    timer = threading.Timer(SUBPROC_TIMEOUT, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            yield line
    finally:
        timer.cancel()
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait()


def ask_stream(db_path, conv_id, question, framework="auto", mode="fast", runner=None):
    """검증→세션조회→실행→파싱→이벤트 yield→세션저장. accounting.py와 동일 골격.

    framework: 'auto'|'audit'|'ethics_law' — 적용 영역.
    mode: 'fast'|'grounded'.
    """
    runner = runner or _default_runner
    try:
        conv_id = validate_conversation_id(conv_id)
        question = validate_question(question)
    except ValueError as e:
        yield {"type": "error", "message": str(e)}
        return

    session_id = get_session_id(db_path, conv_id)
    final_session = session_id

    acquired = _SEM.acquire(timeout=SUBPROC_TIMEOUT)
    if not acquired:
        yield {"type": "error", "message": "서버 혼잡 — 잠시 후 재시도"}
        return

    workdir = None
    try:
        workdir = tempfile.mkdtemp(prefix="wat_audit_")
        cmd = build_command(question, session_id, workdir, framework, mode)
        streamed_any = False
        last_full = ""
        for line in runner(cmd):
            ev = parse_stream_line(line)
            if ev is None:
                continue
            etype = ev["type"]
            if etype in ("session", "done") and ev.get("sessionId"):
                final_session = ev["sessionId"]
            if etype == "session":
                continue
            if etype == "assistant_text":
                last_full = ev["text"]
                continue
            if etype == "token":
                streamed_any = True
            if etype == "done":
                if not streamed_any and not (ev.get("text") or "").strip() and last_full:
                    ev = {**ev, "text": last_full, "type": "token"}
                    yield ev
                    yield {"type": "done", "sessionId": final_session, "text": last_full}
                    continue
            yield ev
    finally:
        _SEM.release()
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        if final_session:
            upsert_session(db_path, conv_id, final_session)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd c:\Claude\WAT && python -m pytest tests/test_audit.py -q`
Expected: PASS (전체 통과)

- [ ] **Step 5: 커밋**

```bash
git add WAT/audit.py WAT/tests/test_audit.py
git commit -m "feat(audit): 감사·윤리기준 AI 핵심 로직 (accounting 구조 복제·도메인 교체)"
```

---

## Task 2: server.py 라우트 배선

**Files:**
- Modify: `WAT/server.py`
- Test: `WAT/tests/test_server_audit.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `WAT/tests/test_server_audit.py`:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd c:\Claude\WAT && python -m pytest tests/test_server_audit.py -q`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'AUDIT_DB'` 또는 404

- [ ] **Step 3: server.py 수정**

`WAT/server.py`의 `import accounting` 줄(13행) 아래에 추가:

```python
import audit
```

`ACCOUNTING_DB = ...` 줄(17행) 아래에 추가:

```python
AUDIT_DB = str(ROOT / "data" / "audit.db")
```

`accounting.init_db(ACCOUNTING_DB)` 줄(36행) 아래에 추가:

```python
audit.init_db(AUDIT_DB)
```

`api_accounting_ask` 라우트 함수(124~138행) 전체 블록 **아래에** 새 라우트 추가:

```python
@app.route("/api/audit/ask", methods=["POST"])
def api_audit_ask():
    body = request.get_json(silent=True) or {}
    conv_id = body.get("conversationId")
    question = body.get("question")
    framework = body.get("framework", "auto")
    mode = body.get("mode", "fast")
    if not conv_id or not question:
        return jsonify({"error": "conversationId와 question 필수"}), 400

    def generate():
        for ev in audit.ask_stream(AUDIT_DB, conv_id, question, framework, mode):
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return app.response_class(generate(), mimetype="text/event-stream")
```

`healthz` 라우트(141~148행)의 반환 dict에 `claude_cli` 줄 아래 키 추가:

```python
        "audit_db": "ready",
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd c:\Claude\WAT && python -m pytest tests/test_server_audit.py tests/test_server_accounting.py -q`
Expected: PASS (audit 신규 + accounting 회귀 둘 다 통과)

- [ ] **Step 5: 커밋**

```bash
git add WAT/server.py WAT/tests/test_server_audit.py
git commit -m "feat(audit): /api/audit/ask SSE 라우트 + healthz audit 표시"
```

---

## Task 3: audit/index.html UI (CSS 복사 + 읽기가능 JS)

**Files:**
- Create: `WAT/audit/index.html`

> accounting JS는 난독화돼 문자열 치환 불가 → CSS는 그대로, JS는 동일 동작의 읽기 가능한 새 버전으로 작성. localStorage 키 `audit_*`, 엔드포인트 `/api/audit/ask`, 토글 `[자동/감사기준/윤리·법령]`.

- [ ] **Step 1: `<style>` 블록 복사 추출**

Run (CSS만 추출 확인):
`cd c:\Claude\WAT && python -c "import re; s=open('accounting/index.html',encoding='utf-8').read(); i=s.index('<style>'); j=s.index('</style>')+8; print(len(s[i:j]))"`
Expected: 0보다 큰 길이 출력(style 블록 존재). 이 `<style>…</style>` 구간을 다음 단계 파일에 그대로 붙여넣는다.

- [ ] **Step 2: audit/index.html 작성**

Create `WAT/audit/index.html`. `<head>`의 `<style>…</style>`는 **Step 1에서 확인한 `accounting/index.html`의 `<style>…</style>` 전체를 그대로 복사**해 넣고(디자인 토큰·WAT 임베드 셸 표준 유지), 나머지 골격은 아래대로:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>감사·윤리기준 AI · WAT</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
<!-- ↓↓↓ 여기에 accounting/index.html의 <style>…</style> 전체를 그대로 복사해 넣는다 ↓↓↓ -->
<style>
/* accounting/index.html의 <style> 내용 전체 복사 */
</style>
</head>
<body>
<header>
  <div class="htop">
    <h1>감사·윤리기준 <span>AI</span> · 감사기준 · 윤리 · 공회법/외감법</h1>
    <button id="newChat" type="button">+ 새 대화</button>
  </div>
  <div class="seg-row">
    <div class="fw-seg" id="fwSeg" role="group" aria-label="적용 영역 선택">
      <button type="button" data-fw="auto">자동 판단</button>
      <button type="button" data-fw="audit">감사기준</button>
      <button type="button" data-fw="ethics_law">윤리·법령</button>
    </div>
    <div class="fw-seg" id="modeSeg" role="group" aria-label="응답 모드 선택">
      <button type="button" data-mode="fast" title="지식 기반 즉답 (~수초)">⚡ 빠른답변</button>
      <button type="button" data-mode="grounded" title="웹 검색·질의회신 출처 링크 (~수십초)">🔍 정밀검색</button>
    </div>
  </div>
</header>
<div id="stream"></div>
<form id="askForm">
  <textarea id="q" rows="1" placeholder="감사기준·윤리·법령 질문을 입력하세요 (Shift+Enter 줄바꿈)"></textarea>
  <button id="send" type="submit">질문</button>
</form>
<footer><span><b>Disclaimer.</b> 본 도구는 감사 실무 보조용 참고자료이며, 최종 판단과 책임은 사용자에게 있습니다. · 조문번호는 원문 확인 권고</span><span class="right">© 2026 Woongcpa</span></footer>
<script>
const API = "/api/audit/ask";
const LS = { conv: "audit_conv_id", fw: "audit_framework", mode: "audit_mode" };

function uuid() {
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}

let convId = localStorage.getItem(LS.conv);
if (!convId) { convId = uuid(); localStorage.setItem(LS.conv, convId); }

let framework = localStorage.getItem(LS.fw) || "auto";
const fwSeg = document.getElementById("fwSeg");
function paintFw() {
  fwSeg.querySelectorAll("button").forEach(b =>
    b.classList.toggle("on", b.dataset.fw === framework));
}
fwSeg.addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  framework = b.dataset.fw;
  localStorage.setItem(LS.fw, framework);
  paintFw();
});
paintFw();

let mode = localStorage.getItem(LS.mode) || "fast";
const modeSeg = document.getElementById("modeSeg");
function paintMode() {
  modeSeg.querySelectorAll("button").forEach(b =>
    b.classList.toggle("on", b.dataset.mode === mode));
}
modeSeg.addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  mode = b.dataset.mode;
  localStorage.setItem(LS.mode, mode);
  paintMode();
});
paintMode();

function renderMd(text) {
  let html;
  try { html = window.marked ? marked.parse(text, { gfm: true, breaks: true }) : null; }
  catch (e) { html = null; }
  if (html == null)
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  if (window.DOMPurify) html = DOMPurify.sanitize(html);
  return html;
}

const streamEl = document.getElementById("stream");
const form = document.getElementById("askForm");
const qEl = document.getElementById("q");
const sendBtn = document.getElementById("send");

function addMsg(who, role) {
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.innerHTML = '<div class="who">' + who + '</div><div class="bubble"></div>';
  streamEl.appendChild(el);
  streamEl.scrollTop = streamEl.scrollHeight;
  return el.querySelector(".bubble");
}

qEl.addEventListener("input", () => {
  qEl.style.height = "auto";
  qEl.style.height = Math.min(qEl.scrollHeight, 140) + "px";
});
qEl.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});
document.getElementById("newChat").addEventListener("click", () => {
  convId = uuid();
  localStorage.setItem(LS.conv, convId);
  streamEl.innerHTML = "";
});

form.addEventListener("submit", async e => {
  e.preventDefault();
  const q = qEl.value.trim();
  if (!q) return;
  addMsg("나", "user").textContent = q;
  qEl.value = "";
  qEl.style.height = "auto";
  sendBtn.disabled = true;

  const usedMode = mode;
  const bubble = addMsg("AI", "ai");
  let chip = document.createElement("div");
  chip.className = "chip";
  chip.textContent = "준비 중…";
  bubble.parentNode.insertBefore(chip, bubble);

  try {
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversationId: convId, question: q, framework, mode }),
    });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", acc = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        const dataLine = part.split("\n").find(l => l.startsWith("data: "));
        if (!dataLine) continue;
        const ev = JSON.parse(dataLine.slice(6));
        if (ev.type === "tool") {
          chip.textContent = ev.label;
        } else if (ev.type === "token") {
          chip.remove();
          acc += ev.text;
          bubble.textContent = acc;
        } else if (ev.type === "done") {
          chip.remove();
          if (ev.text) acc = ev.text;
          bubble.classList.add("md");
          bubble.innerHTML = renderMd(acc);
          bubble.querySelectorAll("a").forEach(a => {
            a.target = "_blank";
            a.rel = "noopener noreferrer";
          });
          if (usedMode === "fast") {
            const note = document.createElement("div");
            note.className = "note";
            note.textContent = "⚡ 빠른답변 — 조문·코드 번호는 정밀검색으로 확인 권고";
            bubble.parentNode.appendChild(note);
          }
        } else if (ev.type === "error") {
          chip.remove();
          bubble.textContent = "⚠ " + ev.message;
        }
        streamEl.scrollTop = streamEl.scrollHeight;
      }
    }
  } catch (err) {
    chip.remove();
    bubble.textContent = "⚠ 통신 오류: " + err.message;
  } finally {
    sendBtn.disabled = false;
  }
});
</script>
</body>
</html>
```

- [ ] **Step 3: HTML 구조 검증**

Run: `cd c:\Claude\WAT && python -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('audit/index.html',encoding='utf-8').read()); print('parse OK')"`
Expected: `parse OK` (파싱 에러 없음)

검증 항목(수동): `<style>` 블록이 비어있지 않고 accounting CSS가 들어갔는지, `/api/audit/ask`·`audit_conv_id`·data-fw 토글 3개(auto/audit/ethics_law) 존재 확인.

- [ ] **Step 4: 커밋**

```bash
git add WAT/audit/index.html
git commit -m "feat(audit): 감사·윤리기준 AI UI 탭 (CSS 승계 + 읽기가능 JS, 영역 토글)"
```

---

## Task 4: 통합 점검 · 골든질문 수동 검증

**Files:** (없음 — 가동 점검)

- [ ] **Step 1: 전체 테스트 회귀**

Run: `cd c:\Claude\WAT && python -m pytest -q`
Expected: PASS (audit·accounting·server 전부)

- [ ] **Step 2: 서버 기동 + healthz**

서버 재기동(메모리 [[feedback_auto_restart_server]]): 기존 WAT 서버 프로세스 종료 후
`cd c:\Claude\WAT && python run_server.py` (백그라운드), 그 다음:
Run: `curl -s http://localhost:8765/healthz`
Expected: JSON에 `"status":"ok"`, `"audit_db":"ready"`, `"claude_cli":"present"`

- [ ] **Step 3: 골든질문 수동 검증** (스펙 §11.5 — 사용자가 답 직접 판단)

브라우저 `http://localhost:8765/audit/`에서 정밀검색 모드로 질의:

| 질문 | 기대 (의도대로면 통과) |
|---|---|
| 감사인 독립성 — 비감사용역 제한 근거는? | 윤리규정 + 외부감사법(비감사용역 조항) **교차 인용** |
| 핵심감사사항(KAM) 기준서? | KSA 701 |
| 부정에 대한 감사인 책임? | KSA 240 |
| 파이썬으로 정렬 코드 짜줘 | 범위 게이트 **거절** 문구 |

- [ ] **Step 4: 범위 게이트·거울관계 확인**

"감사인이 보는 수익인식 위험" 질의 → 거절하지 않고 감사 관점 답변(거울관계 정상).

- [ ] **Step 5: 최종 커밋(필요 시 문구·프롬프트 미세조정 반영)**

```bash
git add -A WAT/
git commit -m "test(audit): 통합 회귀·골든질문 수동검증 통과"
```

---

## Self-Review (작성자 점검 완료)

- **스펙 커버리지**: §2 범위→Task1 `_BASE_PROMPT`·게이트 / §3 배치→Task1·2·3 파일 / §4 토글→Task1 `FRAMEWORKS`+Task3 UI / §5 인용형식→Task1 프롬프트+test_prompt_scope_tokens / §6 검색우선순위→Task1 grounded suffix+test_prompt_grounded_search_priority / §7 모드→Task1 `_MODE_SUFFIX` / §8 에러→Task1 `ask_stream` / §9 테스트→Task1·2·4 / §11.2 도메인정확성→Task1 프롬프트(IESBA재편·ISQM·신외감법·KSA매핑)+test_prompt_domain_accuracy_guards / §11.3 ICFR·감리 포함→Task1 게이트 문구 / §11.5 골든질문→Task4.
- **Placeholder 스캔**: audit/index.html `<style>`만 "복사" 지시(난독화 회피 위해 의도적, 출처·범위 명시). 그 외 모든 코드 완전 기재.
- **타입·시그니처 일관성**: 함수명·인자(framework/mode 기본값) accounting.py와 동일, 라우트 `AUDIT_DB`·`audit.ask_stream` 일치, localStorage 키·data-fw 값(auto/audit/ethics_law) UI↔백엔드 `FRAMEWORKS` 키 일치 확인.
