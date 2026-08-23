"""@tool 래퍼: 이름·스키마·실행 검증."""

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from tools import agent_tools as at


def test_tool_names():
    assert {t.name for t in at.ALL_TOOLS} == {
        "get_wafer", "search_similar", "compare_sensor_distribution",
        "hyp_eqp_ch_commonality", "hyp_ppid_commonality",
        "hyp_step_passage_commonality", "hyp_metro_commonality",
        "finalize",
    }
    assert "finalize" not in at.TOOLS_BY_NAME  # finalize 는 게이트가 처리
    assert "find_commonality" not in at.TOOLS_BY_NAME   # raw 래퍼 제거(legend 로 일원화)


def test_docstrings_exist():
    # docstring 이 곧 LLM 의 tool 선택 판단 재료
    assert all(t.description for t in at.ALL_TOOLS)


def test_every_tool_argument_declares_a_json_type():
    """LLM 에 나가는 스키마의 모든 인자에 `type` 이 있어야 한다.

    `@tool` 데코레이터로 만든 도구는 타입 힌트에서 스키마가 나오지만, YAML 로
    동적 생성되는 `hyp_*` (domain/registry.py) 는 힌트를 안 붙이면 인자가
    `{}` (타입 없음)로 나간다. 그러면 LLM 이 리스트 자리에 문자열을 넣어도
    스키마 위반이 아니게 되고, 그 사고는
    `test_hypothesis_tool_rejects_a_string_where_a_list_is_required` 가 보여주듯
    **에러 없이 틀린 결과**로 끝난다.

    도구가 늘어날 때마다 같은 구멍이 다시 생기므로 전수로 잠근다.
    """
    typeless = []
    for tool in at.ALL_TOOLS:
        props = convert_to_openai_tool(tool)["function"]["parameters"]["properties"]
        typeless += [f"{tool.name}.{arg}" for arg, spec in props.items()
                     if "type" not in spec and "anyOf" not in spec]
    assert not typeless, (
        f"타입 없는 인자: {sorted(typeless)}. 도구 함수에 타입 힌트를 붙여야 한다 "
        f"(hyp_* 는 domain/registry.py 의 `_run`)."
    )


def test_hypothesis_tool_rejects_a_string_where_a_list_is_required():
    """가설 도구에 wafer 목록 대신 문자열이 오면 실패해야 한다.

    타입 없는 스키마에서는 문자열이 `set()` 으로 들어가 글자 단위로 쪼개지고,
    결과가 `status="no_paired_stratum"` (= "이력 결측 확인 필요") 로 나왔다.
    LLM 의 인자 실수가 엔지니어에게 **데이터 결측으로 보고**되는 조용한 오류다.
    실패해야 `tools_node` 가 오류 ToolMessage 로 돌려주고 LLM 이 스스로 고친다.
    """
    with pytest.raises(Exception):
        at.TOOLS_BY_NAME["hyp_eqp_ch_commonality"].invoke({
            "group_ids": "W2406_02,W2406_04,W2406_06",
            "control_ids": "W2406_01,W2406_03,W2406_05",
        })


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


def test_sensor_tool_is_not_registered_when_sensors_are_off():
    """`SENSOR_MODE=off` 면 2단 도구를 아예 안 준다.

    등록해 두면 LLM 이 부르고, 실패가 "인자를 확인하고 다시 호출하라" 로 돌아와
    같은 호출을 반복하며 루프만 태운다. FDC 배선 전 사내 투입에서 실제로 이 모양이
    된다 - 그때 코드를 고치지 않고 .env 로 끌 수 있어야 한다.

    별도 프로세스로 확인하는 이유는 test_eds_search.py 와 같다: 도구 목록은 모듈
    import 시점에 만들어지므로 이미 import 된 이 세션에서는 반영되지 않는다.
    """
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = ("from tools.agent_tools import TOOLS_BY_NAME as T; "
             "print('compare_sensor_distribution' in T, 'search_similar' in T)")

    off = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         cwd=root, env={**os.environ, "SENSOR_MODE": "off"})
    assert off.returncode == 0, off.stderr.decode("utf-8", "replace")
    assert off.stdout.decode().split() == ["False", "True"]

    on = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                        cwd=root, env={**os.environ, "SENSOR_MODE": "local"})
    assert on.returncode == 0, on.stderr.decode("utf-8", "replace")
    assert on.stdout.decode().split() == ["True", "True"]


def test_turning_sensors_off_does_not_touch_the_hypothesis_budget():
    """센서를 꺼도 게이트의 `no_signal` 전제는 그대로다 - 흔한 오해를 못박는다.

    게이트가 "다 돌렸는가" 를 셀 때 보는 것은 `hyp_` 로 시작하는 도구뿐이다
    (`graph/nodes.py`). 2단 도구를 빼는 것은 **LLM 이 헛호출로 바퀴를 태우는 것**을
    막을 뿐, 루프 예산의 산수를 바꾸지 않는다. 예산을 실제로 먹는 것은 상시 빈손인
    metro 축처럼 `hyp_` 인 축이다.
    """
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = ("from tools.agent_tools import TOOLS_BY_NAME as T; "
             "print(sum(1 for n in T if n.startswith('hyp_')))")

    counts = []
    for mode in ("off", "local"):
        p = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                           cwd=root, env={**os.environ, "SENSOR_MODE": mode})
        assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
        counts.append(p.stdout.decode().strip())

    assert counts[0] == counts[1]
