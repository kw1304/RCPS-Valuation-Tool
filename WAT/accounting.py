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


_BASE_PROMPT = (
    "당신은 K-IFRS·일반기업회계기준·회계감사기준 전문가다. 한국어로 답한다.\n"
    "- 범위 제한(중요): 회계기준(K-IFRS·일반기업회계기준)·회계감사·재무보고 관련\n"
    "  질문에만 답하라. 회계·감사와 무관한 질문(프로그래밍·코딩·일반상식·시사·잡담·\n"
    "  타 분야 등)은 답하지 말고, 한 문장으로 정중히 거절하라:\n"
    "  '본 도구는 회계기준·회계감사 질의응답 전용입니다. 회계·감사 관련 질문을 입력해 주세요.'\n"
    "  (회계처리의 세무 영향 등 회계와 직접 연관된 인접 주제는 회계 관점에서 답해도 된다.)\n"
    "- 불필요한 서두·인사말 없이 곧바로 [결론]부터 시작하라.\n"
    "- 답변 길이는 질문에 맞춰 조절하라: 단순 사실확인·길찾기(예: '리스는 어느"
    "  기준서?')는 핵심만 2~4줄로 간결히. 해석/적용 질문은 아래 구조로 상세히:\n"
    "  [결론] -> [근거 기준서·조문] -> [적용 논리] -> [유의사항]\n"
    "  (상세 답변은 마지막 유의사항·disclaimer까지 끊김 없이 완결하라.)\n"
    "- 인용 형식: K-IFRS는 '제1xxx호 문단 N', 일반기업회계기준은 '제○장 문단 ○.○',\n"
    "  감사기준은 'KSA NNN 문단 N' 형식으로 표기하라.\n"
    "- 답변은 마크다운(제목 ##, 굵게 **, 표, 코드블록)으로 구조화하라.\n"
    "  단 수식은 LaTeX($$, \\(...\\), \\text 등)를 쓰지 말고 일반 텍스트로 표현하라\n"
    "  (예: '영업권 = 이전대가 − 식별가능순자산 공정가치').\n"
    "- 자주 혼동되는 사항 주의(확정 사실):\n"
    "  · 감가상각방법 변경(예: 정액→정률)은 회계정책 변경이 아니라 **회계추정\n"
    "    변경(전진적용)**이다(K-IFRS 제1016호 문단 61, 제1008호).\n"
    "  · 유형자산 재평가모형: K-IFRS(제1016호)는 허용하나, **일반기업회계기준\n"
    "    (제10장)은 허용하지 않는다(원가모형만)** — 둘 다 허용한다고 답하지 마라.\n"
    "  · 분류가 결론을 좌우하는 질문(정책/추정/오류 구분 등)은 특히 신중히 판단하고,\n"
    "    단정이 어려우면 정밀검색 확인을 권고하라. 특히 일반기업회계기준(K-GAAP)의\n"
    "    세부 처리는 K-IFRS와 다른 경우가 많으니 불확실하면 단정 대신 정밀검색 권고.\n"
    "- 조문번호·기준서 번호를 정확히 제시하고, 확실치 않으면 단정하지 말고\n"
    "  '원문 확인 권고'로 명시하라.\n"
    "- WebSearch 사용 시 우선순위: ① 한국회계기준원(KASB) 질의회신(Q&A) 사례,\n"
    "  ② kifrs.or.kr 기준서·해석서 원문, ③ 금융감독원 회계포털·감리지적사례.\n"
    "  관련 질의회신이 있으면 질의회신 번호·제목과 직접 접속 가능한 출처 URL을\n"
    "  답변에 그대로(전체 https URL) 포함하라.\n"
    "- 적용 회계기준 구분(중요):\n"
    "  · 질문 앞에 '[적용 회계기준: …]' 지시가 있으면 그 기준으로만 답하라.\n"
    "  · 지시가 없으면(자동) 먼저 적용 기준을 판단해 밝히고, K-IFRS와\n"
    "    일반기업회계기준의 처리가 다르면 두 기준을 [K-IFRS]·[일반기업회계기준]\n"
    "    소제목으로 나눠 각각 제시하라(상장·외감은 K-IFRS, 비상장 중소기업은 일반).\n"
    "- 범위: K-IFRS(제1xxx호·해석서), 일반기업회계기준, 회계감사기준(ISA).\n"
    "  세무 영향은 '회계 관점 한정'임을 밝히고 단정하지 마라.\n"
    "- 한국 회계용어를 정확히: 장부가(O)/도서가(X), 공정가치, 무위험이자율 등.\n"
    "- 답변 끝에 반드시: '본 답변은 참고용이며 최종 판단과 책임은 사용자에게 있습니다.'"
)

