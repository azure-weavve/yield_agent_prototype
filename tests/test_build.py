"""라우팅 함수(순환/종료 판단) 검증. E2E 는 tests/test_e2e.py 에서."""

from langchain_core.messages import AIMessage

from graph.build import _after_analyze, _after_status, _after_tools

import config


def _ai(with_call: bool):
    calls = [{"name": "get_wafer", "args": {"wafer_id": "W"}, "id": "c1"}] if with_call else []
    return AIMessage(content="생각", tool_calls=calls)


def test_analyze_with_tool_call_continues():
    assert _after_analyze({"messages": [_ai(True)], "loop_count": 2}) == "tools"


def test_analyze_without_tool_call_exits():
    # tool 도 finalize 도 없이 텍스트만 낸 이탈 케이스 → 리포팅으로 (안전망)
    assert _after_analyze({"messages": [_ai(False)], "loop_count": 2}) == "report"


def test_tools_accepted_goes_report():
    assert _after_tools({"finalize_accepted": True, "loop_count": 3}) == "report"


def test_tools_not_accepted_loops_back():
    assert _after_tools({"loop_count": 2}) == "analyze"


def test_tools_at_max_loops_forced_to_report():
    # 가드레일: finalize 없이 MAX_LOOPS 를 채우면 강제로 리포팅 (정확히 6회에서 멈춘다)
    assert _after_tools({"loop_count": config.MAX_LOOPS}) == "report"


def test_status_with_group_goes_analyze():
    assert _after_status({"target_group": ["W2406_02"]}) == "analyze"


def test_status_without_group_goes_report():
    # 이상 lot 이 없거나 defect 그룹을 못 묶으면 분석 루프를 건너뛴다
    assert _after_status({"target_group": []}) == "report"
