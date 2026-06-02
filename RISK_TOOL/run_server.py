import os
import sys
import pathlib

_ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(_ROOT / "src"))


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
