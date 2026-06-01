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
