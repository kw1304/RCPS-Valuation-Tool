from risk.domain.thresholds import Signal
from risk.infrastructure.llm.commenter import Commenter


def test_no_complete_fn_returns_empty():
    c = Commenter(complete_fn=None)
    assert c.comment_signals("X", [Signal("a", "c", "l", "red", 1, "t")]) == {}


def test_all_green_or_na_no_api_call():
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return "무관: 코멘트"

    c = Commenter(complete_fn=fake)
    signals = [
        Signal("analytical", "revenue_change", "매출 증감률", "green", 1, "t"),
        Signal("going_concern", "debt_ratio", "부채비율", "na", None, "t"),
    ]
    assert c.comment_signals("회사", signals) == {}
    assert calls == []  # 플래그 신호 없으면 호출 안 함


def test_red_signal_maps_label_to_comment():
    label = "자본잠식"
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return f"{label}: 완전자본잠식으로 계속기업 불확실성 검토 필요"

    c = Commenter(complete_fn=fake)
    signals = [
        Signal("analytical", "revenue_change", "매출 증감률", "green", 1, "t"),
        Signal("going_concern", "capital_impairment", label, "red", -50, "자본<0 적"),
    ]
    out = c.comment_signals("회사", signals)
    assert len(calls) == 1
    assert out["capital_impairment"] == "완전자본잠식으로 계속기업 불확실성 검토 필요"


# ── structure_events ──────────────────────────────────────────────

def _news(title, summary="", url="", keyword="", date=""):
    return type("N", (), {"title": title, "summary": summary, "url": url,
                          "keyword": keyword, "date": date})()


def test_structure_events_no_fn_returns_empty():
    c = Commenter(complete_fn=None)
    assert c.structure_events("회사", [_news("소송 제기")], []) == []


def test_structure_events_empty_inputs_returns_empty():
    c = Commenter(complete_fn=lambda p: "[]")
    assert c.structure_events("회사", [], []) == []


def test_structure_events_parses_json_array():
    payload = (
        '여기 결과입니다:\n'
        '[{"type":"소송","date":"2025-03","summary":"하도급 소송 제기",'
        '"impact":"우발부채","source":"http://x"}]\n끝.'
    )
    c = Commenter(complete_fn=lambda p: payload)
    events = c.structure_events("회사", [_news("소송")], [{"report_nm": "소송등의제기"}])
    assert isinstance(events, list) and len(events) == 1
    e = events[0]
    assert e["type"] == "소송"
    assert e["summary"] == "하도급 소송 제기"
    assert e["impact"] == "우발부채"
    assert e["source"] == "http://x"


def test_structure_events_garbage_returns_empty():
    c = Commenter(complete_fn=lambda p: "JSON 못 만들겠어요 죄송")
    assert c.structure_events("회사", [_news("소송")], []) == []


def test_structure_events_caps_to_12():
    arr = "[" + ",".join('{"type":"기타","summary":"s"}' for _ in range(30)) + "]"
    c = Commenter(complete_fn=lambda p: arr)
    events = c.structure_events("회사", [_news("x")], [])
    assert len(events) == 12


def test_analyze_combined_parses_comments_and_events():
    from risk.domain.thresholds import Signal
    from risk.infrastructure.llm.commenter import Commenter
    payload = ('말머리설명 {"comments": {"debt_ratio": "부채과다 — 차입약정 검토"},'
               ' "events": [{"type":"소송","date":"2025-06","summary":"소송 제기",'
               '"impact":"우발부채","source":"http://x"}]} 꼬리')
    c = Commenter(complete_fn=lambda p: payload)
    sigs = [Signal("going_concern", "debt_ratio", "부채비율", "red", 400, "t")]
    comments, events = c.analyze("X", sigs, [{"title": "소송"}], [])
    assert comments == {"debt_ratio": "부채과다 — 차입약정 검토"}
    assert len(events) == 1 and events[0]["type"] == "소송"


def test_analyze_degrades_no_fn():
    from risk.domain.thresholds import Signal
    from risk.infrastructure.llm.commenter import Commenter
    c = Commenter(complete_fn=None)
    assert c.analyze("X", [Signal("a", "c", "l", "red", 1, "t")], [], []) == ({}, [])


def test_analyze_garbage_returns_empty():
    from risk.domain.thresholds import Signal
    from risk.infrastructure.llm.commenter import Commenter
    c = Commenter(complete_fn=lambda p: "응답인데 JSON 없음")
    out = c.analyze("X", [Signal("a", "c", "l", "red", 1, "t")], [{"title": "x"}], [])
    assert out == ({}, [])
