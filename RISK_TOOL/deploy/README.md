# RISK_TOOL 배포·자동시작

## 부팅 자동시작 (Windows)
`deploy/RISK_Server.vbs`를 시작프로그램 폴더에 복사:
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`

- pythonw.exe(무콘솔)로 `run_server.py` 실행 → port 8533.
- `run_server.py`가 (1) `RISK_TOOL/.env`에서 `DART_API_KEY`(선택 `NAVER_CLIENT_ID/SECRET`) 로드, (2) pythonw에서 stdout None일 때 `_server.log`로 리다이렉트(uvicorn worker 사망 방지).

## 환경변수 (.env, gitignore됨)
```
DART_API_KEY=...        # 필수 — DART OPEN API 키
NAVER_CLIENT_ID=...     # 선택 — 뉴스 검색(없으면 뉴스 degrade)
NAVER_CLIENT_SECRET=...
```

## 수동 기동
`cd C:\Claude\RISK_TOOL && python run_server.py` → http://127.0.0.1:8533/

## WAT 런처 연동
WAT 셸(`WAT/src/index.html`)에 `risk-precheck` 등록됨(로컬 :8533 / 원격 TS_HOST:8533).
원격 접속하려면 :8533을 Tailscale 등으로 노출 필요(현재 로컬만).
