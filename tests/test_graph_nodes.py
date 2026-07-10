"""노드 단위 검증 — 특히 tools 노드의 finalize 게이트(승인/반려)와 감사 기록."""

from langchain_core.messages import AIMessage, ToolMessage

from graph import nodes


def _ai_finalize(confidence):
    return AIMessage(
        content="종료 제안",
        tool_calls=[{"name": "finalize",
                     "args": {"hypothesis": "Etch ETCH-9 원인", "confidence": confidence},
                     "id": "call_f"}],
    )


def test_status_node_sets_target_and_seed_messages():
    out = nodes.status_node({"question": "원인 분석해줘"})
    assert out["target_wafer"].startswith("W2406_")          # 최근 배치의 worst wafer
    assert f"대상 wafer: {out['target_wafer']}" in out["messages"][-1].content
    assert out["findings"][0]["loop"] == 0                   # 현황파악도 감사 기록에 남는다
    assert out["findings"][0]["tool"] == "find_low_yield_lots"


def test_tools_node_executes_and_records_finding():
    ai = AIMessage(
        content="유사 사례 확인",
        tool_calls=[{"name": "get_process_log",
                     "args": {"wafer_id": "W2406_cen0"}, "id": "call_1"}],
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


def test_finalize_gate_accepts_high_confidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4})
    assert out["finalize_accepted"] is True
    assert out["final_hypothesis"] == "Etch ETCH-9 원인"
    assert out["final_confidence"] == 0.9
    assert "승인" in out["messages"][0].content


def test_finalize_gate_accepts_at_max_loops_even_if_low():
    out = nodes.tools_node({"messages": [_ai_finalize(0.5)], "loop_count": 6})
    assert out["finalize_accepted"] is True                  # 한계 도달 시 강제 승인


def test_report_node_produces_report():
    out = nodes.report_node({
        "question": "q", "target_wafer": "W2406_cen0", "status_summary": "요약",
        "findings": [], "final_hypothesis": "Etch ETCH-9 원인", "final_confidence": 0.9,
    })
    assert "ETCH-9" in out["report"]
