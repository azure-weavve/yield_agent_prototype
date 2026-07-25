"""End-to-End: mock 그룹 대조 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

from graph.build import build_graph


def test_full_loop_reaches_report_with_audit_trail():
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    # 형제 묶기(전 lot): 최근 3장 + 과거 center_spot 4장이 한 사건으로 묶인다
    assert set(state["target_group"]) == {
        "W2406_02", "W2406_04", "W2406_06",
        "W2410_cen1", "W2411_cen2", "W2412_cen3", "W2413_cen4",
    }
    # 라벨이 없으면 '정상' 을 판정할 수 없다 — W2406_07(88.5, 무라벨)도 대조군에 들어간다.
    # 희석은 막지 않고 yield_summary 로 보인다 (spec 2026-07-25 결정 1·2).
    assert "W2406_07" in state["control_group"]
    assert set(state["control_group"]) >= {"W2406_01", "W2406_03", "W2406_05"}
    assert "root_lot" in state["status_summary"]     # 대조군 출처가 root_lot 단위로 보고된다
    assert state["report"]

    gate_results = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert any("반려" in r for r in gate_results)
    assert any("승인" in r for r in gate_results)
    assert state["finalize_accepted"] is True
    assert "ETCH9_B" in state["final_hypothesis"]        # ETCH-9 → 챔버로 좁혀진 결론

    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[:2] == ["normalize_target", "select_control"]   # loop 0 골격
    assert "aggregate_defects" in tools_used
    assert any(t.startswith("hyp_") for t in tools_used)  # 레지스트리 도구가 실제 호출됨
    assert state["loop_count"] <= 6
    assert all("thought" in f for f in state["findings"])   # 모든 실행에 감사용 사고 기록


def test_no_targets_short_circuits_to_report():
    """자동 선정이 빈손(이상 lot 없음)이면 크래시 없이 '이상 없음' 리포트로 조기 종료."""
    state = build_graph().invoke({"target_wafers": [], "target_source": "auto"})
    assert state["report"]
    assert state["target_group"] == []
    assert state["finalize_status"] == "no_anomaly"
    assert state["findings"] == []           # 분석 루프도 그룹 묶기도 돌지 않았다
