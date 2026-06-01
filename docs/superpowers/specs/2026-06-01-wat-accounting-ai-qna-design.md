# WAT 회계기준 AI Q&A 툴 — 설계 (Design Spec)

- **날짜:** 2026-06-01
- **위치:** WAT 통합 허브 (`c:\Claude\WAT`)
- **상태:** 설계 승인됨, 구현계획 대기

## 1. 목적 (Purpose)

감사 실무 중 발생하는 **회계기준 해석/적용 질문**에 대해, 웹검색으로 근거를
확인하고 조문·출처를 인용해 답하는 대화형 AI 툴. WAT 허브에 카드로 추가한다.

- 주 사용 시나리오: **해석/적용(B)** — "이 거래를 K-IFRS 1115 5단계 어디에
  넣어야 하나" 류. 단답 길찾기가 아니라 결론 + 근거조문 + 적용논리 + 유의점.
- 부차: 빠른 조회도 자연히 커버됨.
- **명시적 비목표:** 조서 문구 자동 export, 답변 평가, PDF 첨부 질의, 영구
  대화 아카이브 — 모두 v2로 분리.

## 2. 핵심 결정 (요구사항 확정)

| 항목 | 결정 |
|---|---|
| 답변 성격 | 해석/적용 위주. 구조화 답변 필수 |
| 대화 | **대화형(multi-turn)**. claude `--resume`로 맥락 유지 |
| 기준 범위 | K-IFRS + 일반기업회계기준 + 회계감사기준(ISA). **세무 제외** |
| 사용자 | **다중사용자** (Tailscale 팀 공유). 세션 분리 필요 |
| LLM | **로컬 claude CLI headless** (`claude -p`). 별도 API키·과금 0, 기존 구독 사용 |
| 근거 | **WebSearch 도구**로 실시간 검색 후 출처 인용 |
| 배포 | 로컬/Tailscale 전용 (Render엔 claude CLI 없음) |

## 3. 아키텍처

```
[브라우저: WAT 카드 → iframe /accounting/]
      │ 질문 + conversationId
      ▼  POST /api/accounting/ask  (SSE text/event-stream)
[WAT Flask server.py]
   ├ SQLite: conv(id, claude_session_id, created, last_used)
   ├ 세마포어(병렬 3) — 초과 큐 대기
   └ subprocess: claude -p [--resume <sid>] --output-format stream-json
        --append-system-prompt <회계전문가 프롬프트>
        --allowedTools WebSearch --permission-mode default
        --add-dir <빈 temp dir>
      │ stream-json stdout 라인 파싱 → SSE 이벤트
      └ 종료 시 새 session_id를 SQLite upsert
```

선택된 접근법 = **CLI 서브프로세스 + SSE 스트리밍** (Agent SDK / 단발-메모리
대안 대비). 이유: 추가 인프라 0, claude 자체 세션저장 활용, WAT 순수 Flask
컨벤션 유지, 다중사용자/긴 대기를 SSE+SQLite로 정직하게 처리.

## 4. 백엔드 상세 (`WAT/server.py` 확장)

### 4.1 엔드포인트
- **`POST /api/accounting/ask`** — body `{conversationId, question}`,
  응답 `text/event-stream`
  1. conversationId로 SQLite 조회 → `claude_session_id` 있으면 `--resume <sid>`,
     없으면 신규 세션
  2. claude subprocess를 stream-json 모드로 실행, stdout 라인별 파싱
  3. SSE 이벤트로 프론트에 흘림:
     - `{type:'token', text}` — 답변 토큰 조각
     - `{type:'tool', label}` — "웹 검색 중: <쿼리>" 등 진행 표시
     - `{type:'done', sessionId}` — 완료, 새 session_id 포함
     - `{type:'error', message}` — 실패
  4. 종료 시 session_id·last_used를 SQLite upsert
- **`/healthz` 확장** — `claude_cli: "present"|"absent"` 노출
  (`claude --version` 성공 여부)

### 4.2 SQLite 스키마
```sql
CREATE TABLE IF NOT EXISTS accounting_conv (
  id            TEXT PRIMARY KEY,   -- conversationId (클라이언트 uuid)
  session_id    TEXT,               -- claude headless session_id
  created_at    TEXT NOT NULL,
  last_used_at  TEXT NOT NULL
);
```
- DB 파일: `WAT/data/accounting.db` (없으면 생성)
- 세션 매핑만 저장. 대화 본문은 claude 자체 transcript + 브라우저
  localStorage가 보유 (서버는 본문 비보관 → 개인정보 노출 최소)