# 응답 모드 — 속도 vs 검색근거 트레이드오프
_MODE_SUFFIX = {
    # 빠른답변: 지식 기반 즉답(~수초). 핵심 불확실할 때만 검색.
    "fast": (
        "\n- [응답 모드: 빠른답변] 보유 지식으로 즉시 답하되 기준서·조문 번호를"
        " 정확히 제시하라. 핵심이 불확실할 때만 WebSearch를 1회 사용하고"
        " 과도한 재검색은 금지한다."
        "\n- (무결성) 검색하지 않았으므로 구체적 출처 URL을 임의로 생성하지 마라."
        " 링크가 필요하면 'URL은 정밀검색 모드에서 확인' 이라고만 안내하라."
        "\n- (정확성) 조문·문단 번호와 분개·계정과목은 기억에 의존해 틀릴 수 있다."
        " 기준서 번호(예: 제1116호)는 비교적 확실하나 세부 문단 번호는 불확실하면"
        " 추측해서 적지 말고 기준서·장 수준으로만 제시하라('문단 번호는 정밀검색 확인')."
        " 특히 일반기업회계기준(K-GAAP)의 세부 조문·계정(예: 전환권조정·전환권대가)은"
        " 오류 위험이 크니 단정하지 말고, 결론·조문이 중요하면 '🔍정밀검색으로 확인 권고'를"
        " 명시하라. K-IFRS와 K-GAAP의 처리가 다른 주제는 차이를 분명히 구분하라."
    ),
    # 정밀검색: 반드시 검색해 질의회신·원문 URL 확보(~수십초).
    "grounded": (
        "\n- [응답 모드: 정밀검색] 답변 근거를 WebSearch로 확인하라. 핵심 근거 확보에"
        " 필요한 만큼(1회 이상, 최대 3~4회) 한국회계기준원 질의회신·기준 원문을"
        " 검색하고, 관련 질의회신 번호·제목과 직접 접속 가능한 출처 URL(전체 https,"
        " 검색으로 실제 확인된 것만)을 답변에 명시하라."
        "\n- **검색 과정·수행 사실을 서술하지 마라**('검색하겠습니다/검색 완료/"
        "검색 결과를 바탕으로' 등 메타문구 금지). 곧바로 [결론]부터 시작해 끝까지"
        " 완결하라(중간에 끊지 말 것)."
        "\n- 실제로 WebSearch를 수행하지 않은 경우에는 출처 URL을 임의로 만들지"
        " 말고, 조문번호로만 근거를 제시하라(미검증 URL 생성 금지)."
    ),
}
ANSWER_MODES = set(_MODE_SUFFIX)


def validate_mode(mode):
    return mode if mode in _MODE_SUFFIX else "fast"


def accounting_system_prompt(mode):
    return _BASE_PROMPT + _MODE_SUFFIX[validate_mode(mode)]


# 적용 회계기준 체계 — 질문에 prefix로 주입(매 턴 적용, --resume 무관)
FRAMEWORKS = {
    "auto": "",
    "kifrs": "[적용 회계기준: K-IFRS(한국채택국제회계기준) — 상장·외감 대상. "
             "이 기준으로만 답하라.] ",
    "kgaap": "[적용 회계기준: 일반기업회계기준 — 비상장 중소기업 대상. "
             "이 기준으로만 답하라.] ",
}


def validate_framework(framework):
    """알 수 없는 값은 'auto'로 관대 처리(차단보다 기본동작 우선)."""
    return framework if framework in FRAMEWORKS else "auto"


def apply_framework(question, framework):
    """검증된 질문에 적용기준 지시를 prefix. auto면 원문 그대로."""
    return FRAMEWORKS[validate_framework(framework)] + question


