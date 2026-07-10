"""누적형 상태: messages/findings 가 덮어쓰이지 않고 쌓이는지 검증."""

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

import config
from graph.state import AgentState


def test_loop_config_exists():
    assert config.MAX_LOOPS == 6
    assert config.CONFIDENCE_THRESHOLD == 0.8


def test_messages_and_findings_accumulate():
    def n1(state):
        return {"messages": [HumanMessage("a")], "findings": [{"loop": 0}]}

    def n2(state):
        return {"messages": [HumanMessage("b")], "findings": [{"loop": 1}]}

    g = StateGraph(AgentState)
    g.add_node("n1", n1)
    g.add_node("n2", n2)
    g.set_entry_point("n1")
    g.add_edge("n1", "n2")
    g.add_edge("n2", END)
    out = g.compile().invoke({"question": "q"})

    assert [m.content for m in out["messages"]] == ["a", "b"]   # 누적 (덮어쓰기 아님)
    assert [f["loop"] for f in out["findings"]] == [0, 1]
