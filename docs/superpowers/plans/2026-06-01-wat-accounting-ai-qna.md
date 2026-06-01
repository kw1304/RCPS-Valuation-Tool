# WAT 회계기준 AI Q&A 툴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WAT 허브에 회계기준 해석/적용 대화형 AI Q&A 카드를 추가한다 — 로컬 `claude` CLI를 headless로 호출해 WebSearch 근거로 답하고, SSE로 스트리밍하며, SQLite로 대화 세션을 매핑한다.

**Architecture:** WAT Flask 서버(`server.py`)에 `/api/accounting/ask` SSE 엔드포인트를 추가한다. 핵심 로직은 별도 모듈 `accounting.py`에 격리(입력검증·SQLite 세션매핑·claude 명령조립·stream-json 파싱·오케스트레이션). claude는 `--bare`로 사용자 훅/플러그인을 차단(caveman 누출 방지)하고 `--allowedTools WebSearch`로 도구를 제한해 원격 명령실행을 막는다. 프론트는 `src/accounting/index.html`(WAT 디자인토큰)로 만들고 난독화 빌드로 `accounting/index.html` 서빙본을 생성한다.

**Tech Stack:** Python 3.14, Flask, sqlite3(표준), pytest, subprocess, Server-Sent Events, claude CLI 2.1.x headless, Node.js javascript-obfuscator(기존 빌드).

---

## 실측으로 확정된 사실 (구현 전 필독)

`claude -p ... --output-format stream-json --verbose` 실제 출력에서 확인:

- stream-json은 **라인당 JSON 객체 1개**(JSONL). 관련 타입:
  - `{"type":"system","subtype":"init",...,"session_id":"<sid>"}` — 첫 실질 이벤트, session_id 보유
  - `{"type":"system","subtype":"hook_started"|"hook_response",...}` — **훅 노이즈, 무시**
  - `{"type":"assistant","message":{"content":[{"type":"text","text":"..."}|{"type":"tool_use","name":"WebSearch",...}]}, "session_id":"..."}`
  - `{"type":"rate_limit_event",...}` — **무시**
  - `{"type":"user",...}` — tool_result, **무시**
  - `{"type":"result","subtype":"success","result":"<최종답변>","session_id":"<sid>"}` — 종료
- `--output-format stream-json`은 `--verbose` 필수 (없으면 `Error: ... requires --verbose`)
- **`--bare`** = "Minimal mode: skip hooks, LSP, plugin" → 서버 호출 시 사용자 SessionStart 훅(caveman 등) 차단. WebSearch는 빌트인이라 유지됨
- session_id는 `system/init`과 `result` 둘 다에 있음 → `result`의 것을 우선 저장
- 토큰단위 델타는 MVP 범위 외(메시지 단위 스트리밍으로 충분)

### 확정 claude 명령 (구현 기준)
```
claude -p <question>
  --bare
  --system-prompt <ACCOUNTING_SYSTEM_PROMPT>
  --allowedTools WebSearch
  --permission-mode default
  --add-dir <빈 임시폴더>
  --output-format stream-json --verbose
  [--resume <session_id>]      # 후속 턴만
```
- `--dangerously-skip-permissions` 절대 미사용
- `--system-prompt`(전체 교체) 사용 — 회계 전문가 프롬프트로 통제

---

## 파일 구조

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `WAT/accounting.py` | 입력검증·SQLite 세션·명령조립·stream 파싱·ask 오케스트레이션 | 신규 |
| `WAT/server.py` | `/api/accounting/ask` SSE 라우트 + healthz 확장 배선 | 수정 |
| `WAT/data/accounting.db` | 세션매핑 SQLite (런타임 생성, gitignore) | 런타임 |
| `WAT/src/accounting/index.html` | 채팅 UI + SSE 클라이언트 + localStorage | 신규 |
| `WAT/accounting/index.html` | 난독화 서빙본 (빌드 산출) | 빌드 |
| `WAT/build/obfuscate.mjs` | accounting 타깃 추가 | 수정 |
| `WAT/src/index.html` | 리서치 카드 + TOOLS 레지스트리 | 수정 |
| `WAT/index.html` | 난독화 서빙본 재생성 | 빌드 |
| `WAT/.gitignore` | `data/*.db` 추가 | 수정 |
| `WAT/requirements.txt` | flask, pytest 명시 | 신규 |
| `WAT/tests/test_accounting.py` | accounting.py 단위테스트 | 신규 |
| `WAT/tests/test_server_accounting.py` | 라우트/ healthz 테스트 | 신규 |
| `WAT/tests/conftest.py` | pytest 픽스처(임시 DB) | 신규 |

