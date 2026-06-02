# WAT 감사·윤리기준 리서치 AI 툴 — 설계

작성: 2026-06-02
도메인: 회계감사기준(KSA/ISA)·공인회계사 윤리기준·관련 법령(공인회계사법·외부감사법)

## 1. 목적

감사실무자가 감사기준·윤리규정·관련 법령을 한 화면에서 질의응답으로 리서치하는 AI 툴.
회계기준 AI 툴(`WAT/accounting.py`)의 SSE·세션·모드·서브프로세스 아키텍처를 그대로
재사용하고, 도메인(범위·인용형식·검색 우선순위·framework 토글)만 교체한다.

회계기준 툴과 **거울 관계**: 회계기준 툴은 회계처리 중심(감사는 부수), 본 툴은 감사·윤리·
법령 중심(회계기준은 감사 맥락에서만).

## 2. 범위 (scope)

1급 범위 3축:

- **감사기준** — 회계감사기준(KSA), 국제감사기준(ISA), 품질관리기준(ISQM 1·2 / KQM·KQCS)
- **윤리기준** — 한국공인회계사회 윤리기준(윤리규정), IESBA Code of Ethics, 독립성
- **관련 법령** — 공인회계사법, 주식회사 등의 외부감사에 관한 법률(외부감사법),
  각 시행령·시행규칙

**교차질의 통합**: 독립성 위반처럼 윤리규정·외감법·감사기준에 동시 걸리는 사안은
영역을 쪼개지 말고 통합 답변(관련 조문 모두 인용).

**범위 게이트**: 감사·윤리·관련법령 무관 질문(코딩·잡담·순수 회계처리)은 한 문장 거절.
단, 회계감사 맥락의 회계기준 질문(예: "감사인이 보는 수익인식 위험")은 답한다.

## 3. 아키텍처 · 배치

`accounting.py` + `server.py` SSE 구조 복제, 도메인만 교체.

```
WAT/
  audit.py          ← accounting.py 복제·개작 (핵심 로직)
  audit/index.html  ← accounting/index.html 복제 (UI, 토글 라벨만 교체)
  server.py         ← /api/audit/* SSE 라우트 추가 (기존 라우트 옆)
  data/             ← audit_conv 테이블 (세션 resume)
  tests/            ← audit 단위테스트 추가
```

### 그대로 재사용 (변경 없음)

- SSE 토큰 스트리밍(`--include-partial-messages`, stream-json 파싱)
- fast/grounded 2모드 + effort(low/medium) 매핑
- 세션 resume(sqlite conv_id ↔ session_id, upsert)
- `claude -p` 서브프로세스 + 세마포어(동시 3) + 150s timeout
- `resolve_claude()` Windows claude.exe 경로 풀이
- 빈답변 fallback(델타·result 둘다 비면 assistant 본문 surface)
- workdir 임시폴더 생성·정리
- 질문검증(4000자·빈값), conv_id UUID 검증

### 교체 대상

- `_BASE_PROMPT` → 감사·윤리·법령 범위·인용형식·검색우선순위
- `FRAMEWORKS` 딕셔너리 → 감사/윤리·법령 토글
- 테이블명 `accounting_conv` → `audit_conv`
- 라우트 prefix `/api/accounting` → `/api/audit`

WAT 임베드 셸 표준(헤더 padding-left 7.25rem, 푸터 통일문구, 디자인 토큰) 신규 탭 적용.

## 4. framework 토글 (A안)

상단 3토글: `[자동 / 감사기준 / 윤리·법령]`

- `auto` — prefix 없음. 모델이 영역 판단, 교차질의 통합답
- `audit` — `[적용 영역: 회계감사기준(KSA/ISA)·품질관리기준 한정. 이 영역으로만 답하라.]`
- `ethics_law` — `[적용 영역: 공인회계사 윤리기준·공인회계사법·외부감사법 한정. 이 영역으로만 답하라.]`

미지값은 `auto`로 관대 처리(회계기준 툴 `validate_framework`와 동일).

회계기준 툴과 달리 영역이 상호배타 아님 → 토글로 강제 분할 대신 자동(교차 통합)을 기본.

## 5. 인용형식 (도메인별 정확 표기)

- 감사기준: `KSA NNN 문단 N` (예: KSA 240 문단 32), 국제 병기 시 `(ISA 240)`
- 품질관리: `ISQM 1 문단 N` / `KQCS`
- 윤리: `한공회 윤리기준 제N조` / IESBA `Code 290.N`
- 법령: `공인회계사법 제N조 제N항`, `외부감사법 제N조`, `동법 시행령 제N조`

조문·기준서 번호 정확 제시, 불확실하면 단정 금지 → '원문 확인 권고'.
fast 모드는 세부 문단번호 추측 금지(기준서·장 수준만), 중요 사안은 '🔍정밀검색 확인 권고'.

## 6. 검색 우선순위 (grounded 모드)

전부 검색 대상. 순위 = 우선 탐색·신뢰 순서. 필요한 만큼(1회 이상, 최대 3~4회) 가로질러 검색.

1. 한국공인회계사회(한공회) — 윤리위·감사기준위 질의회신·적용지침
2. 금융감독원 — 감리지적사례·회계감독, 증선위/감리위 결정
3. 법령 원문 — 공인회계사법·외부감사법·시행령/규칙 (법제처 국가법령정보)
4. 금융위원회 — 외감법 유권해석
5. IAASB·IESBA — 국제감사기준·윤리기준 원문

질의회신 있으면 번호·제목 + 전체 https URL 명시.
**미검색 시 URL 임의 생성 금지**(회계기준 툴과 동일 무결성 가드).

## 7. 모드 (회계기준 툴 승계)

- `fast` — 보유지식 즉답, effort low, 핵심 불확실 시만 WebSearch 1회. 미검색 시 URL 생성 금지.
- `grounded` — 답변 전 WebSearch 강제(1회 이상, 최대 3~4회), 출처 URL 명시, effort medium, timeout 150s.

## 8. 에러처리 (승계)

- 질문 검증 실패 → `{type:error}` 이벤트
- conv_id UUID 미준수 → 거절
- 세마포어 timeout → "서버 혼잡 — 잠시 후 재시도"
- 빈답변 fallback → assistant 본문 surface
- workdir 정리(`finally`), 세션 upsert(`finally`)

## 9. 테스트

`tests/`에 audit 단위테스트:

- 범위 게이트: 무관 질문 거절 / 감사맥락 회계질문 통과
- `apply_framework`: audit·ethics_law prefix 주입, auto 무변경, 미지값→auto
- `validate_mode` / `validate_framework` 관대 처리
- `parse_stream_line` 재사용(stream_event·assistant·result·session)
- 도메인 골든질문(독립성 위반·KAM·감리지적사례·외감법 위반 조문)

## 10. 비범위 (YAGNI)

- 후속측정·문서 업로드·RAG 벡터DB 없음(회계기준 툴과 동일, 웹검색 기반)
- framework 4토글·법령 별도축 분리 안 함(교차질의 특성상 통합이 자연)
- 회계기준 툴에 흡수 안 함(시스템프롬프트·검색우선순위 충돌)