def build_command(question, session_id, workdir, framework="auto", mode="fast"):
    question = apply_framework(question, framework)
    # fast=low(추론 최소화→빠름). grounded=medium(검색 신뢰성과 지연의 균형).
    # 기초·자명한 질문은 모델이 검색을 생략할 수 있으나(합리적), 검색을 생략하면
    # URL을 만들지 않도록 프롬프트로 보장(미검증 URL 금지) → 안전.
    effort = "low" if validate_mode(mode) == "fast" else "medium"
    cmd = [
        "claude", "-p", question,
        # user 설정/플러그인 훅(예: 외부 환경의 caveman 등) 미로드 → 답변 오염 차단.
        # 구독 인증은 keychain에서 별도 로드되므로 영향 없음(--bare는 keychain까지 끊어 사용 불가).
        "--setting-sources", "project,local",
        "--system-prompt", accounting_system_prompt(mode),
        "--allowedTools", "WebSearch",
        "--permission-mode", "default",
        "--add-dir", workdir,
        # Sonnet = Opus 대비 2~3배 빠름. 회계기준 검색·요약엔 충분.
        "--model", "claude-sonnet-4-6",
        # 모드별 effort: fast=low(속도), grounded=medium(검색 신뢰성).
        "--effort", effort,
        # cwd/env/git/memory 등 머신별 섹션 제외 → 프롬프트·콜드스타트 축소.
        "--exclude-dynamic-system-prompt-sections",
        "--output-format", "stream-json",
        "--verbose",
        # 토큰 단위 실시간 스트리밍 → 대기 체감 급감(첫 토큰까지만 기다림).
        "--include-partial-messages",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


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
    if not isinstance(obj, dict):
        return None

    t = obj.get("type")

    # 부분 메시지(--include-partial-messages): 토큰 단위 실시간 스트리밍
    if t == "stream_event":
        delta = (obj.get("event") or {}).get("delta") or {}
        if delta.get("type") == "text_delta":
            txt = delta.get("text", "")
            if txt:
                return {"type": "token", "text": txt}
        return None  # thinking_delta 등은 무시

    if t == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "tool")
                return {"type": "tool", "label": f"{name} 실행 중…"}
        # 본문 텍스트: 평소엔 stream_event 델타로 전달되므로 라이브로 내보내지 않되,
        # 델타가 안 와서 토큰이 비는 경우(간헐적 빈 답변 버그)의 fallback용으로 surface.
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
            "is_error": bool(obj.get("is_error")),
        }

    if t == "system" and obj.get("subtype") == "init":
        return {"type": "session", "sessionId": obj.get("session_id")}

    return None


import os
import shutil
import subprocess
import tempfile
import threading
import time

# 상류(Anthropic API) 일시 장애 — claude CLI가 result(is_error)로 돌려주는 텍스트.
# 토큰이 하나도 안 나온 상태에서 이 패턴이면 자동 재시도(backoff) 대상.
_TRANSIENT_MARKERS = (
    "api error", "overloaded", "internal server error",
    "rate limit", "timeout", "503", "502", "500", "529",
)
_RETRY_BACKOFF = (1.5, 3.0, 6.0)     # 시도 간 대기(초). 최대 len+1회 시도.
_HEAD_GUARD = 60                     # 선두 N자까지 보류해 에러텍스트 검사 후 라이브 전환.


def _is_transient_error(text):
    s = (text or "").lower()
    return any(k in s for k in _TRANSIENT_MARKERS)


_SEM = threading.Semaphore(3)        # 동시 claude 프로세스 최대 3
# 정밀검색 다회 검색 시 90s로는 답변이 잘림(iter2 발견) → 150s로 상향.
SUBPROC_TIMEOUT = 150


