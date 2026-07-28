"""@tool 래퍼: 이름·스키마·실행 검증."""

from tools import agent_tools as at


def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "get_process_log",
        "validate_data_completeness", "find_counterexamples",
        "hyp_eqp_ch_commonality", "hyp_ppid_commonality",
        "compare_sensor_distribution",
        "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리
    assert "find_commonality" not in at.TOOLS_BY_NAME   # raw 래퍼 제거(legend 로 일원화)


def test_docstrings_exist():
    # docstring 이 곧 LLM 의 tool 선택 판단 재료
    assert all(t.description for t in at.ALL_TOOLS)


def test_get_process_log_tool_invokes():
    rows = at.TOOLS_BY_NAME["get_process_log"].invoke({"wafer_id": "W2406_02"})
    assert len(rows) == 4


def test_validate_data_completeness_tool_invokes():
    res = at.TOOLS_BY_NAME["validate_data_completeness"].invoke(
        {"wafer_ids": ["W2406_02"]}
    )
    assert res["status"] == "good"


def test_hyp_eqp_ch_commonality_tool_invokes():
    res = at.TOOLS_BY_NAME["hyp_eqp_ch_commonality"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    keys = {c["key"] for c in res["candidates"]}
    assert "ETCH9_B" in keys
    assert any(c["passes"] for c in res["candidates"] if c["key"] == "ETCH9_B")


def test_find_counterexamples_tool_invokes():
    # 대조군 3장도 이제 Etch 에서 ETCH-9 를 쓰므로(다른 챔버) 반례 목록에 추가된다:
    # 구멍 (가) W2406_07 + 대조군 3장(W2406_01/03/05) = 4건.
    res = at.TOOLS_BY_NAME["find_counterexamples"].invoke({
        "equipment_id": "ETCH-9", "process_step": "Etch",
        "defect_type": "center_spot",
    })
    assert [r["wafer_id"] for r in res["passed_but_normal"]] == [
        "W2406_01", "W2406_03", "W2406_05", "W2406_07",
    ]


def test_legacy_tools_hidden_when_flag_off(monkeypatch):
    """실데이터 모드에서는 process_log 기반 레거시 도구가 LLM 에 노출되지 않는다.

    reload 로 모듈 상태를 갈아끼우므로, 플래그가 꺼진 창(window) 안에서 다른 모듈이
    agent_tools 를 처음 import 하면 그쪽은 줄어든 목록을 붙든 채로 남는다.
    graph/nodes.py 가 `from tools.agent_tools import TOOLS_BY_NAME` 로 이름을 직접
    바인딩하는데, 수집 시점에 이미 import 되므로 지금은 안전하다.
    """
    import importlib

    import config
    from tools import agent_tools

    monkeypatch.setattr(config, "LEGACY_TOOLS_ENABLED", False)
    importlib.reload(agent_tools)
    try:
        names = {t.name for t in agent_tools.ANALYSIS_TOOLS}
        assert not (names & {"get_process_log", "find_counterexamples",
                             "validate_data_completeness"})
        assert any(n.startswith("hyp_") for n in names)      # 가설 도구는 남는다
        assert "finalize" in {t.name for t in agent_tools.ALL_TOOLS}
    finally:
        monkeypatch.undo()                                   # 원래 값으로 (True 고정 아님)
        importlib.reload(agent_tools)                        # 다른 테스트에 누수 방지


def test_reason_is_optional_and_ignored():
    # reason 은 감사 기록용 — 있어도 없어도 결과는 같다
    args = {"wafer_id": "W2406_02"}
    assert (at.TOOLS_BY_NAME["get_wafer"].invoke(args)
            == at.TOOLS_BY_NAME["get_wafer"].invoke({**args, "reason": "테스트"}))


def test_compare_sensor_distribution_tool_invokes():
    from data.generate_dummy import CONTROL_WAFERS, GROUP_WAFERS, SENSOR_REAL, SENSOR_STEP

    res = at.TOOLS_BY_NAME["compare_sensor_distribution"].invoke({
        "process_step": SENSOR_STEP,
        "group_ids": GROUP_WAFERS, "control_ids": CONTROL_WAFERS,
    })
    assert res["status"] == "ok"
    assert res["candidates"][0]["sensor_name"] == f"{SENSOR_REAL}_avg"
    assert "refetch_key" in res
