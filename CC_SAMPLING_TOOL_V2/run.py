"""CC Sampling Tool V2 — standalone 실행 엔트리.

사용: python run.py        (기본 포트 8530)
      CC_PORT=8531 python run.py
v1=8520 · WAT=9090 회피해 8530 기본.
"""
from __future__ import annotations
import os

from api.app import create_app


def main() -> None:
    port = int(os.environ.get("CC_PORT", "8530"))
    host = os.environ.get("CC_HOST", "127.0.0.1")
    app = create_app()
    print(f"CC Sampling Tool V2 → http://{host}:{port}/")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