`accounting.py`를 분리하는 이유: `server.py`는 정적서빙+ECOS만 담당하던 얇은 파일. 회계 로직을 섞으면 비대해지고 테스트가 어려움. subprocess·DB·파싱을 한 모듈에 모아 Flask 없이도 단위테스트 가능하게 함.

---

## Task 1: 테스트 스캐폴딩 + requirements

**Files:**
- Create: `WAT/requirements.txt`
- Create: `WAT/tests/__init__.py`
- Create: `WAT/tests/conftest.py`
- Modify: `WAT/.gitignore`

- [ ] **Step 1: requirements.txt 작성**

Create `WAT/requirements.txt`:
```
flask>=3.0
pytest>=8.0
```

- [ ] **Step 2: .gitignore에 DB 제외 추가**

`WAT/.gitignore` (기존 1줄 `WAT/build/node_modules/` 유지하고 추가):
```
WAT/build/node_modules/
data/
__pycache__/
.pytest_cache/
```

- [ ] **Step 3: tests 패키지 + conftest 작성**

Create `WAT/tests/__init__.py` (빈 파일).

Create `WAT/tests/conftest.py`:
```python
import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """임시 SQLite 경로. 각 테스트 격리."""
    return str(tmp_path / "accounting_test.db")
```

- [ ] **Step 4: pytest 수집 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/ -q`
Expected: `no tests ran` (collected 0 items) — 에러 없이 수집만 동작

- [ ] **Step 5: Commit**

```bash
git add WAT/requirements.txt WAT/tests/__init__.py WAT/tests/conftest.py WAT/.gitignore
git commit -m "test(wat): 회계 Q&A 툴 pytest 스캐폴딩 + requirements"
```

---

## Task 2: 입력 검증 (validate_question, validate_conversation_id)

**Files:**
- Create: `WAT/accounting.py`
- Test: `WAT/tests/test_accounting.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `WAT/tests/test_accounting.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounting'`

- [ ] **Step 3: 최소 구현**

Create `WAT/accounting.py`:
```python
"""WAT 회계기준 AI Q&A — 핵심 로직 (검증·세션·명령조립·파싱·오케스트레이션).

server.py가 이 모듈을 import해 SSE 라우트에 배선한다.
Flask 비의존 → 단위테스트 용이.
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add WAT/accounting.py WAT/tests/test_accounting.py
git commit -m "feat(wat): 회계 Q&A 입력검증 (질문 길이·conversationId uuid)"
```

---

## Task 3: SQLite 세션 매핑 (init_db, get_session_id, upsert_session)

**Files:**
- Modify: `WAT/accounting.py`
- Test: `WAT/tests/test_accounting.py`

- [ ] **Step 1: 실패 테스트 추가**