def resolve_claude():
    """직접 실행 가능한 claude 실행파일 경로. 없으면 None.

    Windows에서 PATH의 `claude`는 npm 셸 래퍼(claude.CMD)라
    subprocess가 shell 없이는 못 띄운다(WinError 2). 래퍼가 호출하는
    실제 bin\\claude.exe로 풀어 shell 없이 안전하게 실행한다.

    PATH에 claude가 없는 환경(서비스 계정 등)을 위해 WAT_CLAUDE_PATH
    환경변수로 실행파일 절대경로를 직접 지정할 수 있다(최우선).
    """
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
    """실제 claude 실행. stdout 라인을 순차 yield. timeout 시 kill."""
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
    """검증→세션조회→실행→파싱→이벤트 yield→세션저장.

    framework: 'auto'|'kifrs'|'kgaap' — 적용 회계기준 체계.
    mode: 'fast'(지식 즉답)|'grounded'(검색·출처 URL) — 속도/근거 트레이드오프.
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
    final_session = session_id

    acquired = _SEM.acquire(timeout=SUBPROC_TIMEOUT)
    if not acquired:
        yield {"type": "error", "message": "서버 혼잡 — 잠시 후 재시도"}
        return

    try:
        # 상류 API 일시 장애(529/500/overload)는 토큰 전에 result(is_error)로 떨어진다.
        # 토큰이 하나도 안 나온 시점의 오류는 사용자에게 노출하지 않고 backoff 재시도.
        # 토큰을 하나라도 흘린 뒤면(live) 되돌릴 수 없으므로 그대로 둔다.
        for _attempt in range(len(_RETRY_BACKOFF) + 1):
            workdir = tempfile.mkdtemp(prefix="wat_acct_")
            try:
                cmd = build_command(question, session_id, workdir, framework, mode)
                streamed_any = False   # 실제 토큰을 흘렸는가
                live = False           # 본문 확정 → 라이브 스트리밍 중
                last_full = ""         # assistant 본문(델타 미발생 시 fallback)
                buffered = []          # 라이브 전 비-토큰 이벤트(재시도 시 폐기)
                pending = []           # 라이브 전 토큰 이벤트(head-guard로 보류)
                head = ""              # 선두 토큰 텍스트(에러 패턴 검사용)
                need_retry = False
                for line in runner(cmd):
                    ev = parse_stream_line(line)
                    if ev is None:
                        continue
                    etype = ev["type"]
                    if etype in ("session", "done") and ev.get("sessionId"):
                        final_session = ev["sessionId"]
                    if etype == "session":
                        continue  # 내부용
                    if etype == "assistant_text":
                        last_full = ev["text"]  # fallback만
                        continue
                    if etype == "token":
                        if live:
                            streamed_any = True
                            yield ev
                            continue
                        # head-guard: 선두 토큰을 잠깐 보류 → 에러텍스트면 노출 없이 재시도
                        pending.append(ev)
                        head += ev.get("text", "")
                        if _is_transient_error(head):
                            need_retry = True
                            break
                        if len(head) >= _HEAD_GUARD:   # 실제 본문 확정 → flush·라이브
                            live = True
                            for b in buffered:
                                yield b
                            buffered = []
                            for p in pending:
                                streamed_any = True
                                yield p
                            pending = []
                        continue
                    if etype == "done":
                        text = (ev.get("text") or "").strip()
                        if not live:
                            full = head.strip() or text or last_full
                            # 에러(플래그/텍스트)거나 빈 응답 → 노출 없이 재시도
                            if ev.get("is_error") or _is_transient_error(full) or not full:
                                need_retry = True
                                break
                            # 정상 짧은 응답 → 보류분 flush(없으면 본문으로 보강)
                            for b in buffered:
                                yield b
                            buffered = []
                            if pending:
                                for p in pending:
                                    streamed_any = True
                                    yield p
                                pending = []
                            else:
                                yield {"type": "token", "text": full}
                                streamed_any = True
                            yield {"type": "done", "sessionId": final_session, "text": full}
                            live = True
                            break
                        yield ev
                        break
                    # tool 등 기타: 라이브 전이면 버퍼(재시도 시 폐기)
                    if live:
                        yield ev
                    else:
                        buffered.append(ev)

                if streamed_any and not need_retry:
                    return  # 성공
                if _attempt < len(_RETRY_BACKOFF):
                    time.sleep(_RETRY_BACKOFF[_attempt])
                    continue
                # 모든 재시도 소진
                yield {"type": "error",
                       "message": "AI 서버가 일시적으로 혼잡합니다. 잠시 후 다시 시도해 주세요."}
            finally:
                if workdir:
                    shutil.rmtree(workdir, ignore_errors=True)
    finally:
        _SEM.release()
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)  # 비어있지 않아도 정리
        if final_session:
            upsert_session(db_path, conv_id, final_session)