### 4.3 보안 (핵심 — 원격 명령실행 차단)
- 툴 화이트리스트 **`--allowedTools WebSearch`만**. Bash/Edit/Write/Read 전면 차단
- **`--dangerously-skip-permissions` 절대 미사용.** `--permission-mode default`
- `--add-dir <빈 임시폴더>` → 파일시스템 접근 격리 (repo 경로 노출 안 함)
- 입력 검증: 질문 길이 ≤ 4000자, conversationId는 uuid 형식 정규식 검증
- subprocess timeout 90s, 초과 시 kill + error 이벤트
- stream-json 파싱은 화이트리스트 필드만 사용 (임의 실행 경로 없음)

### 4.4 동시성
- `threading.Semaphore(3)` — 병렬 claude 프로세스 최대 3개. 초과는 큐 대기
- 목적: 다중사용자 시 프로세스 폭주 + 구독 쿼터 폭주 차단

## 5. 시스템 프롬프트 (`--append-system-prompt`)

```
당신은 K-IFRS·일반기업회계기준·회계감사기준 전문가다. 한국어로 답한다.

- 질문은 해석/적용이 주다. 결론만 말하지 말고 다음 구조로 답하라:
  [결론] → [근거 기준서·조문] → [적용 논리] → [유의사항]
- 반드시 WebSearch로 근거를 확인한 뒤 조문번호·출처를 제시하라.
  검색으로 확인 못 하면 단정하지 말고 "원문 확인 권고"로 명시하라.
- 범위: K-IFRS(제1xxx호·해석서), 일반기업회계기준, 회계감사기준(ISA).
  세무 영향은 "회계 관점 한정"임을 밝히고 단정하지 마라.
- 한국 회계용어를 정확히: 장부가(O)/도서가(X), 공정가치, 무위험이자율 등.
- 답변 끝에 반드시: "본 답변은 참고용이며 최종 판단과 책임은 사용자에게 있습니다."
```

## 6. 프론트엔드 (`WAT/src/accounting/index.html`)

- WAT 디자인토큰 그대로: Pretendard, `--accent #3182F6`, Toss풍 카드/여백
- 레이아웃: 채팅형 — 하단 고정 입력창 + 위로 쌓이는 메시지 스트림
- SSE 수신 → 토큰 실시간 마크다운 렌더. `token`/`tool`/`done`/`error` 처리
- 진행 표시: "🔍 웹 검색 중…" 상태칩 (`tool` 이벤트 기반)
- 답변 출처 링크 클릭가능(`target=_blank`), 하단 disclaimer 고정 노출
- "새 대화" 버튼 → 새 conversationId(uuid) 발급, 화면 비움
- 대화이력: 브라우저 **localStorage** 보관(가벼움). 서버는 session_id 매핑만

## 7. WAT 카드 등록 (`WAT/src/index.html`)

- 신규 3번째 카테고리 카드 **"리서치 / Reference"** (ico "R")
  - 평가·감사보조 어디에도 안 맞아 별도 카드. grid `auto-fit minmax(380px)`라
    3카드 자연 배치
- tool-item: `회계기준 AI · K-IFRS 질의응답` [사용 가능]
- JS `TOOLS` 레지스트리에 `accounting-ai` 추가:
  - `url: '/accounting/'` (IRS처럼 동일 서버 정적 경로 — 로컬/TS 분기 불필요)

## 8. 제약 / 알려진 한계

1. **로컬/Tailscale 전용** — Render엔 claude CLI 없음. healthz로 가용성 노출
2. **응답 10~30초** — CLI 기동 + 웹검색. SSE 스트리밍으로 체감 완화
3. **구독 쿼터 소모** — 동시성 cap(3)으로 폭주만 차단
4. **조문번호 100% 보장 X** — 검색결과 의존. 시스템 프롬프트 + disclaimer로 커버
5. **claude CLI 로그인 의존** — 서버 호스트에 claude 인증 상태 필요

## 9. MVP 범위 vs v2

- **MVP (본 spec):** §3~8 전부 — SSE 스트리밍, SQLite 세션매핑, 다중사용자,
  WebSearch-only 보안, WAT 카드, healthz
- **v2 (제외, YAGNI):** 대화 영구 아카이브·검색, 답변 평가(👍/👎),
  조서용 문구 export, PDF 첨부 질의, 세무 연결

## 10. 성공 기준

- 팀원이 Tailscale로 접속해 회계 해석 질문 → 10~30초 내 스트리밍 답변 +
  근거 조문·출처 표시
- 후속질문이 맥락 유지 (`--resume` 동작)
- WebSearch 외 도구 호출 불가 (보안 검증)
- 동시 3건 초과 시 큐 대기, 서버 안정
- healthz가 claude CLI 가용성 정확히 보고
