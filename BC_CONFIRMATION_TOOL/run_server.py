import os
import sys
import time
import socket
import subprocess
import urllib.request

# pythonw(콘솔 없음)·부팅 VBS 기동 시 sys.stdout/stderr가 None -> uvicorn 로그 write가
# AttributeError로 worker를 죽인다(프로세스는 살아있고 포트는 미바인딩). 로그파일로 리다이렉트.
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_server.log"),
                "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import uvicorn

PORT = 8766
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _serving():
    """이미 정상 서빙 중이면 True(중복 기동 방지)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=2) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def _port_free():
    """8766 바인딩 가능하면 True. 좀비가 점유 중이면 False."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _kill_port_owner():
    """8766을 LISTENING으로 점유한 좀비 프로세스 종료(Windows netstat→taskkill)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, creationflags=_NOWIN,
        ).stdout or ""
    except Exception:
        return
    mypid = str(os.getpid())
    pids = set()
    for line in out.splitlines():
        if f":{PORT} " in line and "LISTENING" in line.upper():
            pid = line.split()[-1]
            if pid.isdigit() and pid != mypid:
                pids.add(pid)
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"],
                           capture_output=True, creationflags=_NOWIN)
            print(f"=== 좀비 정리: PID {pid} 종료 ===", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    # 1) 이미 정상 기동돼 있으면 중복 인스턴스 즉시 종료(싱글톤).
    if _serving():
        print(f"=== 이미 기동됨(port {PORT}) - 중복 실행 종료 ===", flush=True)
        sys.exit(0)
    # 2) 응답은 없는데 포트만 잡힌 좀비 -> 정리 후 바인딩 가능해질 때까지 대기.
    if not _port_free():
        print(f"=== port {PORT} 좀비 점유 감지 -> 정리 ===", flush=True)
        _kill_port_owner()
        for _ in range(10):
            time.sleep(1)
            if _port_free():
                break
    # reload=False - Windows에서 multiprocessing worker가 좀비로 남아 port 잡는 문제 회피
    uvicorn.run("api.app:app", host="127.0.0.1", port=PORT, reload=False)
