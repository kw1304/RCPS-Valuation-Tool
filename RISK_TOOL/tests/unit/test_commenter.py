from risk.domain.thresholds import Signal
from risk.infrastructure.llm.commenter import Commenter


def test_no_client_returns_empty():
    c = Commenter(client=None)
    assert c.comment_signals("X", [Signal("a", "c", "l", "red", 1, "t")]) == {}


class _FakeClient:
    """anthropic.Anthropic 모양의 가짜 — messages.create 호출 기록·고정 응답."""
    def __init__(self, text):
        self._text = text
        self.calls = []

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                block = type("B", (), {"text": self._outer._text})()
                return type("M", (), {"content": [block]})()

        self.messages = _Messages(self)


def test_all_green_or_na_no_api_call():
    client = _FakeClient("무관: 코멘트")
    c = Commenter(client=client)
    signals = [
        Signal("analytical", "revenue_change", "매출 증감률", "green", 1, "t"),
        Signal("going_concern", "debt_ratio", "부채비율", "na", None, "t"),
    ]
    assert c.comment_signals("회사", signals) == {}
    assert client.calls == []  # 플래그 신호 없으면 API 미호출


def test_red_signal_maps_label_to_comment():
    label = "자본잠식"
    client = _FakeClient(f"{label}: 완전자본잠식으로 계속기업 불확실성 검토 필요")
    c = Commenter(client=client)
    signals = [
        Signal("analytical", "revenue_change", "매출 증감률", "green", 1, "t"),
        Signal("going_concern", "capital_impairment", label, "red", -50, "자본<0 적"),
    ]
    out = c.comment_signals("회사", signals)
    assert len(client.calls) == 1
    assert out["capital_impairment"] == "완전자본잠식으로 계속기업 불확실성 검토 필요"
