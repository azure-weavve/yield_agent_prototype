"""End-to-End: mock 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

from graph.build import build_graph


def test_full_loop_reaches_report_with_audit_trail():
    state = build_graph().invoke(
        {"question": "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"}
    )

    # 골격: 현황파악이 대상 wafer 를 지목하고, 리포트로 끝난다
    assert state["target_wafer"].startswith("W2406_")
    assert state["report"]

    # 게이트: 조기 finalize 는 반려됐고, 최종 finalize 는 승인됐다
    gate_results = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert any("반려" in r for r in gate_results)
    assert any("승인" in r for r in gate_results)
    assert state["finalize_accepted"] is True
    assert "-9" in state["final_hypothesis"]        # 이상 장비까지 좁혔다

    # 감사 기록: 시나리오의 분석 tool 이 순서대로 남았다
    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[0] == "find_low_yield_lots"   # loop 0 = 고정 골격
    for expected in ("search_similar", "aggregate_defects", "get_process_log"):
        assert expected in tools_used
    assert all("thought" in f for f in state["findings"])

    # 가드레일 안에서 끝났다
    assert state["loop_count"] <= 6
