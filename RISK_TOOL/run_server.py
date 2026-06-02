import os
import sys
import pathlib

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT / "src"))

# pythonw(콘솔 없음)·부팅 VBS 기동 시 sys.stdout/stderr가 None → uvicorn 로그 write가
# AttributeError로 worker를 죽인다(프로세스는 살아있고 포트는 미바인딩). 로그파일로 리다이렉트.
if sys.stdout is None or sys.stderr is None:
    _log = open(_ROOT / "_server.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def _load_env(path: pathlib.Path) -> None:
    """간단 .env 로더 — KEY=VALUE 라인. 이미 설정된 환경변수는 덮지 않음."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and not os.environ.get(k):
            os.environ[k] = v


_load_env(_ROOT / ".env")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    _key = "set" if os.environ.get("DART_API_KEY") else "MISSING"
    print(f"=== RISK_TOOL 기동 (port 8533, DART_API_KEY={_key}) ===", flush=True)
    uvicorn.run("risk.interface.api.app:app", host="127.0.0.1", port=8533, reload=False)
