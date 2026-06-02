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
    " 조문번호가 불확실하면 단정 말고 정밀검색·원문 확인을 권고하라. 한 답변 안에서"
    " 같은 제도·개념의 조문번호는 반드시 일관되게 인용하라(예: '손해배상책임'을"
    " 한 곳은 제N조, 다른 곳은 제M조로 다르게 적지 말 것).\n"
    "  · 기준서 개정 시행일: 개정 기준서의 적용 시점은 '~이후 개시하는 회계연도'와"
    " '~이후 종료하는 회계연도'를 혼동하기 쉽고 연도 자체도 기억 오류가 잦으니,"
    " 시행일을 단정하기 전에 정밀검색·원문 확인을 권고하라(예: ISA/KSA 600 개정).\n"
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
        "\n- (법령 조문 엄격) 검색하지 않은 상태에서 외감법·공회법·시행령의 구체"
        " 조문번호(제N조)를 단정하지 마라. 번호를 적을 때는 반드시 '🔍' 표시를"
        " 동반하거나 조문명(예: 손해배상책임 조항)으로만 인용하고, 한 답변 내"
        " 동일 개념의 조문번호가 서로 어긋나지 않게 하라."
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
