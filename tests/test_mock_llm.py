"""ScriptedMockLLMClient: 시나리오 순서·파싱·finalize 인자 검증.

mock 은 tools 노드가 만들 ToolMessage(name=..., content=json)를 보고
다음 tool 을 결정한다 — 여기서는 그 ToolMessage 를 손으로 만들어 단계를 진행시킨다.
"""

import json

from langchain_core.messages import HumanMessage, ToolMessage

from llm.client import ScriptedMockLLMClient

HUMAN = HumanMessage("현황: ...\n\n대상 wafer: W2406_cen0\n질문: 원인 분석해줘")


def _tm(name, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ToolMessage(content, tool_call_id=f"call_{name}", name=name)


def test_scripted_sequence():
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]

    # 1) 유사 검색부터
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "search_similar"
    assert ai.tool_calls[0]["args"]["wafer_id"] == "W2406_cen0"
    assert ai.content  # thought(가설 서술)가 감사 기록 재료로 반드시 존재
    msgs += [ai, _tm("search_similar", [{"wafer_id": "W2411_cen2", "similarity": 0.92}])]

    # 2) defect 집계 (유사 wafer id 를 이어받는다)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "aggregate_defects"
    assert ai.tool_calls[0]["args"]["wafer_ids"] == ["W2406_cen0", "W2411_cen2"]
    msgs += [ai, _tm("aggregate_defects", [{"defect_type": "center_spot", "count": 2}])]

    # 3) 조기 finalize (낮은 확신도 → 게이트 반려 시연용)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    msgs += [ai, _tm("finalize", "반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.")]

    # 4) 공정 로그 확인
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "get_process_log"
    msgs += [ai, _tm("get_process_log", [
        {"process_step": "Etch", "equipment_id": "ETCH-9", "param_name": "rf_power",
         "param_value": 570.0, "spec_low": 450.0, "spec_high": 550.0, "in_spec": False},
        {"process_step": "CMP", "equipment_id": "CMP-1", "param_name": "pad_pressure",
         "param_value": 4.0, "spec_low": 3.0, "spec_high": 5.0, "in_spec": True},
    ])]

    # 5) 최종 finalize — 스펙 이탈 장비를 가설에 명시
    ai = llm.analyze_step(msgs)
    call = ai.tool_calls[0]
    assert call["name"] == "finalize"
    assert call["args"]["confidence"] >= 0.8
    assert "ETCH-9" in call["args"]["hypothesis"]


def test_generate_report_contains_findings_and_conclusion():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="원인 분석해줘",
        target_wafer="W2406_cen0",
        status_summary="LOT2406 평균 84.8",
        findings=[{"loop": 1, "tool": "search_similar", "args": {"wafer_id": "W2406_cen0"},
                   "result": [], "thought": "유사 사례 확인"}],
        hypothesis="Etch 공정 ETCH-9 장비 rf_power 스펙 이탈이 원인",
        confidence=0.9,
    )
    assert "W2406_cen0" in report
    assert "search_similar" in report
    assert "ETCH-9" in report


def test_generate_report_handles_no_hypothesis():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="q", target_wafer="W1", status_summary="s",
        findings=[], hypothesis=None, confidence=None,
    )
    assert "미확정" in report
