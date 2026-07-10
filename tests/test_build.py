"""라우팅 함수(순환/종료 판단) 검증. E2E 는 tests/test_e2e.py 에서."""

from langchain_core.messages import AIMessage

from graph.build import _after_analyze, _after_tools


def _ai(with_call: bool):
    calls = [{"name": "get_wafer", "args": {"wafer_id": "W"}, "id": "c1"}] if with_call else []
    return AIMessage(content="생각", tool_calls=calls)


def test_analyze_with_tool_call_continues():
    assert _after_analyze({"messages": [_ai(True)], "loop_count": 2}) == "tools"


def test_analyze_without_tool_call_exits():
    # tool 도 finalize 도 없이 텍스트만 낸 이탈 케이스 → 리포팅으로 (안전망)
    assert _after_analyze({"messages": [_ai(False)], "loop_count": 2}) == "report"


def test_analyze_over_max_loops_forced_to_report():
    assert _after_analyze({"messages": [_ai(True)], "loop_count": 7}) == "report"


def test_tools_accepted_goes_report():
    assert _after_tools({"finalize_accepted": True}) == "report"


def test_tools_not_accepted_loops_back():
    assert _after_tools({}) == "analyze"
