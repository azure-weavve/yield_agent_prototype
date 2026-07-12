"""End-to-End: mock 그룹 대조 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

from graph.build import build_graph


def test_full_loop_reaches_report_with_audit_trail():
    state = build_graph().invoke(
        {"question": "이번 배치에서 수율 이상 wafer 의 불량 원인을 분석해줘"}
    )

    # 골격: 현황파악이 불량/대조 그룹을 묶고, 리포트로 끝난다
    assert state["target_group"] == ["W2406_02", "W2406_04", "W2406_06"]
    assert state["control_group"] == ["W2406_01", "W2406_03", "W2406_05"]
    assert state["report"]

    # 게이트: 조기 finalize 는 반려됐고, 최종 finalize 는 승인됐다
    gate_results = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert any("반려" in r for r in gate_results)
    assert any("승인" in r for r in gate_results)
    assert state["finalize_accepted"] is True
    assert "ETCH-9" in state["final_hypothesis"]    # 그룹 공유 이상 장비까지 좁혔다

    # 감사 기록: 고정 골격 + 그룹 대조 시나리오의 tool 이 남았다
    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[0] == "find_low_yield_lots"   # loop 0 = 고정 골격
    assert tools_used[1] == "find_defect_group"     # loop 0 = 그룹 묶기도 골격
    for expected in ("aggregate_defects", "compare_process_logs"):
        assert expected in tools_used
    assert all("thought" in f for f in state["findings"])

    # 가드레일 안에서 끝났다
    assert state["loop_count"] <= 6


def test_no_low_yield_lots_short_circuits_to_report(monkeypatch):
    """수율 이상 lot 이 없으면 크래시 없이 '이상 없음' 리포트로 조기 종료한다."""
    from graph import nodes

    monkeypatch.setattr(nodes.yt, "find_low_yield_lots", lambda: [])
    state = build_graph().invoke({"question": "이번 배치 수율 이상 분석해줘"})

    assert state["report"]                       # 크래시 없이 리포트 도달
    assert state["target_group"] == []           # 분석 대상 없음
    assert "없음" in state["status_summary"]      # "수율 임계 미만인 lot 없음."
    # 분석 루프는 돌지 않았다 — 감사 기록은 현황 파악뿐
    assert [f["tool"] for f in state["findings"]] == ["find_low_yield_lots"]
