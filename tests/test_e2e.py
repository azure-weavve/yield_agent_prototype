"""End-to-End: mock 그룹 대조 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

import config
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

    # 2단은 '불렀다' 가 아니라 '근거를 냈다' 로 고정한다 — 호출만 보면 센서가 통째로
    # 실패해도 초록이 된다 (test_sensor_failure_is_not_reported_as_confirmed)
    sensor = next(f["result"] for f in state["findings"]
                  if f["tool"] == "compare_sensor_distribution")
    assert sensor["status"] == "ok"
    assert "rf_power_steady_avg" in state["final_hypothesis"]   # 2단 근거가 결론에 실린다

    tools_used = [f["tool"] for f in state["findings"]]
    assert tools_used[:2] == ["normalize_target", "select_control"]   # loop 0 골격
    assert any(t.startswith("hyp_") for t in tools_used)  # 레지스트리 도구가 실제 호출됨
    assert state["loop_count"] <= 6
    assert all("thought" in f for f in state["findings"])   # 모든 실행에 감사용 사고 기록


def test_sensor_failure_is_not_reported_as_confirmed(monkeypatch):
    """2단을 못 돌면(fetch_failed) 1단 근거만으로 확정하지 않는다.

    센서 결과를 보지 않고 확신도 0.9 를 내면 이 Stage 가 없앤 조용한 오확증이
    2단에서 되살아난다 — 없는 근거를 있다고 말하는 감사 기록이 남는다.
    """
    monkeypatch.setattr(config, "SENSOR_MODE", "bogus")   # get_store() 가 죽어 fetch_failed
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    sensor = next(f["result"] for f in state["findings"]
                  if f["tool"] == "compare_sensor_distribution")
    assert sensor["status"] == "fetch_failed"
    assert state["finalize_status"] != "confirmed"
    assert state["final_confidence"] < config.CONFIDENCE_THRESHOLD
    # 감사 기록도 없는 근거를 있다고 말하지 않는다
    assert not any("센서 근거까지" in f["thought"] for f in state["findings"])
    assert "ETCH9_B" in state["final_hypothesis"]    # 1단 후보는 후보로 남긴다


def test_eds_lookup_failure_ends_with_report_not_crash(monkeypatch):
    """EDS 조회가 실패해도 그래프가 예외로 죽지 않는다.

    '입력 wafer 가 없다(unknown_target)' 와 사유가 다르다 — 이쪽은 EDS 쪽 문제라
    사람이 할 조치가 다르다. 다만 사유를 '인덱스에 없다' 로 단정하지는 않는다.
    """
    from tools import grouping

    class _Missing:
        def search(self, wafer_id, k):
            raise KeyError(wafer_id)

    monkeypatch.setattr(grouping, "_searcher", _Missing())
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    assert state["finalize_status"] == "eds_lookup_failed"
    assert state["report"]
    assert "분석 미수행 — EDS 유사맵 조회 실패" in state["report"]   # 결론 문장
    assert "KeyError" in state["report"]       # 구체 사유는 현황에 그대로 실린다
    assert state["findings"]                   # 감사 기록이 끊기지 않는다


def test_no_targets_short_circuits_to_report():
    """자동 선정이 빈손(이상 lot 없음)이면 크래시 없이 '이상 없음' 리포트로 조기 종료."""
    state = build_graph().invoke({"target_wafers": [], "target_source": "auto"})
    assert state["report"]
    assert state["target_group"] == []
    assert state["finalize_status"] == "no_anomaly"
    assert state["findings"] == []           # 분석 루프도 그룹 묶기도 돌지 않았다
