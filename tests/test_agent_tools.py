"""@tool 래퍼: 이름·스키마·실행 검증."""

from tools import agent_tools as at


def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "compare_sensor_distribution",
        "hyp_eqp_ch_commonality", "hyp_ppid_commonality",
        "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리
    assert "find_commonality" not in at.TOOLS_BY_NAME   # raw 래퍼 제거(legend 로 일원화)


def test_docstrings_exist():
    # docstring 이 곧 LLM 의 tool 선택 판단 재료
    assert all(t.description for t in at.ALL_TOOLS)


def test_hyp_eqp_ch_commonality_tool_invokes():
    res = at.TOOLS_BY_NAME["hyp_eqp_ch_commonality"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    keys = {c["key"] for c in res["candidates"]}
    assert "ETCH9_B" in keys
    assert any(c["passes"] for c in res["candidates"] if c["key"] == "ETCH9_B")


def test_reason_is_optional_and_ignored():
    # reason 은 감사 기록용 — 있어도 없어도 결과는 같다
    args = {"wafer_id": "W2406_02"}
    assert (at.TOOLS_BY_NAME["get_wafer"].invoke(args)
            == at.TOOLS_BY_NAME["get_wafer"].invoke({**args, "reason": "테스트"}))


def test_compare_sensor_distribution_tool_invokes():
    from data.generate_dummy import CONTROL_WAFERS, GROUP_WAFERS, SENSOR_REAL, SENSOR_STEP

    res = at.TOOLS_BY_NAME["compare_sensor_distribution"].invoke({
        "step_seq": SENSOR_STEP,
        "group_ids": GROUP_WAFERS, "control_ids": CONTROL_WAFERS,
    })
    assert res["status"] == "ok"
    assert res["candidates"][0]["sensor_name"] == f"{SENSOR_REAL}_avg"
    assert "refetch_key" in res
