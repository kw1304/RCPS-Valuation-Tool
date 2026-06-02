"""WAT 유저세션 기동 래퍼 (Startup VBS → pythonw 무콘솔).

pythonw.exe로 띄우면 콘솔이 없어 sys.stdout/stderr가 None이 되고,
server.py의 print(...)가 AttributeError로 죽는다. 여기서 stdout/stderr를
로그파일로 돌려 가드한 뒤 Flask 앱을 직접 구동한다.

유저세션에서 돌아야 claude 구독 인증(keychain)·PATH가 살아 회계 Q&A가
동작한다(LocalSystem 서비스에선 인증 불가).
"""
import os
import sys
import urllib.request

_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wat_server.log")
_fh = open(_LOG, "a", encoding="utf-8", buffering=1)
sys.stdout = _fh
sys.stderr = _fh

import server  # noqa: E402  (stdout 가드 후 import)


def _already_serving(port):
    """이미 같은 포트에서 정상 서빙 중이면 True (중복 기동 방지)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


if __name__ == "__main__":
    # 싱글톤: 이미 떠 있으면 중복 인스턴스가 포트를 두고 충돌하지 않도록 즉시 종료.
    if _already_serving(server.PORT):
        print(f"=== 이미 기동됨(port {server.PORT}) — 중복 실행 종료 ===", flush=True)
        sys.exit(0)
    print(f"=== WAT 유저세션 기동 (port {server.PORT}) ===", flush=True)
    server.app.run(host="0.0.0.0", port=server.PORT, debug=False, use_reloader=False)
