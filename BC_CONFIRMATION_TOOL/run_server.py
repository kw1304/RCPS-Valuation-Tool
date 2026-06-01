import os
import sys

# pythonw(콘솔 없음)·부팅 VBS 기동 시 sys.stdout/stderr가 None → uvicorn 로그 write가
# AttributeError로 worker를 죽인다(프로세스는 살아있고 포트는 미바인딩). 로그파일로 리다이렉트.
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_server.log"),
                "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import uvicorn

if __name__ == "__main__":
    # reload=False — Windows에서 multiprocessing worker가 좀비로 남아 port 잡는 문제 회피
    # 코드 수정 후엔 _restart_server.ps1로 명시적 재기동
    uvicorn.run("api.app:app", host="127.0.0.1", port=8766, reload=False)
