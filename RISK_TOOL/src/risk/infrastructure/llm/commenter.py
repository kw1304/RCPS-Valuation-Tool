from __future__ import annotations
import json
import re
from risk.domain.thresholds import Signal

_SYS = ("당신은 K-IFRS·회계감사기준 전문가입니다. 룰베이스로 산출된 위험신호를 보고 "
        "왜 위험한지·후속 확인사항·관련 경영진주장(실재성/완전성/평가/권리의무)을 "
        "감사조서용으로 간결히 서술하세요. 신호 등급은 절대 바꾸지 마세요. "
        "한국 회계용어(장부가 등) 사용.")

_EVENT_SYS = (
    "당신은 K-IFRS·회계감사기준 전문가입니다. 아래 회사의 뉴스 제목·요약과 DART 공시명을 "
    "보고, 감사대상이 될 만한 위험사건을 구조화하세요. 한국어로 작성합니다.\n"
    "규칙:\n"
    "- 동일사건은 하나로 병합. 회사와 무관한 기사·중복은 제외.\n"
    "- 근거가 없으면 빈 배열 [] 만 출력.\n"
    "- 각 사건은 다음 키를 가진 JSON 객체:\n"
    '  {"type": 사건유형(소송/횡령·배임/실적악화/지배구조/규제·제재/자금조달/기타),'
    ' "date": "YYYY-MM" 추정, "summary": "1줄 요약(한국어)",'
    ' "impact": "재무제표 영향 추정(예: 우발부채·매출인식·계속기업)",'
    ' "source": 출처URL 또는 공시명}\n'
    "- 출력은 JSON 배열만. 그 외 설명·코드블록 표시 금지."
)


_COMBINED_SYS = (
    "당신은 K-IFRS·회계감사기준 전문가입니다. 아래 (1)위험신호와 (2)뉴스·공시를 보고 "
    "다음 JSON 객체 하나만 출력하세요(설명·코드블록 금지):\n"
    '{"comments": {"<신호code>": "한 줄 코멘트(왜 위험·후속확인·관련 경영진주장)"},'
    ' "events": [{"type": 사건유형(소송/횡령·배임/실적악화/지배구조/규제·제재/자금조달/기타),'
    ' "date": "YYYY-MM", "summary": "1줄 요약", "impact": "재무제표 영향 추정",'
    ' "source": 출처URL또는공시명}]}\n'
    "규칙: 신호 등급은 바꾸지 말 것. 동일사건 병합·무관기사 제외. 근거 없으면 events는 []. "
    "한국어·한국 회계용어 사용."
)


class Commenter:
    def __init__(self, complete_fn=None):
        """complete_fn(prompt:str)->str|None. None이면 모든 AI 기능은 빈 결과로 degrade."""
        self.complete_fn = complete_fn

    @staticmethod
    def _news_disc_lines(news, disclosures):
        news_lines = []
        for n in news or []:
            if isinstance(n, dict):
                title, summary, url = n.get("title", ""), n.get("summary", ""), n.get("url", "")
            else:
                title = getattr(n, "title", "")
                summary = getattr(n, "summary", "")
                url = getattr(n, "url", "")
            news_lines.append(f"- {title} | {summary} | {url}".strip())
        disc_lines = [f"- {d.get('report_nm', '')} ({d.get('rcept_dt', '')})"
                      for d in (disclosures or [])]
        return news_lines, disc_lines

    def analyze(self, company, signals, news, disclosures):
        """신호 코멘트 + 뉴스·공시 구조화를 claude CLI 1회 호출로 통합 → (comments, events).

        claude CLI는 동시실행 불가(락 충돌)라 2개 작업을 병렬화할 수 없다. 대신 하나의
        프롬프트로 합쳐 호출 1회로 처리 → 순차 2회 대비 대기시간 절반. 실패는 ({}, []).
        """
        flagged = [s for s in (signals or []) if s.level in ("yellow", "red")]
        news = news or []
        disclosures = disclosures or []
        if not self.complete_fn or (not flagged and not news and not disclosures):
            return {}, []
        sig_lines = [f"- code={s.code} [{s.level}] {s.label}: 값 {s.value} (기준 {s.threshold})"
                     for s in flagged]
        news_lines, disc_lines = self._news_disc_lines(news, disclosures)
        prompt = (_COMBINED_SYS + f"\n\n회사: {company}\n\n[위험신호]\n" +
                  ("\n".join(sig_lines) or "(없음)") +
                  "\n\n[뉴스]\n" + ("\n".join(news_lines) or "(없음)") +
                  "\n\n[DART 공시]\n" + ("\n".join(disc_lines) or "(없음)") +
                  "\n\nJSON 객체만 출력:")
        text = self.complete_fn(prompt)
        if not text:
            return {}, []
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}, []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}, []
        if not isinstance(data, dict):
            return {}, []
        valid_codes = {s.code for s in flagged}
        comments = {k: str(v) for k, v in (data.get("comments") or {}).items()
                    if k in valid_codes and v}
        events = [e for e in (data.get("events") or []) if isinstance(e, dict)][:12]
        return comments, events

    def comment_signals(self, company: str, signals: list[Signal]) -> dict[str, str]:
        """신호 code → 코멘트. complete_fn 없거나 실패하면 빈 dict (degrade)."""
        flagged = [s for s in signals if s.level in ("yellow", "red")]
        if not self.complete_fn or not flagged:
            return {}
        lines = [f"- [{s.level}] {s.label}: 값 {s.value} (기준 {s.threshold})" for s in flagged]
        prompt = (_SYS + f"\n\n회사: {company}\n신호:\n" + "\n".join(lines) +
                  "\n각 신호별 한 줄 코멘트를 'code: 코멘트' 형식으로.")
        text = self.complete_fn(prompt)
        if not text:
            return {}
        out: dict[str, str] = {}
        for s in flagged:
            for ln in text.splitlines():
                if s.label in ln:
                    out[s.code] = ln.split(":", 1)[-1].strip()
        return out

    def structure_events(self, company: str, news, disclosures) -> list[dict]:
        """뉴스·공시를 구조화 위험사건 list[dict]로. 실패·미설정 시 [] (degrade)."""
        news = news or []
        disclosures = disclosures or []
        if not self.complete_fn or (not news and not disclosures):
            return []
        news_lines = []
        for n in news:
            if isinstance(n, dict):
                title, summary, url = n.get("title", ""), n.get("summary", ""), n.get("url", "")
            else:
                title = getattr(n, "title", "")
                summary = getattr(n, "summary", "")
                url = getattr(n, "url", "")
            news_lines.append(f"- {title} | {summary} | {url}".strip())
        disc_lines = [f"- {d.get('report_nm', '')} ({d.get('rcept_dt', '')})"
                      for d in disclosures]
        prompt = (_EVENT_SYS + f"\n\n회사: {company}\n\n[뉴스]\n" +
                  ("\n".join(news_lines) or "(없음)") +
                  "\n\n[DART 공시]\n" + ("\n".join(disc_lines) or "(없음)") +
                  "\n\nJSON 배열만 출력:")
        text = self.complete_fn(prompt)
        if not text:
            return []
        m = re.search(r"\[.*\]", text, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        events = [d for d in data if isinstance(d, dict)]
        return events[:12]
