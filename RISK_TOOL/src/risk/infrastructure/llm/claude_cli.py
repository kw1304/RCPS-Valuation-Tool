from __future__ import annotations
import os
import shutil
import subprocess
import threading

_TIMEOUT = 120


def resolve_claude():
    """직접 실행 가능한 claude 실행파일 경로. 없으면 None. (WAT 패턴 포팅)

    Windows에서 PATH의 `claude`는 npm 셸 래퍼(claude.CMD)라 shell 없이는
    못 띄운다(WinError 2). 래퍼가 호출하는 실제 bin\\claude.exe로 풀어
    shell 없이 안전하게 실행한다. WAT_CLAUDE_PATH로 절대경로 직접 지정 가능(최우선).
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


def claude_available() -> bool:
    return resolve_claude() is not None


def claude_complete(prompt: str, model: str = "claude-sonnet-4-6",
                    timeout: int = _TIMEOUT) -> str | None:
    """claude CLI 1회 호출 → 전체 stdout 텍스트. 실패·미설치 시 None (degrade)."""
    exe = resolve_claude()
    if not exe:
        return None
    try:
        proc = subprocess.Popen(
            [exe, "-p", prompt, "--model", model],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding="utf-8", bufsize=1,
        )
    except Exception:
        return None
    killed = {"v": False}

    def _kill():
        killed["v"] = True
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    try:
        out = proc.stdout.read()
    finally:
        timer.cancel()
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait()
    if killed["v"] or not out:
        return None
    return out.strip()