Append to `WAT/tests/test_accounting.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: FAIL — `AttributeError: module 'accounting' has no attribute 'init_db'`

- [ ] **Step 3: 구현 추가**

Append to `WAT/accounting.py`:
```python
import sqlite3
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path):
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS accounting_conv (
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
            "SELECT session_id FROM accounting_conv WHERE id = ?", (conv_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def upsert_session(db_path, conv_id, session_id):
    now = _now()
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """INSERT INTO accounting_conv (id, session_id, created_at, last_used_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 session_id = excluded.session_id,
                 last_used_at = excluded.last_used_at""",
            (conv_id, session_id, now, now),
        )
        con.commit()
    finally:
        con.close()
```

- [ ] **Step 4: 통과 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add WAT/accounting.py WAT/tests/test_accounting.py
git commit -m "feat(wat): 회계 Q&A SQLite 세션매핑 (init/get/upsert)"
```

---

## Task 4: claude 명령 조립 (build_command)

**Files:**
- Modify: `WAT/accounting.py`
- Test: `WAT/tests/test_accounting.py`

- [ ] **Step 1: 실패 테스트 추가**

Append to `WAT/tests/test_accounting.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: FAIL — `AttributeError: ... 'build_command'`

- [ ] **Step 3: 구현 추가**

Append to `WAT/accounting.py`:
```python
ACCOUNTING_SYSTEM_PROMPT = (
    "당신은 K-IFRS·일반기업회계기준·회계감사기준 전문가다. 한국어로 답한다.\n"
    "- 질문은 해석/적용이 주다. 결론만 말하지 말고 다음 구조로 답하라:\n"
    "  [결론] -> [근거 기준서·조문] -> [적용 논리] -> [유의사항]\n"
    "- 반드시 WebSearch로 근거를 확인한 뒤 조문번호·출처를 제시하라.\n"
    "  검색으로 확인 못 하면 단정하지 말고 '원문 확인 권고'로 명시하라.\n"
    "- 범위: K-IFRS(제1xxx호·해석서), 일반기업회계기준, 회계감사기준(ISA).\n"
    "  세무 영향은 '회계 관점 한정'임을 밝히고 단정하지 마라.\n"
    "- 한국 회계용어를 정확히: 장부가(O)/도서가(X), 공정가치, 무위험이자율 등.\n"
    "- 답변 끝에 반드시: '본 답변은 참고용이며 최종 판단과 책임은 사용자에게 있습니다.'"
)


def build_command(question, session_id, workdir):
    cmd = [
        "claude", "-p", question,
        "--bare",
        "--system-prompt", ACCOUNTING_SYSTEM_PROMPT,
        "--allowedTools", "WebSearch",
        "--permission-mode", "default",
        "--add-dir", workdir,
        "--output-format", "stream-json",
        "--verbose",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd
```

- [ ] **Step 4: 통과 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add WAT/accounting.py WAT/tests/test_accounting.py
git commit -m "feat(wat): 회계 Q&A claude 명령조립 (--bare·WebSearch-only·시스템프롬프트)"
```

---

## Task 5: stream-json 라인 파싱 (parse_stream_line)

실측 스키마 기반. `assistant`(text/tool_use)·`result`·`system/init`만 의미있는 이벤트로 변환, 나머지는 `None`.

**Files:**
- Modify: `WAT/accounting.py`
- Test: `WAT/tests/test_accounting.py`

- [ ] **Step 1: 실패 테스트 추가**

Append to `WAT/tests/test_accounting.py`:
```python
import json


def test_parse_assistant_text():
    line = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "리스는 K-IFRS 1116"}]},
        "session_id": "s1",
    })
    ev = accounting.parse_stream_line(line)
    assert ev == {"type": "token", "text": "리스는 K-IFRS 1116"}


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
```

- [ ] **Step 2: 실패 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: FAIL — `AttributeError: ... 'parse_stream_line'`

- [ ] **Step 3: 구현 추가**

Append to `WAT/accounting.py`:
```python
import json as _json


def parse_stream_line(line):
    """stream-json 한 줄 -> SSE 이벤트 dict 또는 None(무시).

    실측 스키마 기준. None이면 호출측이 건너뛴다.
    """
    line = (line or "").strip()
    if not line:
        return None
    try:
        obj = _json.loads(line)
    except (ValueError, TypeError):
        return None

    t = obj.get("type")

    if t == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                name = block.get("name", "tool")
                return {"type": "tool", "label": f"{name} 실행 중…"}
        joined = "".join(texts).strip()
        if joined:
            return {"type": "token", "text": joined}
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
```

- [ ] **Step 4: 통과 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: PASS (19 passed)

- [ ] **Step 5: Commit**

```bash
git add WAT/accounting.py WAT/tests/test_accounting.py
git commit -m "feat(wat): 회계 Q&A stream-json 파서 (실측 스키마, 훅노이즈 필터)"
```

---

## Task 6: ask 오케스트레이션 (ask_stream 제너레이터 + 세마포어)

검증→세션조회→subprocess 실행→라인별 파싱→이벤트 yield→세션 저장. subprocess는 주입 가능한 `runner` 인자로 빼서 테스트에서 가짜 스트림 주입.

**Files:**
- Modify: `WAT/accounting.py`
- Test: `WAT/tests/test_accounting.py`

- [ ] **Step 1: 실패 테스트 추가**

Append to `WAT/tests/test_accounting.py`:
```python
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
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "답변 본문"}]}}),
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: FAIL — `AttributeError: ... 'ask_stream'`

- [ ] **Step 3: 구현 추가**

Append to `WAT/accounting.py`:
```python
import os
import subprocess
import tempfile
import threading

_SEM = threading.Semaphore(3)        # 동시 claude 프로세스 최대 3
SUBPROC_TIMEOUT = 90


def _default_runner(cmd):
    """실제 claude 실행. stdout 라인을 순차 yield. timeout 시 kill."""
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


def ask_stream(db_path, conv_id, question, runner=None):
    """검증→세션조회→실행→파싱→이벤트 yield→세션저장.

    yield하는 각 항목은 SSE로 보낼 dict. runner는 테스트 주입용.
    """
    runner = runner or _default_runner
    try:
        conv_id = validate_conversation_id(conv_id)
        question = validate_question(question)
    except ValueError as e:
        yield {"type": "error", "message": str(e)}
        return

    session_id = get_session_id(db_path, conv_id)
    workdir = tempfile.mkdtemp(prefix="wat_acct_")
    cmd = build_command(question, session_id, workdir)

    final_session = session_id
    acquired = _SEM.acquire(timeout=SUBPROC_TIMEOUT)
    if not acquired:
        yield {"type": "error", "message": "서버 혼잡 — 잠시 후 재시도"}
        return
    try:
        for line in runner(cmd):
            ev = parse_stream_line(line)
            if ev is None:
                continue
            if ev["type"] in ("session", "done") and ev.get("sessionId"):
                final_session = ev["sessionId"]
            if ev["type"] == "session":
                continue  # 내부용, 프론트로는 안 보냄
            yield ev
    finally:
        _SEM.release()
        try:
            os.rmdir(workdir)
        except OSError:
            pass
        if final_session:
            upsert_session(db_path, conv_id, final_session)
```

- [ ] **Step 4: 통과 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_accounting.py -q`
Expected: PASS (22 passed)

- [ ] **Step 5: Commit**

```bash
git add WAT/accounting.py WAT/tests/test_accounting.py
git commit -m "feat(wat): 회계 Q&A ask 오케스트레이션 (세마포어·세션저장·timeout)"
```

---

## Task 7: server.py 배선 — SSE 라우트 + healthz 확장

**Files:**
- Modify: `WAT/server.py`
- Test: `WAT/tests/test_server_accounting.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `WAT/tests/test_server_accounting.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/test_server_accounting.py -q`
Expected: FAIL — `/api/accounting/ask` 404 또는 healthz에 claude_cli 없음

- [ ] **Step 3: server.py 수정**

`WAT/server.py` 상단 import 영역에 추가 (기존 `from pathlib import Path` 아래):
```python
import shutil
import accounting
```

`PORT = ...` 아래에 DB 경로 상수 추가:
```python
ACCOUNTING_DB = str(ROOT / "data" / "accounting.db")
```

`app = Flask(...)` 아래에 DB 초기화:
```python
(ROOT / "data").mkdir(exist_ok=True)
accounting.init_db(ACCOUNTING_DB)
```

`@app.route("/healthz")` 함수의 반환 dict에 `claude_cli` 키 추가:
```python
@app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "ecos_local": bool(ECOS_KEY),
        "source": "ECOS-local" if ECOS_KEY else "Render-fallback",
        "claude_cli": "present" if shutil.which("claude") else "absent",
    })
