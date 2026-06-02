"""WAT 계열 툴 서버 워치독 — 죽은 서버 자동 복구.

배경: pythonw(무콘솔) 기동 시 Flask dev server가 SSE 스트리밍+subprocess 상호작용에서
간헐적으로 하드 크래시(traceback 없이 프로세스 사망 → 포트 닫힘 → '안 열린다').
근본원인 규명이 어렵고 간헐적이라, healthz 폴링 후 죽으면 부팅 VBS로 재기동하는
경량 supervisor로 self-healing 처리한다.

각 툴은 부팅 Startup VBS가 정상 기동을 담당하고, 본 워치독은 '죽었을 때만' 재기동한다
(idempotent — 살아있으면 아무것도 안 함). 자신도 Startup VBS로 무콘솔 상주.
"""
import os
import sys
import time
import subprocess
import urllib.request

# pythonw 무콘솔 stdout 가드 (None이면 로그파일로)
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_watchdog.log"),
                "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

_STARTUP = os.path.join(
    os.environ.get("APPDATA", ""),
    r"Microsoft\Windows\Start Menu\Programs\Startup",
)

# port -> (healthz 경로, 부팅 VBS 파일명). 죽으면 wscript로 VBS 재실행.
TOOLS = {
    8765: ("/healthz", "WAT_Server.vbs"),     # WAT 통합(회계기준·감사윤리 AI)
    8533: ("/healthz", "RISK_Server.vbs"),    # Risk Tool
    8766: ("/healthz", "BC_Server.vbs"),      # BC 조회서
    5000: ("/healthz", "RCPS_Server.vbs"),    # RCPS 평가
}

CHECK_INTERVAL = 20      # 초
TIMEOUT = 4              # healthz 요청 타임아웃
GRACE_AFTER_RELAUNCH = 12  # 재기동 후 다음 점검까지 유예


def _alive(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=TIMEOUT) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def _relaunch(vbs):
    path = os.path.join(_STARTUP, vbs)
    if not os.path.exists(path):
        print(f"[watchdog] VBS 없음: {path}", flush=True)
        return False
    try:
        subprocess.Popen(["wscript.exe", path], close_fds=True)
        print(f"[watchdog] 재기동: {vbs}", flush=True)
        return True
    except Exception as e:
        print(f"[watchdog] 재기동 실패 {vbs}: {e}", flush=True)
        return False


def main():
    print(f"[watchdog] 시작 — {len(TOOLS)}개 서버 감시 (interval={CHECK_INTERVAL}s)", flush=True)
    while True:
        relaunched = False
        for port, (path, vbs) in TOOLS.items():
            if not _alive(port, path):
                print(f"[watchdog] DOWN port {port} → {vbs} 재기동", flush=True)
                if _relaunch(vbs):
                    relaunched = True
        time.sleep(GRACE_AFTER_RELAUNCH if relaunched else CHECK_INTERVAL)


if __name__ == "__main__":
    main()
