# BC 은행조회서 자동화 Tool
4150 조서(금융기관 조회) 자동 작성.
- Sampling: G/L → 금융기관 추출 (B/S + P/L)
- Cross-check: 회사 CS · 전기 · 월보 · 담보·보증 · 주소
- 회신본 PDF (온라인·우편) 파싱
- AC0~AC10 셀 자동 fill (원본 양식 보존, Toss 색감)
- WAT 임베드

## 실행
```
uv sync
python run_server.py
```
포트 8765, http://127.0.0.1:8765
