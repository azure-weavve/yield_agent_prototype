"""노드 단위 검증 — 특히 tools 노드의 finalize 게이트(승인/반려)와 감사 기록."""

from langchain_core.messages import AIMessage, ToolMessage

from graph import nodes


def _ai_finalize(confidence, hypothesis="Etch ETCH-9 원인"):
    return AIMessage(
        content="종료 제안",
        tool_calls=[{"name": "finalize",
                     "args": {"hypothesis": hypothesis, "confidence": confidence},
                     "id": "call_f"}],
    )


# 게이트 증거 검사용: compare_process_logs 가 ETCH-9 를 지목한 감사 기록
EVIDENCE_FINDING = {
    "loop": 2, "tool": "compare_process_logs",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {
        "suspect_equipment": [{"process_step": "Etch", "equipment_id": "ETCH-9",
                               "group_count": 3, "control_count": 0}],
        "equipment_usage": [],
        "group_spec_violations": [
            {"wafer_id": "W2406_02", "process_step": "Etch", "equipment_id": "ETCH-9",
             "param_name": "rf_power", "param_value": 570.0,
             "spec_low": 450.0, "spec_high": 550.0},
        ],
    },
    "thought": "그룹 대조",
}


def test_status_node_sets_groups_and_seed_messages():
    out = nodes.status_node({"question": "원인 분석해줘"})
    assert out["target_group"] == ["W2406_02", "W2406_04", "W2406_06"]
    assert out["control_group"] == ["W2406_01", "W2406_03", "W2406_05"]
    assert "불량 그룹 (center_spot)" in out["messages"][-1].content
    assert "대조 그룹 (정상)" in out["messages"][-1].content
    assert out["findings"][0]["loop"] == 0                   # 현황파악도 감사 기록에 남는다
    assert out["findings"][0]["tool"] == "find_low_yield_lots"
    assert out["findings"][1]["tool"] == "find_defect_group"  # 그룹 묶기도 감사 기록에


def test_tools_node_executes_and_records_finding():
    ai = AIMessage(
        content="유사 사례 확인",
        tool_calls=[{"name": "get_process_log",
                     "args": {"wafer_id": "W2406_02"}, "id": "call_1"}],
    )
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    tm = out["messages"][0]
    assert isinstance(tm, ToolMessage) and tm.name == "get_process_log"
    f = out["findings"][0]
    assert (f["loop"], f["tool"], f["thought"]) == (1, "get_process_log", "유사 사례 확인")
    assert len(f["result"]) == 4                             # 결과 원본이 그대로 남는다
    assert "finalize_accepted" not in out


def test_finalize_gate_rejects_low_confidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.6)], "loop_count": 3})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert out["findings"][0]["tool"] == "finalize"          # 반려도 감사 기록에 남는다


def test_finalize_gate_accepts_high_confidence_with_evidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"
    assert out["final_hypothesis"] == "Etch ETCH-9 원인"
    assert out["final_confidence"] == 0.9
    assert "승인" in out["messages"][0].content


def test_finalize_gate_rejects_high_confidence_without_evidence():
    # (a) 조사 없이 결론: confidence 0.9 라도 그룹 대조 근거가 없으면 반려
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 1,
                            "findings": []})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert "compare_process_logs" in out["messages"][0].content  # 무엇을 하라는지 안내


def test_finalize_gate_rejects_hypothesis_not_backed_by_evidence():
    # (b) 조사와 다른 결론: tool 결과는 ETCH-9 를 지목했는데 가설은 CVD-3
    out = nodes.tools_node({
        "messages": [_ai_finalize(0.9, hypothesis="CVD-3 장비의 온도 이상이 원인")],
        "loop_count": 3, "findings": [EVIDENCE_FINDING],
    })
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert "ETCH-9" in out["messages"][0].content  # 실제 suspect 후보를 알려준다


def test_finalize_gate_sees_evidence_from_same_message():
    # 한 메시지에 compare_process_logs + finalize 가 같이 오면, 방금 실행된 대조 결과도 증거다
    ai = AIMessage(
        content="그룹 대조 후 바로 종료 제안",
        tool_calls=[
            {"name": "compare_process_logs",
             "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
                      "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
             "id": "call_c"},
            {"name": "finalize",
             "args": {"hypothesis": "Etch ETCH-9 원인", "confidence": 0.9},
             "id": "call_f"},
        ],
    )
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": []})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"


def test_finalize_gate_marks_inconclusive_at_max_loops():
    # (c) 한계 도달 강제 종료는 "승인"이 아니라 "미확정"으로 구분 기록
    out = nodes.tools_node({"messages": [_ai_finalize(0.5)], "loop_count": 6,
                            "findings": []})
    assert out["finalize_accepted"] is True                  # 루프는 종료하되
    assert out["finalize_status"] == "inconclusive"          # 확정 결론이 아님을 기록
    assert "미확정" in out["messages"][0].content


def test_report_node_produces_report():
    out = nodes.report_node({
        "question": "q", "target_group": ["W2406_02", "W2406_04", "W2406_06"], "status_summary": "요약",
        "findings": [], "final_hypothesis": "Etch ETCH-9 원인", "final_confidence": 0.9,
    })
    assert "ETCH-9" in out["report"]


def test_report_node_marks_inconclusive_conclusion():
    # 한계 도달 종료는 리포트 결론도 "미확정" 톤으로 나가야 한다 (확정 결론으로 위장 금지)
    out = nodes.report_node({
        "question": "q", "target_group": ["W2406_02"], "status_summary": "요약",
        "findings": [], "final_hypothesis": "ETCH-9 이상 추정", "final_confidence": 0.5,
        "finalize_status": "inconclusive",
    })
    assert "미확정" in out["report"]
    assert "ETCH-9" in out["report"]  # 유력 가설은 후보로는 남긴다

def test_tools_node_recovers_from_unknown_tool_name():
    ai = AIMessage(content="", tool_calls=[
        {"name": "functions.get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert "오류" in out["messages"][0].content
    assert "get_wafer" in out["messages"][0].content


def test_tools_node_recovers_from_bad_args():
    ai = AIMessage(content="", tool_calls=[
        {"name": "aggregate_defects", "args": {"wafer_ids": "W2406_02"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert "오류" in out["messages"][0].content


def test_finalize_gate_handles_non_numeric_confidence():
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize", "args": {"hypothesis": "Etch ETCH-9 원인",
                                      "confidence": "high"}, "id": "cf"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": []})
    assert "finalize_accepted" not in out
    assert "숫자" in out["messages"][0].content


def test_tools_node_falls_back_to_reason_when_content_empty():
    # 실제 LLM 은 tool call 시 content 를 비우므로 reason 인자가 감사 기록을 채운다
    ai = AIMessage(content="", tool_calls=[
        {"name": "get_process_log",
         "args": {"wafer_id": "W2406_02", "reason": "스펙 이탈 확인"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert out["findings"][0]["thought"] == "스펙 이탈 확인"