```

`@app.route("/healthz")` 위에 새 라우트 추가:
```python
@app.route("/api/accounting/ask", methods=["POST"])
def api_accounting_ask():
    body = request.get_json(silent=True) or {}
    conv_id = body.get("conversationId")
    question = body.get("question")
    if not conv_id or not question:
        return jsonify({"error": "conversationId와 question 필수"}), 400

    def generate():
        for ev in accounting.ask_stream(ACCOUNTING_DB, conv_id, question):
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return app.response_class(generate(), mimetype="text/event-stream")
```

- [ ] **Step 4: 통과 확인**

Run: `cd /c/Claude/WAT && python -m pytest tests/ -q`
Expected: PASS (전체 25 passed)

- [ ] **Step 5: Commit**

```bash
git add WAT/server.py WAT/tests/test_server_accounting.py
git commit -m "feat(wat): /api/accounting/ask SSE 라우트 + healthz claude_cli 노출"
```

---

## Task 8: 프론트엔드 — 채팅 UI + SSE 클라이언트

**Files:**
- Create: `WAT/src/accounting/index.html`

WAT 디자인토큰(`src/index.html`의 `:root` 변수)을 동일 적용. 채팅형 단일 페이지. `fetch` + `ReadableStream`으로 SSE 수신(POST라 EventSource 불가).

- [ ] **Step 1: HTML/CSS/JS 작성**

Create `WAT/src/accounting/index.html`:
```html
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>회계기준 AI · WAT</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
:root{
  --bg:#F9FAFB;--bg2:#FFFFFF;--bg3:#F2F4F6;--border:#E5E8EB;
  --accent:#3182F6;--accent2:#1B64DA;--text:#191F28;--text2:#4E5968;--text3:#8B95A1;
  --sans:'Pretendard',-apple-system,BlinkMacSystemFont,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--text);font-family:var(--sans);
  font-size:14px;display:flex;flex-direction:column;height:100vh}
