"""그래프 조립 — 하이브리드 분석 루프.

  status ──(대상 있음)──▶ analyze ──(tool call)──▶ tools ──(반려/계속)──▶ analyze   ← 순환
   (고정)      │              │                      │
               │              └─(호출 없음)          └─(finalize 승인/한계)
               └─(조기 출구)         ▼                      ▼
                      ▼            report ◀────────────────┘
                      └─────────────▶ (고정)

골격(status→…→report)은 고정 엣지, analyze ⇄ tools 만 LLM 자율 순환.
종료는 tools 노드의 finalize 게이트(확신도)와 _after_tools 의 MAX_LOOPS 가드레일이 통제한다.
"""

from langgraph.graph import END, StateGraph

import config
from graph import nodes
from graph.state import AgentState


def _after_status(state: dict) -> str:
    # 조기 출구(no_anomaly/unknown_target/eds_lookup_failed/isolated/control_insufficient)는 finalize_status 가
    # 이미 찍혀 있다 — 분석 루프를 건너뛰고 리포팅으로
    return "report" if state.get("finalize_status") else "analyze"


def _after_analyze(state: dict) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "report"  # tool 호출 없이 텍스트만 = 이탈 케이스 → 리포팅 (안전망)


def _after_tools(state: dict) -> str:
    if state.get("finalize_accepted"):
        return "report"
    if state["loop_count"] >= config.MAX_LOOPS:  # 가드레일: 무한루프 차단 (정확히 MAX_LOOPS 회)
        return "report"
    return "analyze"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("status", nodes.status_node)
    g.add_node("analyze", nodes.analyze_node)
    g.add_node("tools", nodes.tools_node)
    g.add_node("report", nodes.report_node)

    g.set_entry_point("status")                    # 고정: 반드시 현황파악 먼저
    g.add_conditional_edges("status", _after_status, ["analyze", "report"])
    g.add_conditional_edges("analyze", _after_analyze, ["tools", "report"])
    g.add_conditional_edges("tools", _after_tools, ["analyze", "report"])
    g.add_edge("report", END)                      # 고정: 반드시 리포팅으로 끝

    return g.compile()
