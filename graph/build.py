"""그래프 조립.

  intent ──(conditional)──▶ yield_tool ─┐
                          └▶ similar_tool ┴▶ answer ▶ END

의도 파악 결과에 따라 경로별 도구 노드로 분기(라우팅).
멀티턴(시나리오 1→2 의 "그 wafer" 이어받기)을 위해 체크포인터를 단다.
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from graph import nodes
from graph.state import AgentState
from llm.client import ROUTE_SIMILAR


def _route(state: dict) -> str:
    # defect_cause(시나리오 3)는 확장 — 현재는 yield 로 폴백.
    return "similar_tool" if state.get("intent") == ROUTE_SIMILAR else "yield_tool"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("intent", nodes.intent_node)
    g.add_node("yield_tool", nodes.yield_tool_node)
    g.add_node("similar_tool", nodes.similar_tool_node)
    g.add_node("answer", nodes.answer_node)

    g.set_entry_point("intent")
    g.add_conditional_edges("intent", _route, ["yield_tool", "similar_tool"])
    g.add_edge("yield_tool", "answer")
    g.add_edge("similar_tool", "answer")
    g.add_edge("answer", END)

    return g.compile(checkpointer=MemorySaver())