header{padding:1rem 1.4rem;background:var(--bg2);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between}
header h1{font-size:1rem;font-weight:800;letter-spacing:-0.02em}
header h1 span{color:var(--accent)}
header button{font-family:inherit;font-size:.74rem;font-weight:600;color:var(--text2);
  background:var(--bg3);border:1px solid var(--border);border-radius:100px;
  padding:.4rem .9rem;cursor:pointer}
header button:hover{color:var(--accent);border-color:#BFDBFE;background:#EFF6FF}
#stream{flex:1;overflow-y:auto;padding:1.4rem;display:flex;flex-direction:column;gap:1rem}
.msg{max-width:780px;width:100%;margin:0 auto;display:flex;flex-direction:column;gap:.4rem}
.msg .who{font-size:.68rem;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.05em}
.msg.user .bubble{background:var(--accent);color:#fff;align-self:flex-end;border-radius:14px 14px 4px 14px}
.msg.ai .bubble{background:var(--bg2);border:1px solid var(--border);border-radius:14px 14px 14px 4px}
.bubble{padding:.85rem 1.1rem;line-height:1.65;white-space:pre-wrap;word-break:break-word}
.bubble a{color:var(--accent)}
.chip{display:inline-flex;align-items:center;gap:.4rem;font-size:.72rem;font-weight:600;
  color:var(--accent);background:#EFF6FF;border:1px solid #BFDBFE;border-radius:100px;
  padding:.3rem .7rem;align-self:flex-start}
form{padding:1rem 1.4rem;background:var(--bg2);border-top:1px solid var(--border);
  display:flex;gap:.7rem;align-items:flex-end}
textarea{flex:1;font-family:inherit;font-size:.9rem;line-height:1.5;resize:none;
  border:1.5px solid var(--border);border-radius:12px;padding:.7rem .9rem;max-height:140px}
textarea:focus{outline:none;border-color:var(--accent)}
form button{font-family:inherit;font-weight:700;color:#fff;background:var(--accent);
  border:0;border-radius:12px;padding:.7rem 1.3rem;cursor:pointer}
form button:disabled{background:var(--text3);cursor:not-allowed}
footer{padding:.5rem 1.4rem;background:var(--bg2);border-top:1px solid var(--border);
  font-size:.64rem;color:var(--text3);text-align:center}
</style>
</head>
<body>
<header>
  <h1>회계기준 <span>AI</span> · K-IFRS 질의응답</h1>
  <button id="newChat" type="button">+ 새 대화</button>
</header>
<div id="stream"></div>
<form id="askForm">
  <textarea id="q" rows="1" placeholder="회계기준 해석/적용 질문을 입력하세요 (Shift+Enter 줄바꿈)"></textarea>
  <button id="send" type="submit">질문</button>
</form>
<footer>본 답변은 참고용이며 최종 판단과 책임은 사용자에게 있습니다. · 검색 근거 기반 · 조문번호는 원문 확인 권고</footer>
<script>
function uuid(){
  return ('10000000-1000-4000-8000-100000000000').replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}
let convId = localStorage.getItem('acct_conv_id');
if(!convId){ convId = uuid(); localStorage.setItem('acct_conv_id', convId); }

const streamEl = document.getElementById('stream');
const form = document.getElementById('askForm');
const qEl = document.getElementById('q');
const sendBtn = document.getElementById('send');

function addMsg(who, cls){
  const m = document.createElement('div');
  m.className = 'msg ' + cls;
  m.innerHTML = '<div class="who">' + who + '</div><div class="bubble"></div>';
  streamEl.appendChild(m);
  streamEl.scrollTop = streamEl.scrollHeight;
  return m.querySelector('.bubble');
}

qEl.addEventListener('input', () => {
  qEl.style.height = 'auto'; qEl.style.height = Math.min(qEl.scrollHeight, 140) + 'px';
});
qEl.addEventListener('keydown', e => {
  if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); form.requestSubmit(); }
});
document.getElementById('newChat').addEventListener('click', () => {
  convId = uuid(); localStorage.setItem('acct_conv_id', convId);
  streamEl.innerHTML = '';
});

