from __future__ import annotations
import os
from risk.domain.thresholds import Signal

_MODEL = "claude-opus-4-8"
_SYS = ("당신은 K-IFRS·회계감사기준 전문가입니다. 룰베이스로 산출된 위험신호를 보고 "
        "왜 위험한지·후속 확인사항·관련 경영진주장(실재성/완전성/평가/권리의무)을 "
        "감사조서용으로 간결히 서술하세요. 신호 등급은 절대 바꾸지 마세요. "
        "한국 회계용어(장부가 등) 사용.")


class Commenter:
    def __init__(self, client=None):
        self.client = client  # anthropic.Anthropic | None

    def comment_signals(self, company: str, signals: list[Signal]) -> dict[str, str]:
        """신호 code → 코멘트. client 없으면 빈 dict (degrade)."""
        flagged = [s for s in signals if s.level in ("yellow", "red")]
        if not self.client or not flagged:
            return {}
        lines = [f"- [{s.level}] {s.label}: 값 {s.value} (기준 {s.threshold})" for s in flagged]
        msg = self.client.messages.create(
            model=_MODEL, max_tokens=1500, system=_SYS,
            messages=[{"role": "user",
                       "content": f"회사: {company}\n신호:\n" + "\n".join(lines) +
                                  "\n각 신호별 한 줄 코멘트를 'code: 코멘트' 형식으로."}])
        text = msg.content[0].text
        out = {}
        for s in flagged:
            for ln in text.splitlines():
                if s.label in ln:
                    out[s.code] = ln.split(":", 1)[-1].strip()
        return out
