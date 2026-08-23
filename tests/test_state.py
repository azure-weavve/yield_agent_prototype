"""누적형 상태: messages/findings 가 덮어쓰이지 않고 쌓이는지 검증."""

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

import ya_config
from graph.state import AgentState


def test_max_loops_covers_every_registered_hypothesis():
    """루프 예산이 등록 가설 수를 감당하는지 — 숫자가 아니라 관계를 지킨다.

    게이트는 등록 가설을 **전부 돌린 뒤에만** no_signal 을 선언한다. 그래서 필요한
    최소 바퀴는 (가설 수 + 첫 finalize 시도 + 마지막 finalize) 다. 가설을 늘리면서
    예산을 안 늘리면 no_signal 케이스가 루프 소진으로 끝나 **사유가 틀린 보고**가
    된다(조치가 다르다: 재시도 vs 대조군 확장). 4번째 가설(metro) 추가 때 실제로
    그렇게 됐고, 그때는 end-to-end 테스트가 먼저 걸렸다 - 여기서 바로 알려준다.

    마진이 +2 가 아니라 **+3** 인 이유: +2 는 "겨우 돈다" 를 통과시킨다. 가설이
    5개가 되면 5+2=7 이라 지금 예산 7 이 그대로 통과하는데, 그때 탐색에 쓸 수 있는
    바퀴는 **0** 이다. 신호를 못 찾는 경로가 곧 신규 제품에서 이름 없는 이상을
    찾는 경로인데, 거기서 시스템이 체크리스트만 소화하고 끝나는 것이 이 프로젝트가
    피하려는 상태 자체다. 최소 한 바퀴는 남겨 두고, 안 남으면 여기서 멈춘다.
    """
    from domain import registry

    n_hyp = len(registry.load_hypotheses())
    assert ya_config.MAX_LOOPS >= n_hyp + 3, (
        f"가설 {n_hyp}개에 MAX_LOOPS {ya_config.MAX_LOOPS} 는 모자란다 - "
        f"전부 돌리고 finalize 두 번 하면 탐색에 쓸 바퀴가 안 남는다")


def test_loop_config_exists():
    assert ya_config.MAX_LOOPS == 7
    assert ya_config.CONFIDENCE_THRESHOLD == 0.8
    assert ya_config.SIBLING_MIN_SIMILARITY == 0.8
    assert ya_config.CONTROL_MIN_SIZE == 3
    assert ya_config.SIBLING_SEARCH_K == 50


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
    out = g.compile().invoke({"target_wafers": []})

    assert [m.content for m in out["messages"]] == ["a", "b"]   # 누적 (덮어쓰기 아님)
    assert [f["loop"] for f in out["findings"]] == [0, 1]