form.addEventListener('submit', async e => {
  e.preventDefault();
  const question = qEl.value.trim();
  if(!question) return;
  addMsg('나', 'user').textContent = question;
  qEl.value = ''; qEl.style.height = 'auto';
  sendBtn.disabled = true;

  const aiBubble = addMsg('회계기준 AI', 'ai');
  let chip = document.createElement('span'); chip.className = 'chip'; chip.textContent = '🔍 분석 준비 중…';
  aiBubble.parentElement.insertBefore(chip, aiBubble);

  try{
    const resp = await fetch('/api/accounting/ask', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ conversationId: convId, question }),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while(true){
      const { value, done } = await reader.read();
      if(done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n'); buf = parts.pop();
      for(const part of parts){
        const dataLine = part.split('\n').find(l => l.startsWith('data: '));
        if(!dataLine) continue;
        const ev = JSON.parse(dataLine.slice(6));
        if(ev.type === 'tool'){ chip.textContent = '🔍 ' + ev.label; }
        else if(ev.type === 'token'){ chip.remove(); aiBubble.textContent += ev.text; }
        else if(ev.type === 'done'){ chip.remove(); if(ev.text) aiBubble.textContent = ev.text; }
        else if(ev.type === 'error'){ chip.remove(); aiBubble.textContent = '⚠ ' + ev.message; }
        streamEl.scrollTop = streamEl.scrollHeight;
      }
    }
  }catch(err){
    chip.remove(); aiBubble.textContent = '⚠ 통신 오류: ' + err.message;
  }finally{
    sendBtn.disabled = false;
  }
});
</script>
</body>
</html>
```

- [ ] **Step 2: 정적 서빙 수동 확인 (서버 재기동)**

Run:
```bash
cd /c/Claude/WAT && python server.py &
sleep 2
curl -s http://127.0.0.1:8765/healthz
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/src/accounting/index.html
```
Expected: healthz JSON에 `"claude_cli":"present"`, accounting 페이지 `200`.

- [ ] **Step 3: Commit**

```bash
git add WAT/src/accounting/index.html
git commit -m "feat(wat): 회계 Q&A 프론트 (채팅 UI·SSE 스트리밍·localStorage 세션)"
```

---

## Task 9: 난독화 빌드에 accounting 타깃 추가

**Files:**
- Modify: `WAT/build/obfuscate.mjs:13-16`

- [ ] **Step 1: TARGETS 배열에 항목 추가**

`WAT/build/obfuscate.mjs`의 TARGETS를 다음으로 교체:
```javascript
const TARGETS = [
  { src: resolve(root, 'src/index.html'),            out: resolve(root, 'index.html') },
  { src: resolve(root, 'src/irs/index.html'),        out: resolve(root, 'irs/index.html') },
  { src: resolve(root, 'src/accounting/index.html'), out: resolve(root, 'accounting/index.html') },
];
```

- [ ] **Step 2: 빌드 실행**

Run:
```bash
cd /c/Claude/WAT/build && node obfuscate.mjs
```
Expected: 3줄 `[OK] ... -> ...  (inline scripts obfuscated: N)`, 그 중
`src/accounting/index.html -> .../accounting/index.html (inline scripts obfuscated: 1)`

- [ ] **Step 3: 산출본 문법 확인 (서빙본 로드)**

Run:
```bash
cd /c/Claude/WAT && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/accounting/
```
Expected: `200` (디렉토리→index.html 자동매핑). 서버 미실행 시 `python server.py &` 먼저.

- [ ] **Step 4: Commit**

```bash
git add WAT/build/obfuscate.mjs WAT/accounting/index.html
git commit -m "build(wat): 난독화 파이프라인에 회계 Q&A 페이지 추가"
```

---

## Task 10: WAT 카드 등록 — 리서치 카드 + TOOLS 레지스트리

**Files:**
- Modify: `WAT/src/index.html` (카드 마크업 + JS 레지스트리)

- [ ] **Step 1: 리서치 카테고리 카드 추가**

`WAT/src/index.html`의 `.cat-grid` 안, 감사보조 카드(`<!-- Audit Support -->` 블록) **뒤**에 추가:
```html
    <!-- Reference -->
    <div class="cat-card cat-reference" data-cat="reference">
      <div class="ico">R</div>
      <h3>리서치 <span class="en">Reference</span></h3>
      <p class="desc">회계기준 해석·적용 질의응답. K-IFRS·일반기업회계기준·회계감사기준을 웹 근거로 검색해 조문·출처와 함께 답합니다.</p>
      <div class="tool-list">
        <a class="tool-item" href="#tool=accounting-ai" data-tool="accounting-ai">
          <span>회계기준 AI · K-IFRS 질의응답</span>
          <span class="tag ready">사용 가능</span>
        </a>
      </div>
    </div>
