"""@tool 래퍼: 이름·스키마·실행 검증."""

from tools import agent_tools as at


def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "aggregate_defects", "get_process_log",
        "compare_process_logs", "validate_data_completeness",
        "compare_parameter_distribution", "find_counterexamples", "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리


def test_docstrings_exist():
    # docstring 이 곧 LLM 의 tool 선택 판단 재료
    assert all(t.description for t in at.ALL_TOOLS)


def test_get_process_log_tool_invokes():
    rows = at.TOOLS_BY_NAME["get_process_log"].invoke({"wafer_id": "W2406_02"})
    assert len(rows) == 4


def test_aggregate_defects_tool_invokes():
    rows = at.TOOLS_BY_NAME["aggregate_defects"].invoke(
        {"wafer_ids": ["W2406_02"]}
    )
    assert rows[0]["defect_type"] == "center_spot"


def test_compare_process_logs_tool_invokes():
    # 대조군도 Etch 에서 같은 설비 ETCH-9 를 쓴다(다른 챔버) — 공유 설비이므로
    # 더 이상 suspect_equipment 로 잡히지 않는다 (실제 원인은 챔버 단위에만 있다).
    res = at.TOOLS_BY_NAME["compare_process_logs"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    assert not any(r["equipment_id"] == "ETCH-9" for r in res["suspect_equipment"])


def test_validate_data_completeness_tool_invokes():
    res = at.TOOLS_BY_NAME["validate_data_completeness"].invoke(
        {"wafer_ids": ["W2406_02"]}
    )
    assert res["status"] == "good"


def test_compare_parameter_distribution_tool_invokes():
    rows = at.TOOLS_BY_NAME["compare_parameter_distribution"].invoke({
        "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
        "control_ids": ["W2406_01", "W2406_03", "W2406_05"],
    })
    assert rows[0]["param_name"] == "rf_power"


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

def test_reason_is_optional_and_ignored():
    # reason 은 감사 기록용 — 있어도 없어도 결과는 같다
    args = {"wafer_ids": ["W2406_02"]}
    assert (at.TOOLS_BY_NAME["aggregate_defects"].invoke(args)
            == at.TOOLS_BY_NAME["aggregate_defects"].invoke({**args, "reason": "테스트"}))