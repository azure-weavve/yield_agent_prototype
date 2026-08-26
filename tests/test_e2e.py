"""End-to-End: mock 그룹 대조 루프가 현황→순환(반려 포함)→승인→리포트까지 완주하는지."""

import ya_config
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
    monkeypatch.setattr(ya_config, "SENSOR_MODE", "bogus")   # get_store() 가 죽어 fetch_failed
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    sensor = next(f["result"] for f in state["findings"]
                  if f["tool"] == "compare_sensor_distribution")
    assert sensor["status"] == "fetch_failed"
    assert state["finalize_status"] != "confirmed"
    assert state["final_confidence"] < ya_config.CONFIDENCE_THRESHOLD
    # 감사 기록도 없는 근거를 있다고 말하지 않는다
    assert not any("센서 근거까지" in f["thought"] for f in state["findings"])
    assert "ETCH9_B" in state["final_hypothesis"]    # 1단 후보는 후보로 남긴다


def test_eds_lookup_failure_ends_with_report_not_crash(monkeypatch):
    """EDS 조회가 실패해도 그래프가 예외로 죽지 않는다.

    '입력 wafer 가 없다(unknown_target)' 와 사유가 다르다 — 이쪽은 EDS 쪽 문제라
    사람이 할 조치가 다르다. 다만 사유를 '인덱스에 없다' 로 단정하지는 않는다.
    """
    from tools import eds_search

    class _Missing:
        def search(self, wafer_id, k):
            raise KeyError(wafer_id)

    monkeypatch.setattr(eds_search, "_searcher", _Missing())
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    assert state["finalize_status"] == "eds_lookup_failed"
    assert state["report"]
    assert "분석 미수행 - EDS 유사맵 조회 실패" in state["report"]   # 결론 문장
    assert "KeyError" in state["report"]       # 구체 사유는 현황에 그대로 실린다
    assert state["findings"]                   # 감사 기록이 끊기지 않는다


def test_no_targets_short_circuits_to_report():
    """자동 선정이 빈손(이상 lot 없음)이면 크래시 없이 '이상 없음' 리포트로 조기 종료."""
    state = build_graph().invoke({"target_wafers": [], "target_source": "auto"})
    assert state["report"]
    assert state["target_group"] == []
    assert state["finalize_status"] == "no_anomaly"
    assert state["findings"] == []           # 분석 루프도 그룹 묶기도 돌지 않았다


def test_sensorless_deployment_still_reaches_confirmed():
    """`SENSOR_MODE=off` 구성에서도 분석이 확정까지 간다.

    2단이 없는 것과 2단이 근거를 못 낸 것은 다르다. 후자는 기다리면 언젠가 근거가
    나오지만 전자는 안 나온다 - 그런데 둘을 같게 다루면 센서 미연결 구성에서는
    **무엇도 확정되지 못하고 매번 루프 소진**으로 끝난다. FDC 배선 전 사내 투입이
    정확히 그 상태라, 이 경로가 서면 도구를 끈 의미가 없다.

    게이트의 승인 조건(claim_id 조회 + 도구 내 최고 점수 + 확신도)은 센서를 요구하지
    않으므로 1단 근거만으로 승인이 성립한다. 여기서 지키는 것은 그 사실이다.

    별도 프로세스인 이유: 도구 목록이 모듈 import 시점에 정해진다.
    """
    import json
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = (
        "import json;"
        "from graph.build import build_graph;"
        "from tools.agent_tools import TOOLS_BY_NAME as T;"
        "s = build_graph().invoke({'target_wafers': ['W2406_02'],"
        "                          'target_source': 'manual'});"
        "print(json.dumps({"
        "  'sensor_tool': 'compare_sensor_distribution' in T,"
        "  'accepted': s.get('finalize_accepted'),"
        "  'status': s.get('finalize_status'),"
        "  'hypothesis': s.get('final_hypothesis') or '',"
        "  'sensor_calls': sum(1 for f in s['findings']"
        "                      if f['tool'] == 'compare_sensor_distribution'),"
        "  'has_report': bool(s.get('report')),"
        "}))")

    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          cwd=root, env={**os.environ, "SENSOR_MODE": "off"})
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    out = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])

    assert out["sensor_tool"] is False        # 도구가 아예 등록되지 않았다
    assert out["sensor_calls"] == 0           # 그래서 헛호출로 바퀴를 태우지 않는다
    assert out["accepted"] is True
    assert out["status"] == "confirmed"
    assert out["has_report"] is True
    assert "ETCH9_B" in out["hypothesis"]     # 1단 근거는 그대로 살아 있다
    # 무엇이 없어서 그렇게 판단했는지가 결론 문장에 남는다 (조용한 축소가 아니다)
    assert "센서가 연결되지 않은" in out["hypothesis"]


def test_every_axis_runs_on_the_pipeline_groups():
    """그래프 전체를 지나도 모든 축이 **같은 분모**로 돌아야 한다.

    이게 어긋나면 리포트 머리말("분석 대상")과 결론의 근거가 다른 wafer 집합을
    가리키는데, 게이트는 claim_id 조회만 하므로 그 어긋남을 볼 방법이 원리적으로
    없다. 노드 단위 테스트는 주입 **메커니즘**을 잠그지만, 축이 늘거나 골격이
    바뀌었을 때 실제로 그 분모가 끝까지 유지되는지는 여기서만 드러난다.
    """
    state = build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}
    )
    ran = [f for f in state["findings"] if "group_ids" in (f.get("args") or {})]
    assert ran, "대조 분모를 쓰는 도구가 한 번도 안 돌았다 - 무대가 깨졌다"
    for f in ran:
        assert f["args"]["group_ids"] == state["target_group"], f["tool"]
        assert f["args"]["control_ids"] == state["control_group"], f["tool"]