```

- [ ] **Step 2: 리서치 카드 아이콘 색상 추가**

`WAT/src/index.html`의 `<style>` 안 `.cat-audit .ico{...}` 줄 **아래**에 추가:
```css
.cat-reference .ico{background:linear-gradient(135deg,#00C2B3,#0E9F8E)}
```

- [ ] **Step 3: TOOLS 레지스트리에 항목 추가**

`WAT/src/index.html`의 `const TOOLS = {` 객체에서 `'bc-confirmation'` 항목 뒤에 추가:
```javascript
  'accounting-ai': {
    name: '회계기준 AI · K-IFRS 질의응답',
    category: 'Reference',
    url: '/accounting/',
  },
```

- [ ] **Step 4: 소스 직접 로드로 카드/네비 동작 확인**

Run:
```bash
cd /c/Claude/WAT && curl -s "http://127.0.0.1:8765/src/index.html" | grep -c "accounting-ai"
```
Expected: `2` (카드 href + TOOLS 레지스트리).

- [ ] **Step 5: 루트 서빙본 재빌드**

Run:
```bash
cd /c/Claude/WAT/build && node obfuscate.mjs
```
Expected: 3 OK 줄, `src/index.html -> .../index.html` 포함.

- [ ] **Step 6: Commit**

```bash
git add WAT/src/index.html WAT/index.html
git commit -m "feat(wat): 리서치 카드 + 회계기준 AI 툴 레지스트리 등록"
```

---

## Task 11: 엔드투엔드 수동 검증 (실제 claude 호출 1회)

실제 quota를 쓰므로 마지막에 1회만. caveman 누출 없는지(=`--bare` 효과), WebSearch 동작, 한국어 회계 답변·세션 이어짐 확인.

**Files:** 없음 (검증 전용)

- [ ] **Step 1: 서버 재기동 + healthz**

Run:
```bash
cd /c/Claude/WAT && (pkill -f "server.py" 2>/dev/null; sleep 1; python server.py &) ; sleep 2
curl -s http://127.0.0.1:8765/healthz
```
Expected: `"claude_cli":"present"`.

- [ ] **Step 2: 실제 질문 1건 (SSE)**

Run:
```bash
curl -s -N -X POST http://127.0.0.1:8765/api/accounting/ask \
  -H "Content-Type: application/json" \
  -d '{"conversationId":"550e8400-e29b-41d4-a716-446655440000","question":"운용리스와 금융리스 구분 기준은 K-IFRS에서 어떻게 되나?"}' | head -40
```
Expected (확인 항목):
- `event: tool` (WebSearch 실행) 1회 이상 등장
- `event: token` 또는 최종 `event: done`에 한국어 회계 답변
- 답변에 **caveman 말투/영어 hook 텍스트 없음** (=`--bare` 정상)
- 답변 끝 "참고용…" disclaimer
- `done` 이벤트에 `sessionId` 존재

- [ ] **Step 3: 후속 질문 세션 이어짐 확인**

Run:
```bash
curl -s -N -X POST http://127.0.0.1:8765/api/accounting/ask \
  -H "Content-Type: application/json" \
  -d '{"conversationId":"550e8400-e29b-41d4-a716-446655440000","question":"방금 답변에서 리스기간 판단은?"}' | grep -m1 "event:"
```
Expected: 정상 스트림 시작(맥락 유지). SQLite에 같은 conv_id로 session 갱신.

- [ ] **Step 4: 보안 확인 — 도구 화이트리스트**

Run:
```bash
sqlite3 /c/Claude/WAT/data/accounting.db "SELECT id, session_id FROM accounting_conv;"
```
Expected: 1행, session_id 채워짐. (`accounting.py` 명령에 `--allowedTools WebSearch`만, `--dangerously-skip-permissions` 없음 — Task 4 테스트로 이미 보장)

- [ ] **Step 5: 전체 테스트 재확인 + 최종 커밋**

Run: `cd /c/Claude/WAT && python -m pytest tests/ -q`
Expected: PASS (25 passed).

```bash
git add -A WAT/
git commit -m "test(wat): 회계 Q&A E2E 수동검증 완료 — bare 격리·WebSearch·세션이어짐 확인"
```

---

## Self-Review (작성자 점검 결과)

**Spec 커버리지:**
- §3 아키텍처 → Task 6,7 (SSE·세마포어·SQLite) ✅
- §4.1 엔드포인트/이벤트(token/tool/done/error) → Task 5,7 ✅
- §4.2 SQLite 스키마 → Task 3 ✅
- §4.3 보안(WebSearch-only, no skip-perms, add-dir, 길이제한, timeout) → Task 2,4,6 ✅ (+ `--bare`로 훅격리 강화 — 실측 반영)
- §4.4 동시성 세마포어(3) → Task 6 ✅
- §5 시스템 프롬프트 → Task 4 (ACCOUNTING_SYSTEM_PROMPT) ✅
- §6 프론트(채팅·SSE·localStorage·새대화·disclaimer) → Task 8 ✅
- §7 WAT 카드(리서치 카테고리·TOOLS) → Task 10 ✅
- §8 제약(로컬전용·healthz claude_cli) → Task 7 ✅
- §10 성공기준(스트리밍·세션이어짐·보안·healthz) → Task 11 검증 ✅

**Placeholder 스캔:** 모든 코드 스텝에 실제 코드 포함. TBD/TODO 없음.

**타입 일관성:** 이벤트 dict 키(`type`,`text`,`label`,`sessionId`,`message`) Task 5·6·7·8 전체 일치. `ask_stream(db_path, conv_id, question, runner=)` 시그니처 Task 6 정의 = Task 7 호출 일치. `build_command(question, session_id, workdir)` Task 4 정의 = Task 6 호출 일치.

**실측 반영 차이(spec 대비):** spec §4는 `--append-system-prompt`였으나 실측 결과 사용자 훅(caveman) 누출·cold-start 비용 확인 → `--bare` + `--system-prompt`(전체교체)로 강화. 보안·정확도 모두 개선이므로 채택.
