"""LangGraph 노드: 현황파악(고정) / 분석(LLM) / 도구 실행+게이트 / 리포팅(고정).

- 골격(status, report)은 고정 — 순서는 개발자가 못박는다.
- analyze ⇄ tools 순환 구간만 LLM 이 자율 판단한다.
- tools 노드는 세 가지를 한다:
    (1) 분석 tool 실행 (수치는 여기서만 나온다)
    (2) 감사 기록: 매 실행을 findings 에 {loop, tool, args, result, thought} 로 남긴다
    (3) finalize 게이트: LLM 의 종료 제안을 confidence 로 승인/반려 (LLM 은 제안, 코드가 결정)
"""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

import ya_config
from graph import evidence
from llm.client import get_llm
from tools import commonality as cm
from tools import grouping
from tools import yield_tools as yt
from tools.agent_tools import TOOLS_BY_NAME

_llm = None


def _llm_lazy():
    """LLM 획득을 첫 사용까지 미룬다 (미룸 8번).

    모듈 레벨에서 잡으면 **import 시점에** 구현이 고정된다. `config.LLM_MODE` 를
    바꾸거나 테스트에서 구현을 갈아끼우려면 그보다 먼저 import 되지 않았기를 빌어야
    했다 — import 순서에 좌우되는 동작이다. 여기서 잡으면 그 의존이 사라진다.
    """
    global _llm
    if _llm is None:
        _llm = get_llm()
    return _llm

ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 불량 그룹(유사 불량 wafer 들)과 대조 그룹(같은 lot 의 정상 wafer 들)을 비교해, 불량 그룹만의 공통 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. 그룹 간 차이(장비·파라미터)가 핵심 근거다 - 가설 도구(hyp_*)로 두 그룹을 대조하라.
- tool 을 호출할 때는 reason 인자에 현재 가설과 그 tool 을 고른 이유를 한 문장으로 반드시 담아라 - 이 서술이 그대로 분석 감사 기록에 남는다.
- 원인을 좁혔고 근거가 충분하면 finalize(claim_id, hypothesis, confidence) 로 종료를 제안하라. claim_id 는 가설 도구 결과의 후보에 실려 온 값을 **그대로** 옮겨야 한다 - 지어내거나 문장으로 대신하면 반려된다. 지목할 근거가 없어 물러설 때는 claim_id 를 비우고 낮은 확신도로 제출하라.
- **claim_id 는 결론 하나를 고르는 것이 아니라 서술의 축을 정하는 것이다.** 판별선을 넘은 후보는 게이트가 상한 안에서는 전부 접어서 줄 세워 리포트에 싣고, 상한을 넘는 것은 건수만 알린다 - 다른 축의 근거를 버릴까 걱정해 지목을 미루지 마라. 다만 순위 1등이 아닌 것을 지목하면 반려된다.
- **2단 센서(compare_sensor_distribution) 후보의 claim_id 는 근거 인용용이다.** finalize 로 지목할 수 있는 것은 가설 도구(hyp_*)가 발급한 claim_id 뿐이다 - 센서는 스텝당 수백 개라 다중비교 보정 없이 효과크기 순위만으로는 우연한 분리를 가릴 수 없어, 지목해도 원인으로 확정되지 않는다. 통과한 가설 도구(hyp_*) 후보가 있는데도 센서를 지목하면 그 이유로 반려된다 - 그럴 때는 통과한 hyp_* 후보를 대신 지목하라. 그렇다고 안 돌려도 된다는 뜻은 아니다: '왜' 를 채우는 근거이고, 그중 효과크기가 판별선을 넘은(passes=true) 후보만 게이트가 리포트에 함께 싣는다.
- **판별선을 넘지 못한 후보만 있으면 지목하지 마라.** 판단상 더 볼 축이 남아 있다면 그것부터 돌려보고, 그러고도 판별선을 넘는 후보가 없을 때 물러서라. 억지로 지목해도 게이트는 그 후보를 원인으로 확정하지 않는다. 아랫선을 넘은 잔차가 있으면 네가 도구 결과에서 실제로 받은 이름을 지목한 한 상한이 남는 한 그것을 근거로 싣지만, 잔차마저 없는 상태에서 지목하면 반려되고 같은 반려를 되풀이하면 루프 예산만 태운다 - 다만 등록 축을 도구 실패 없이 다 돌렸고 가설 도구 후보가 났는데 그 분리 점수가 전부 아랫선에도 못 미치면 게이트가 '갈리는 항목 없음' 으로 받으니 그때는 빈손으로 물러서라. 어느 쪽이든 물러서는 쪽이 낫다 - 빈손으로 내면 약한 후보를 원인으로 단언하는 문장을 애초에 쓰지 않게 된다.
- **등록된 가설 도구를 전부 돌릴 의무는 없다.** 한 축을 더 깊이 파는 것과 다음 축으로 넘어가는 것 중 무엇이 원인에 가까운지 매 단계 네가 고른다. 어디까지 봤는지는 코드가 세어 리포트에 함께 싣는다.
- 수치는 tool 결과를 그대로 인용하고 절대 임의로 만들지 마라."""


# ------------------------------------------------ 고정 골격: 현황 파악
def status_node(state: dict) -> dict:
    targets = state.get("target_wafers") or []
    source = state.get("target_source", "manual")
    if not targets:   # 자동 선정이 빈손 = 이상 없음 (수동 모드 빈 입력은 main 이 차단)
        return {"target_group": [], "control_group": [],
                "status_summary": "수율 임계 미만인 lot 없음 (자동 선정 결과 없음).",
                "findings": [], "finalize_status": "no_anomaly"}

    norm = grouping.normalize_target(targets)
    findings = [{"loop": 0, "tool": "normalize_target", "args": {"wafers": targets},
                 "result": norm, "thought": "대상 정규화 (고정 골격)"}]
    if norm["unknown_wafers"]:
        summary = f"입력 wafer 미존재: {', '.join(norm['unknown_wafers'])}"
        return {"target_group": [], "control_group": [], "status_summary": summary,
                "findings": findings, "finalize_status": "unknown_target"}
    if norm["eds_error"]:
        # 사유를 단정하지 않는다 — 인덱스 미등재·서비스 장애·인덱스 손상이 모두
        # 같은 예외로 온다. 구분은 사내 EDS 오류 응답 실측 뒤에(미룸 6번).
        summary = (f"분석 대상 입력 ({source}): {', '.join(targets)}\n"
                   f"EDS 유사맵 조회 실패: {norm['eds_error']} - "
                   f"wafer 는 yield DB 에 있으나 형제 묶기를 하지 못했다.")
        return {"target_group": norm["target_group"], "control_group": [],
                "status_summary": summary, "findings": findings,
                "finalize_status": "eds_lookup_failed"}
    if norm["isolated"]:
        summary = (f"분석 대상 입력 ({source}): {', '.join(targets)}\n"
                   f"형제 묶기 (EDS, 컷오프 {ya_config.SIBLING_MIN_SIMILARITY}): 형제 없음 - "
                   f"고립 패턴, 자동 분석 범위 밖.")
        return {"target_group": norm["target_group"], "control_group": [],
                "status_summary": summary, "findings": findings,
                "finalize_status": "isolated"}

    ctrl = grouping.select_control(norm["target_group"])
    findings.append({"loop": 0, "tool": "select_control",
                     "args": {"target_group": norm["target_group"]},
                     "result": ctrl, "thought": "대조군 선정 (고정 골격)"})
    summary = _summarize_target(source, targets, norm, ctrl)
    if ctrl["insufficient"]:
        return {"target_group": norm["target_group"],
                "control_group": ctrl["control_group"],
                "status_summary": summary, "findings": findings,
                "finalize_status": "control_insufficient"}

    groups_json = json.dumps(
        {"target": norm["target_group"], "control": ctrl["control_group"]},
        ensure_ascii=False)
    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n"
            f"불량 그룹: {', '.join(norm['target_group'])}\n"
            f"대조 그룹 (비타깃): {', '.join(ctrl['control_group'])}\n"
            f"분석 대상: {', '.join(targets)} 의 불량 원인 분석\n"
            f"GROUPS_JSON={groups_json}"
        )),
    ]
    return {
        "messages": seed,
        "target_group": norm["target_group"],
        "control_group": ctrl["control_group"],
        "status_summary": summary,
        "findings": findings,
    }


def _summarize_target(source: str, targets: list[str], norm: dict, ctrl: dict) -> str:
    lines = [f"분석 대상 입력 ({source}): {', '.join(targets)}"]
    if norm["mode"] == "single":
        sib = ", ".join(f"{s['wafer_id']}({s['similarity']})" for s in norm["siblings"])
        lines.append(f"형제 묶기 (EDS, 컷오프 {ya_config.SIBLING_MIN_SIMILARITY}): "
                     f"{len(norm['target_group'])}장 - 입력 + {sib}")
        if norm.get("unmatched_siblings"):
            lines.append(f"EDS 형제 중 yield DB 미확인 {len(norm['unmatched_siblings'])}장 "
                         f"제외: {', '.join(norm['unmatched_siblings'])} "
                         f"(인덱스/DB 동기화 확인 필요)")
    else:
        lines.append(f"그룹 입력: {len(norm['target_group'])}장 그대로 사용 (묶기 생략)")
    src = ", ".join(f"{rl} {len(ws)}장" for rl, ws in sorted(ctrl["sources"].items()))
    line = f"대조군 (같은 root_lot 비타깃): {len(ctrl['control_group'])}장 - {src}"
    ys = ctrl["yield_summary"]
    if ys:
        # 라벨이 없어 저수율 wafer 를 거를 수 없다 — 거르는 대신 분포를 보인다
        line += (f" · 수율 중앙값 {ys['median']}, 임계 {ys['threshold']} 미만 "
                 f"{ys['n_below_threshold']}장")
    lines.append(line)
    if ctrl["insufficient"]:
        lines.append(f"대조군 부족: {len(ctrl['control_group'])}장 < "
                     f"{ya_config.CONTROL_MIN_SIZE} (root_lot 내 대조 한계 - 추후 분석 필요)")
    return "\n".join(lines)


# ------------------------------------------------ 자유 루프: 분석 (LLM)
def analyze_node(state: dict) -> dict:
    """LLM 이 다음 행동을 고른다. 호출 실패는 예외로 내보내지 않는다.

    사내 LLM 은 타임아웃·5xx 를 낸다. 여기서 예외가 밖으로 나가면 그래프가 죽고,
    `main.py` 는 그래프를 **다 돌린 뒤** 출력하므로 현황·감사 기록이 통째로 사라진다
    (`ya_console.py` 가 막으려던 유실과 같은 것이 다른 경로로 나는 셈이다).
    도구 실패를 ToolMessage 로 복구하는 `tools_node` 와 같은 원칙으로, 실패를
    **사실로 기록하고** 리포팅으로 흘려보낸다 - tool_calls 없는 메시지를 남기면
    `_after_analyze` 의 기존 안전망이 report 로 보낸다.
    """
    loop = state.get("loop_count", 0) + 1
    try:
        ai = _llm_lazy().analyze_step(state["messages"])
    except Exception as e:
        note = f"LLM 분석 호출 실패 ({type(e).__name__}: {e})"
        return {
            "messages": [AIMessage(content=note)],   # tool_calls 없음 -> report 로
            "loop_count": loop,
            "findings": [{"loop": loop, "tool": "analyze", "args": {},
                          "result": note, "thought": ""}],
            "finalize_status": "llm_call_failed",
        }
    return {"messages": [ai], "loop_count": loop}


# ------------------------------------------------ 자유 루프: 도구 실행 + 게이트
def tools_node(state: dict) -> dict:
    ai = state["messages"][-1]
    loop = state["loop_count"]
    out_msgs, findings, update = [], [], {}
    stopped = False   # finalize 승인/한계 이후의 잔여 호출은 실행하지 않는다

    for call in ai.tool_calls:
        if stopped:
            # 실행은 건너뛰되 응답은 채운다 — LangChain 은 모든 tool_call_id 에
            # 대응하는 ToolMessage 를 요구한다. 감사 기록에도 생략 사실을 남긴다.
            skipped = "분석 종료로 생략 (finalize 판정 뒤의 잔여 호출)"
            out_msgs.append(ToolMessage(skipped, tool_call_id=call["id"],
                                        name=call["name"]))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": skipped, "thought": ai.content or "",
            })
            continue

        if call["name"] == "finalize":
            # 증거는 누적 findings + 이번 메시지에서 방금 실행된 tool 결과(findings)까지 포함
            verdict = _finalize_gate(call["args"], loop, update,
                                     state.get("findings", []) + findings)
            out_msgs.append(ToolMessage(verdict, tool_call_id=call["id"], name="finalize"))
            findings.append({
                "loop": loop, "tool": "finalize", "args": call["args"],
                "result": verdict, "thought": ai.content or "",
            })
            stopped = bool(update.get("finalize_accepted"))   # 반려는 종료가 아니다
        else:
            tool = TOOLS_BY_NAME.get(call["name"])
            args = call["args"]
            crashed = False
            if tool is None:
                # 등록되지 않은 이름이므로 **축의 실패가 아니다.** 실패로 세면
                # 커버리지가 없는 축의 장애를 보고한다.
                result = (f"오류: '{call['name']}' 는 존재하지 않는 tool 이다. "
                          f"사용 가능한 tool: {', '.join(TOOLS_BY_NAME)}. "
                          f"이 중에서 다시 선택해 호출하라.")
            else:
                args = _with_pipeline_groups(tool, args, state)
                try:
                    result = tool.invoke(args)
                except Exception as e:  # 인자 스키마 위반·조회 실패 등
                    result, recoverable = _tool_error_message(call["name"], tool, e)
                    # **LLM 이 제 인자를 고쳐 되살릴 수 있는 실패는 축의 실패가 아니다.**
                    # 찍으면 그 축이 `failed` 에 끈적하게 남아, 안내는 "고쳐서 다시
                    # 호출하라" 인데 게이트는 "부를 축이 없다" 로 끝내는 거울상 모순이
                    # 된다 - reason 한 번 헛디딘 것으로 멀쩡한 축을 영구히 버린다.
                    crashed = not recoverable
            out_msgs.append(ToolMessage(
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["id"], name=call["name"],
            ))
            finding = {
                # args 는 **실행된** 인자다. LLM 이 보낸 것을 적으면 감사 기록이
                # 실행과 다른 분모를 가리키고, 그것이 리포트의 근거 문장이 된다.
                "loop": loop, "tool": call["name"], "args": args,
                "result": result, "thought": ai.content or args.get("reason", ""),
            }
            if crashed:
                # **실패를 여기서 표시한다.** `build_bundle` 은 findings 만 보는데,
                # dict 가 아닌 결과가 실패만은 아니라(생략 메시지도 문자열이다)
                # 오류 문자열의 모양으로는 가를 수 없다. 이 표시가 없으면 터진 축이
                # '아직 안 돌린 축' 과 한 덩어리가 되고, 게이트는 방금 터진 도구를
                # 다시 부르라고 이름을 댄다.
                finding["failed"] = True
            findings.append(finding)

    return {"messages": out_msgs, "findings": findings, **update}


# 도구 인자 이름 -> 그 값을 확정한 state 키. **LLM 이 정하는 값이 아니다.**
_PIPELINE_GROUP_ARGS = {"group_ids": "target_group", "control_ids": "control_group"}


def _with_pipeline_groups(tool, args: dict, state: dict) -> dict:
    """대조 분모를 코드가 채운다 (LLM 제안, 코드 결정).

    타깃·대조군은 고정 골격(`status_node`)이 확정하고 리포트 머리말·커버리지·대조군
    선정 근거가 전부 그 위에 서 있다. LLM 이 이 인자를 정할 수 있던 동안에는 **머리말과
    다른 분모로 계산된 후보**가 결론이 될 수 있었고, 게이트는 claim_id 조회만 하므로
    그 어긋남을 볼 방법이 원리적으로 없었다.

    **어떤 도구에 넣을지는 이름이 아니라 도구가 선언한 인자로 판정한다.** 이름으로
    고르면 축이 늘 때마다 여기를 같이 고쳐야 하고, 안 고치면 새 축만 조용히 옛
    계약으로 돈다. `tool.args` 는 주입 인자를 이미 빼고 주므로 전체 스키마를 본다.

    **state 에 그 값이 없으면 빈 그룹으로 채우지 않고 터뜨린다.** 조용히 `[]` 를 넣으면
    도구는 인자를 받은 셈이라 예외가 안 나고, 대조군만 빠진 경우 결과가
    `no_paired_stratum`("타깃과 같은 root_lot 에 속한 대조군 wafer 가 없다")이 된다 —
    엔지니어는 대조군 선정을 다시 하거나 EDS 확장을 뒤지러 가고, 진짜 원인(파이프라인이
    분모를 안 넣었다)은 아무 데도 안 남는다. 빈 리스트는 다르다:
    그건 누락이 아니라 고정 골격이 정한 값이고, 대조군 부족은 이미 status_node 가
    판정해 리포트로 보낸다.
    """
    declared = tool.args_schema.model_json_schema().get("properties", {})
    injected = {}
    for arg, key in _PIPELINE_GROUP_ARGS.items():
        if arg not in declared:
            continue
        if state.get(key) is None:
            # KeyError 가 아니라 RuntimeError 인 이유: 진짜 키 누락 버그와 구분되고,
            # 테스트가 "가드가 있다" 를 볼 수 있다 - KeyError 면 가드를 지워도 바로
            # 아래 state[key] 가 같은 예외를 내서 훼손이 안 잡힌다.
            raise RuntimeError(f"{key} 가 state 에 없다 - {arg} 를 주입할 수 없다 "
                               f"(고정 골격 status_node 를 거치지 않은 경로다).")
        injected[arg] = list(state[key])
    return {**args, **injected}


# 값이 바뀌어도 계산이 달라지지 않는 인자. 재호출 안내의 근거에서 뺀다.
_INERT_ARGS = {"reason"}

# LLM 이 손댈 수 없는 실패일 때의 안내. 재호출을 시키지 않는다.
_PIPELINE_ARG_ADVICE = ("이 도구의 대상·대조군은 파이프라인이 정한 값이라 네가 바꿀 수 "
                        "없다. 같은 호출을 반복하지 말고 다른 축(hyp_*)을 시도하거나 "
                        "finalize 하라.")


def _tool_error_message(name: str, tool, e: Exception) -> tuple[str, bool]:
    """실패 안내는 **LLM 이 아직 바꿀 수 있는 인자가 있는지**로 갈린다.

    `(안내, 복구 가능한가)` 를 돌려준다. 두 번째 값은 **재호출로 되살아날 수 있는
    실패인가** 이고, `tools_node` 가 그것으로 감사 기록의 실패 표시를 가른다 - 안내와
    표시가 다른 기준을 쓰면 "고쳐서 다시 호출하라" 고 해 놓고 그 축을 실패로 세는
    모순이 난다. 판정을 한 곳에서만 하려고 여기서 함께 돌려준다.

    대조 분모는 스키마에서 빠져 LLM 이 못 본다(`_with_pipeline_groups`). 그런데도
    "인자를 확인하고 다시 호출하라" 고 하면, 바꿀 것이 reason 뿐인 hyp_* 는 같은
    호출을 MAX_LOOPS 까지 반복하고 inconclusive 로 떨어진다 — 쓸 수 없는 도구를
    아예 등록하지 않는 `tools/agent_tools.py` 와 같은 이유로 여기서 막는다.
    `tool.args` 는 주입 인자를 이미 빼고 주므로 LLM 이 보는 것과 같다.

    **인자 스키마 위반은 먼저 가른다.** reason 은 계산에 안 쓰여 `_INERT_ARGS` 에
    있지만 검증은 받으므로, 형식 오류의 **원인**일 수 있다 - "바꿀 인자가 남았는가"
    만으로 가르면 "reason 은 문자열이어야 한다" 를 인용하면서 고칠 수 없다고 답하고,
    LLM 이 한 번 헛디디면 멀쩡한 축을 영구히 버린다. 원인 인자가 LLM 소관일 때만
    재호출을 시킨다(주입된 분모가 깨진 경우는 아래 규칙으로 내려간다).

    이 판정은 **도구 스키마가 pydantic v2 라는 전제**에 서 있다. langchain 은 v1
    스키마도 받아 `pydantic.v1.ValidationError` 를 그대로 올려 보내므로, v1 로 만든
    도구가 섞이면 여기서 안 걸려 위 실패가 되살아난다. 지금 저장소의 도구는 전부
    `@tool`/`StructuredTool.from_function` 이라 v2 다 — 그런 도구가 생기면 여기를 늘린다.
    """
    head = f"오류: {name} 실행 실패 ({type(e).__name__}: {e}). "
    if isinstance(e, ValidationError):
        bad = {str(err["loc"][0]) for err in e.errors() if err.get("loc")}
        # 원인에 주입 인자가 하나라도 섞이면 LLM 소관이 아니다. LLM 인자만 지목해
        # 재호출시키면 그것을 고쳐도 같은 자리에서 또 죽는다. 아래 `changeable` 로
        # 흘려보내도 안 된다 - 바꿀 인자가 남은 도구(센서)는 원인과 무관한
        # step_seq 를 고치라고 답하게 된다.
        if bad:
            if bad <= set(tool.args):
                return (head + f"인자 {', '.join(sorted(bad))} 의 형식이 잘못됐다. "
                        f"고쳐서 다시 호출하라.", True)
            return head + _PIPELINE_ARG_ADVICE, False
    # 아래 둘은 실행 자체가 터진 것이다(조회 실패 등). 인자를 바꾸면 다른 대상을 볼 수
    # 있을 뿐 같은 대조가 되살아나지는 않으므로 축의 실패로 센다. hyp_* 는 `changeable`
    # 이 항상 비어 있어(LLM 인자가 reason 뿐) 이 구분이 실제로 갈리는 곳은 센서뿐이고,
    # 센서는 등록 축이 아니라 커버리지에 안 잡힌다.
    changeable = sorted(set(tool.args) - _INERT_ARGS)
    if changeable:
        return head + f"인자를 확인하고({', '.join(changeable)}) 다시 호출하라.", False
    return head + _PIPELINE_ARG_ADVICE, False


def _evidence_groups(bundle, passing_groups: list) -> list:
    """근거로 실을 묶음. **지목 가능한 통과 후보가 없을 때만 잔차를 더한다.**

    이 하한이 곧 접기 계약의 전제다 - 합집합의 비센서 claim 이 전부 미통과라야
    `_fold_key` 가 통과 claim 과 잔차를 한 묶음에 섞지 않는다(B 설계 §4 · C 계약).
    하한을 지우면 p 가 작은 잔차가 lead 를 뺏어, 통과 근거가 `passes` 키도 없는
    `confounded_with` 로 강등돼 묶음 전체가 `[잔차]` 로 찍힌다 - 통과 근거가
    있는데도.

    **잔차를 안 더할 때는 받은 목록을 그대로 돌려준다.** `ranked_groups()` 는
    호출마다 새 `ClaimGroup` 을 만들어(`find_group` docstring 의 경고) 다시
    만들면 호출부의 `picked` 와 `is` 비교가 항상 거짓이 되고, 아무 claim 에도
    `picked_by_llm` 이 안 붙는다.

    네 자리((2a)·(2b)·(4)·백스톱)가 같은 규칙을 쓴다. 규칙을 네 번 적으면 한 자리를
    빠뜨리는 것이 이 저장소의 반복 결함이다.
    """
    residuals = bundle.residuals()
    if bundle.statistical_passing() or not residuals:
        return passing_groups
    return bundle.ranked_groups(bundle.passing() + residuals)


def _honest_pick(bundle, claim_id: str) -> bool:
    """물러섬 판정((2a)·(2b))의 하한 - **정직한 제출인가.**

    빈손이거나 도구 결과에서 실제로 받은 이름이면 참이고, **지어낸 이름만** 거짓이다.

    **대체(superseded)된 앞 실행의 후보도 정직한 제출이다.** `tools_node` 가 도구
    결과를 ToolMessage 로 대화에 실으므로, 축을 다시 돌린 뒤에도 LLM 은 앞 실행의
    claim_id 를 자기 문맥에서 그대로 보고 제출한다 - 지어낸 것이 아니다.
    `bundle.claims` 조회만으로 하한을 걸면 그 제출이 환각과 **같이** 반려된다. 전축을
    다 보고 아무것도 안 갈린 실행인데, 지목했다는 이유만으로 물러설 길이 닫힌다.

    ⚠️ **이 절이 루프 한계를 막는 것은 아니다**(2026-09-12 이후). 한계에서는
    `_gate_verdict` 가 승인이 못 받는 지목(환각·센서·대체 이름·판별선 미달)을
    **버리고** 상태로 판정하므로, 대체 이름은 이 절이 없어도 같은 사유로 끝난다.
    이 절이 지금 하는 일은 **한계 아래**에서 반려 대신 (2a)·(2b)를 여는 것이다 -
    반려를 되풀이하다 한계에 닿는 왕복 자체를 줄인다.

    ⚠️ **이 하한을 다시 좁히면 `(4)` 의 `carried is not groups` 갈래가 되살아난다.**
    지금 그 갈래가 도달 불가인 것은 한계에서 이 절이 늘 참이기 때문이고(근거는
    `_gate_verdict` 의 `(4) 루프 한계 도달` 블록에서 `carried = _evidence_groups(...)`
    를 감싼 주석), 좁히는 순간 잔차가 `(4)` 로 다시 타기 시작한다 - 손대기 전에 그
    갈래를 먼저 볼 것. **줄 번호로 적지 않는다** - 이 파일은 자주 늘어나 각주가 곧
    엉뚱한 분기를 가리킨다(재리뷰가 실제로 잡았다).

    **규칙을 한 자리에만 적는다.** (2a)·(2b) 두 분기가 같은 하한을 쓰므로 각자
    적으면 한쪽만 고치는 이 저장소의 반복 결함이 그대로 재발한다.
    """
    return (not claim_id
            or claim_id in bundle.claims
            or claim_id in bundle.dropped_claims)


def _approvable_pick(claim) -> bool:
    """이 지목으로 (1) 승인이 성립할 수 있는가 - **도구가 낸 사실만 본다.**

    거짓인 경우가 넷이다: 번들에 없는 이름(환각) · 대체된 앞 실행의 이름(역시 claims
    에 없다) · 2단 센서 claim(근거로는 실리되 지목 대상이 아니다 - (1)의 `kind` 하한) ·
    **판별선을 못 넘은 claim**((1)의 `passes` 하한).

    **확신도와 등수는 일부러 안 본다.** 그 둘은 "지목은 쓸 수 있는데 이번엔 모자랐다"
    이고 빈손 제출도 같은 자리에서 막히므로 제출 형태에 따른 비대칭이 안 생긴다.
    `passes` 는 다르다 - 확신도는 LLM 이 올릴 수 있고 등수는 축을 더 돌리면 바뀌지만,
    `passes` 는 **도구가 발급한 사실**이라 루프 한계에서는 바꿀 회차가 없다. 남겨 두면
    실재한다는 이유로 `(2)` 의 `not claim_id` 하한에 걸려, 정직하게 지목한 쪽이
    환각보다 나쁜 사유를 받는다(실측: 부분 커버리지에서 빈손·환각은 `no_signal` 인데
    실재하는 약한 후보 지목은 `inconclusive` + 커버리지 문장 소실).
    """
    return claim is not None and claim.kind != "sensor" and claim.passes


def _drop_reason(bundle, claim_id: str, claim) -> str:
    """버린 지목을 판정문에서 어떻게 부를 것인가. **넷을 뭉개지 않는다** - 다음에 할
    일이 다르다(가설 도구의 claim 을 지목하라 / 판별선을 넘은 것을 지목하라 /
    재실행 결과를 보라 / 지어내지 마라).
    """
    # **`_approvable_pick` 과 같은 술어를 쓴다.** 여기서 `claim is not None` 하나로
    # 센서를 판정하면 그쪽이 넓어지는 순간 이 문장이 조용히 거짓이 된다 - 가설 도구의
    # 챔버 후보를 "2단 센서" 라고 부르게 된다(재리뷰 I-1 이 실제로 잡은 자리다).
    if claim is not None and claim.kind == "sensor":
        return "2단 센서 근거라 지목 대상이 아니어서"
    if claim is not None:
        return "판별선을 넘지 못해 승인 대상이 아니어서"
    if claim_id in bundle.dropped_claims:
        # **어느 축인지 이름을 댄다.** `_superseded_note` 와 같은 정보를 손에 쥐고
        # 있으면서 "같은 축" 으로 뭉개면, 리포트 LLM 이 "어느 재실행 결과를 보라" 를
        # 말할 수 없다 - 다음에 할 일을 가리키는 것이 이 네 갈래의 존재 이유다.
        return f"{bundle.dropped_claims[claim_id]} 를 다시 돌려 대체된 앞 실행의 후보라"
    return "도구 결과에 없어"


def _drop_unapprovable_pick(bundle, loop: int, claim_id: str, claim):
    """루프 한계에서 승인이 못 받는 지목을 버린다. 돌려주는 것은 `(claim_id, claim,
    버린 것)` 이고, 안 버렸으면 받은 것을 그대로 + `None` 이다.

    **루프 한계는 종료 트리거이지 사유가 아니다.** 승인이 못 받는 지목은 (2a)·(2b)의
    "정직한 제출" 하한이나 (2)·(3)·(3b)의 `not claim_id` 하한에 걸려 다섯 문이 닫히고,
    그래서 같은 증거 상태가 **마지막 제출 형태에 따라** 다른 사유로 끝났다(실측:
    빈손이면 weak_signal, 환각이면 inconclusive). 엔지니어가 받는 조치가 달라진다 -
    "표본을 늘려라" 와 "분석이 예산 안에 못 끝났다" 는 다른 말이다. 한계에 닿았으면
    지목을 버리고 증거 상태로 판정한다. 버린 사실은 껍데기(`_finalize_gate`)가
    판정문에 남긴다.

    **하한은 `_honest_pick` 이 아니라 `_approvable_pick` 이다.** 정직하지만 승인이
    못 받는 지목이 셋 있다 - 2단 센서 claim · 대체된 앞 실행의 이름 · 판별선을 못 넘은
    실재 claim. 환각만 버리면 그 셋은 `claim_id` 가 살아 있는 채 (2)·(3)·(3b) 하한에
    걸려, **정직하게 지목한 쪽이 환각보다 나쁜 사유를 받는다**(실측: 빈손·환각은
    no_signal 인데 센서 지목·약한 후보 지목은 inconclusive 였다).

    **한계 아래에서는 버리지 않는다.** 반려는 LLM 에게 고칠 기회를 주는 것이고,
    여유가 있는데 버리면 환각을 내고도 종료를 얻어 억제가 사라진다.

    **`claim_id` 만이 아니라 `claim` 도 비운다.** 지금은 버린 뒤 `claim` 을 읽는
    도달 가능한 경로가 없어서((1)은 위에서 끝나고 (2a)·(2b)는 `not claim_id` 뒤에서만
    읽는다) 게이트를 통째로 돌리는 테스트로는 이 한 줄이 안 잠긴다 - 남겨 두면 나중에
    소비자가 하나 붙는 순간 "버렸는데 살아 있는" 값이 조용히 읽힌다. 규칙을 여기
    한 함수에 모아 **직접** 단언할 수 있게 한 이유다.
    """
    if loop < ya_config.MAX_LOOPS or not claim_id or _approvable_pick(claim):
        return claim_id, claim, None
    return "", None, (claim_id, _drop_reason(bundle, claim_id, claim))


def _superseded_note(bundle, claim_id: str) -> str:
    """대체된 이름을 지목한 제출에 붙는 판정문 조각.

    **"판별선을 넘지 못해"/"아랫선에도 못 미쳐" 로 뭉개면 거짓이 된다** - 대체된
    후보는 통과했던 것일 수도 있고(M3 의 `EVIDENCE_FINDING_NEW` 가 그 모양이다)
    번들에 없으니 점수를 볼 수도 없다. 확정하지 않는 이유는 점수가 아니라 **그
    실행이 대체됐다는 것**이다. `_gate_rejection` 의 대체 문구와 같은 뜻으로 쓴다.
    """
    return (f"네가 지목한 {claim_id} 는 {bundle.dropped_claims[claim_id]} 를 다시 "
            f"돌려 대체된 앞 실행의 후보라 원인으로 확정하지 않았다. ")


def _no_separation_state(bundle, coverage: dict) -> bool:
    """(2b) '갈리는 항목 없음' 이 성립하는 상태인가 - **claim_id 하한은 빼고**.

    게이트 판정과 물러섬 안내(`_no_candidate_action`)가 **같은 것을 봐야 한다.**
    판정만 만들고 안내를 안 고치면 그 상태에서 "claim_id 를 비우고 finalize
    하라" 가 안 붙어 문이 열려 있는 줄도 모르고 루프 한계까지 왕복한다 -
    (3)이 실제로 겪었던 라이브락이다. 이 함수는 게이트 안이 아니라도(Task 5 가
    물러섬 안내에서 재사용한다) 참이어야 하므로, `_gate_verdict` 안의 분기
    순서(예: (2a)가 먼저 걸러 준다는 것)에 기대지 않고 조건 하나하나가 스스로
    성립해야 한다.

    `not unrun and not failed`: "더 볼 것이 없었다" 는 (3)과 같은 성격의 주장이라
    전축을 봐야 참이다. 부분 커버리지로 열면 근거 0건짜리 리포트로 조기 종료해
    있을지 모를 신호를 스스로 달아난다.

    `not statistical_passing()`: 통과 후보가 있으면 "안 갈렸다" 가 거짓이다.
    아래 점수 조건(`all(score < RESIDUAL_MIN_SCORE)`)이 통상적으로는 이것을
    함의한다 - 통과는 `COMMONALITY_PASS_MIN_SCORE`(기본 0.5) 이상을 요구하고
    그 값은 `RESIDUAL_MIN_SCORE`(0.25)보다 크게 설계됐다. 하지만 둘은 각각
    독립된 환경변수라 코드가 그 대소를 강제하지 않는다 - 설정이 어긋나면
    점수 조건만으로는 통과 후보를 걸러내지 못하므로, 이 조건을 별도로 남겨
    둔다.

    `any(kind != "sensor")`: **후보가 하나도 안 난 상태(전축 no_signal)는 (2)다.**
    `status: "ok" if candidates else "no_signal"` 이므로 이 조건은 "1단 후보가
    실제로 났다" 와 같은 뜻이고, 판정문의 최고 점수를 쓸 수 있다는 보장도 된다.

    `all(score < RESIDUAL_MIN_SCORE for kind != "sensor")`: **"안 갈렸다" 를
    말하는 진짜 사실.** `bundle.residuals()`(그래서 `not residuals()`)는 이
    대용이 못 된다 - `residuals()` 는 `status == "ok"` · `target_pass >=
    COMMONALITY_PASS_MIN_TARGET` 까지 함께 요구하는 5조건 연언이라, 표본이
    얇아 반려된 완전 분리 후보(예: score 1.0 인데 target_pass 1 < 2)는
    `residuals()` 에도 안 잡혀 `not residuals()` 가 참이 된다. 그 상태로
    "갈리는 항목 없음" 을 내보내면 실제로는 완전히 갈린 챔버를 안 갈렸다고
    말하는 거짓 판정문이 나간다 - 그래서 점수를 직접 본다. 점수 조건이
    `residuals()` 의 점수 조건(`score >= RESIDUAL_MIN_SCORE`)을 논리적으로
    함의하므로 `not bundle.residuals()` 는 더 이상 따로 적지 않는다(같은
    규칙을 두 자리에 적지 않는다).
    """
    return (not coverage["unrun"] and not coverage["failed"]
            and not bundle.statistical_passing()
            and any(c.kind != "sensor" for c in bundle.claims.values())
            and all(c.score < ya_config.RESIDUAL_MIN_SCORE
                    for c in bundle.claims.values() if c.kind != "sensor"))


def _finalize_gate(args: dict, loop: int, update: dict, findings: list[dict]) -> str:
    """판정에 **버린 지목**을 덧붙여 돌려주는 얇은 껍데기. 판정 자체는 아래 함수다.

    루프 한계에서 승인이 못 받는 지목(환각·2단 센서·대체된 이름·판별선 미달)을 버릴 수
    있는데(`_drop_unapprovable_pick` 참조), 그 사실은 판정문에
    남아야 한다 - 이 문자열은 findings 를 타고 리포트 LLM 까지 가고 프롬프트는 그것을
    "그대로 인용하라" 고 지시한다. 판정 분기가 여럿이라 각 분기 문구를 고치는 대신
    여기서 한 번만 붙인다.
    """
    verdict, dropped = _gate_verdict(args, loop, update, findings)
    if dropped:
        claim_id, why = dropped
        # **코드가 결론을 직접 적는 자리는 문자열을 뒤지게 두지 않는다.** 아래 판정문은
        # LLM 계약이고, 리포트 생성 실패 폴백은 `final_hypothesis`(버린 후보를 원인으로
        # 단정했을 수 있는 LLM 문장)를 그대로 찍는다 - 그쪽이 볼 구조적 신호다.
        update["dropped_pick"] = claim_id
        # **"루프 한계" 를 사유로 적지 않는다.** 한계는 종료 트리거이고 사유는 위
        # 판정문이 이미 말했다 - 여기에 한계를 또 적으면 그 사유가 루프를 다 썼기
        # 때문인 것처럼 읽힌다.
        verdict += (f" (마지막 제출 claim_id '{claim_id}' 는 {why} 무시하고 증거 "
                    f"상태로 판정했다.)")
    return verdict


def _gate_verdict(args: dict, loop: int, update: dict,
                  findings: list[dict]) -> tuple[str, tuple[str, str] | None]:
    """LLM 의 종료 제안을 코드가 최종 판정한다 (부품 4b). **판정문과 버린 지목을 함께
    돌려준다** - 버린 지목은 최대 하나이고, 없으면 `None` 이다.

    승인 실권은 confidence 자기 신고도, LLM 이 쓴 문장도 아니라 **EvidenceBundle
    조회 결과**에 있다. LLM 은 도구가 발급한 claim_id 를 지목하고, 게이트는 그
    claim 이 판별선을 넘었는지와 **축을 가로지른 순위에서 1등 묶음인지**를 확인한다.

    게이트의 성격이 바뀌었다: 예전에는 "LLM 이 고른 하나를 승인/반려" 하는 이진
    판정이었고, 지금은 **통과 후보 전부를 접어서 줄 세운 뒤 종료**한다. LLM 의
    지목은 서술의 축을 정할 뿐이고, 무엇이 근거로 남는지는 코드가 정한다.
    예전 계약은 도구 안 최고 점수 하나만 승인해서, 축이 여럿일 때 나머지 근거가
    리포트에 도달하지 못했다(같은 wafer 를 가리키는 교락도 구분되지 않았다).

    판정은 위에서부터 처음 걸리는 줄로 결정된다:
      (1) 지목한 claim 이 통과 + **가설 도구 발급** + 1등 묶음 + 확신도 충족 -> confirmed
          (2단 센서 claim 은 근거로 실리되 지목 대상이 아니다.)
      (2a) 통과 후보 0 + 아랫선을 넘은 잔차 있음 + 제출이 정직함(빈손이거나 실재하는
           claim_id) -> weak_signal
           ((2)보다 앞이다. 두 조건이 동시에 참일 때 정보가 더 많은 쪽이 이긴다.)
      (2b) 전축 대조 + 통과 0 + 비센서 후보가 났고 그 점수가 전부 아랫선 미만
           + 제출이 정직함 -> no_separation
           ((2)보다 앞이다. "볼 것이 안 났다"(2)와 "봤는데 안 갈렸다"는 다른 사실이다.
           "잔차 0" 이 아니다 - 표본이 얇아 미통과인 완전 분리 후보도 잔차에는 안
           잡히지만 점수로 보면 갈린 것이다. "후보가 났고" 를 빠뜨리면 `all(...)`
           이 공집합에서 공허하게 참이 되어 이 목록이 전축 침묵 상태(=(2))까지
           포함하는 거짓이 된다.)
      (2) 지목 없이 물러섰는데 통과 후보 0 + no_signal 있음 -> no_signal
          (전축 실행은 전제 조건이 아니다. 어디까지 봤는지는 coverage 로 나간다.)
      (3) 지목 없이 물러섰고 등록 가설을 다 돌렸는데 전부 '계산 불가' -> no_comparable_data
          ((2)와 달리 전축을 요구한다. "볼 것이 없었다" 는 부분 커버리지로는 참이 아니다.)
      (3b) 같은 자리인데 못 본 이유가 **도구 실패** -> tool_failure
          (사실은 (3)과 겹치지만 조치가 다르다: 적재 범위 확인이 아니라 인프라 확인.)
      (4) 루프 한계 -> inconclusive (승인이 아니라 '미확정')
      (5) 그 외 -> 반려. 무엇이 모자란지 그대로 돌려준다.

    **루프 한계에서는 위 목록을 타기 전에 지목을 한 번 거른다**(`_drop_unapprovable_pick`
    - 규칙과 근거는 그 독스트링에 있고 여기 두 번 적지 않는다). 승인이 못 받는
    지목(환각·2단 센서·대체된 이름·판별선 미달)은 버리고 빈손으로 본다 - 그러지 않으면
    (2a)·(2b)의 "정직한 제출" 하한과 (2)·(3)·(3b)의 `not claim_id` 하한에 걸려, 종료
    사유가 증거 상태가 아니라 **마지막 제출 형태**에 끌려간다. 버린 것은 반환값 둘째
    자리에 (claim_id, 사유) 한 쌍으로 실어 껍데기(`_finalize_gate`)가 판정문에 덧붙인다.
    """
    bundle = evidence.build_bundle(findings)
    conf, conf_note = _confidence(args.get("confidence", 0.0))
    hypothesis = args.get("hypothesis", "")
    claim_id = (args.get("claim_id") or "").strip()
    claim = bundle.claims.get(claim_id)
    claim_id, claim, drop = _drop_unapprovable_pick(bundle, loop, claim_id, claim)
    # **반려 경로에서는 상태에 쓰지 않는다.** 쓰면 loop 1 에 종료 제안했다가
    # 반려당하는 흔한 경로에서 `ran: []` 가 굳고, 그 뒤 축을 더 돌려도 갱신은 다음
    # finalize 때만 일어난다 - 마지막 finalize 없이 루프 한계로 끝나면 다 돌린 축을
    # 하나도 안 돌렸다고 보고한다. 커버리지는 **종료된 판정의 기록**이다.
    coverage = _coverage(bundle)
    unrun = coverage["unrun"]
    failed = coverage["failed"]
    groups = bundle.ranked_groups()
    picked = evidence.find_group(groups, claim_id) if claim_id else None
    # 등수는 목록과 **같은 객체**로 맞춘다. `find_group` 이 목록에서 꺼낸 바로 그
    # 객체를 돌려주므로 `is` 로 찾는다 - 다시 만들면 조용히 어긋난다(그 함수의
    # docstring 이 경고하는 함정이 이것이다).
    ranks = evidence.layer_ranks(groups)
    picked_rank = next((r for g, r in zip(groups, ranks) if g is picked), None)

    # (1) 승인
    if (claim is not None and claim.passes
            # **센서는 지목 대상이 아니다.** 근거로는 아래 _record_evidence 가 함께
            # 싣지만, 다중비교 보정을 일부러 안 한 도구(스텝당 센서 수백 개)를 단독
            # 승인 근거로 열면 1단이 빈손일 때 효과크기 하나로 confirmed 가 나간다.
            # `_is_statistical` 로 대신 걸면 참조 회차 0인 1단 후보까지 함께 막혀
            # 순위 계약이 흔들린다 - 그래서 kind 로 명시한다.
            and claim.kind != "sensor"
            and picked_rank == 1
            and conf >= ya_config.CONFIDENCE_THRESHOLD):
        update["finalize_accepted"] = True
        update["finalize_status"] = "confirmed"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        # **통과 후보를 전부 싣는다.** LLM 이 고른 것만 남기면 나머지 축의 근거가
        # 여기서 사라진다 - 그게 예전 계약의 결함이었다.
        update["coverage"] = coverage
        _record_evidence(update, groups, picked)
        # 머리말은 **LLM 이 지목한 묶음**으로 쓴다. 1등이 여럿일 때 groups[0] 을 쓰면
        # "승인" 이라면서 제출한 것과 다른 claim 의 수치를 보여 주게 되고, LLM 이
        # 산문에서 엉뚱한 claim 을 인용하게 된다.
        head = evidence.format_group_line(
            next(c for c in update["final_claims"] if c.get("picked_by_llm")))
        more = (f" 그 밖에 {len(groups) - 1}개 근거를 함께 싣는다."
                if len(groups) > 1 else "")
        return f"승인 (근거 확인): {head}.{more} 리포팅으로 진행한다.", drop

    # (2a) 약한 신호 - 판별선은 못 넘었지만 아랫선을 넘은 후보가 있다.
    #      "봤고 후보도 났는데 이 표본으로는 확정할 만큼 갈리지 않았다" 는 (2)의
    #      "대조한 축에서 갈리는 것이 없었다" 와 **다른 사실**이고 조치도 다르다 -
    #      잔차는 표본을 늘리거나 대조군을 바꾸면 갈릴 수 있다. 그래서 no_signal 로
    #      뭉개지 않고 이름을 따로 준다.
    #
    #      **(2)보다 앞이다.** 한 축은 침묵하고 다른 축은 ok + 약한 후보를 낸 상태에서
    #      두 조건이 동시에 참인데, 정보가 더 많은 쪽이 이겨야 한다. 뒤에 두면 그 상태가
    #      no_signal 로 먼저 빠져나가 잔차가 또 소각된다.
    #
    #      **하한은 `not claim_id` 가 아니라 "정직한 제출" 이다.** 빈손일 때만 열면
    #      이 문이 LLM 의 협조에만 열린다 - 약한 후보를 지목하는 순간 닫혀 (5) 반려로
    #      가고, 반려를 되풀이하면 루프 한계에서 잔차가 그대로 소각된다(이 기능이
    #      없애려던 상태). 하한은 번들 전체를 보므로 잔차도 센서도 포함하고,
    #      **지어내지 않은 이름만** 통과시킨다 - 환각은 "이 표본으로는 갈리지
    #      않았다" 와 다른 사실이라 같은 이름을 주면 안 된다.
    #      **대체(superseded)된 앞 실행의 후보는 정직한 제출로 친다** - 지어낸 것이
    #      아니라 LLM 이 자기 문맥에서 실제로 받은 이름이다. 판정 근거는
    #      `_honest_pick` 독스트링에 있다.
    #      `not bundle.statistical_passing()` 은 **그대로 둔다.** 이것이 남아 있어야
    #      `passing() + residuals` 의 비센서 claim 이 전부 미통과라 `_fold_key` 가
    #      통과 claim 과 잔차를 한 묶음에 섞지 않는다(설계 §4).
    residuals = bundle.residuals()
    if (not bundle.statistical_passing() and residuals
            and _honest_pick(bundle, claim_id)):
        update["finalize_accepted"] = True
        update["finalize_status"] = "weak_signal"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["coverage"] = coverage
        # **통과 근거를 밀어내지 않는다.** 이 분기의 하한은 statistical_passing()
        # 이라 센서만 통과한 상태에서도 열린다 - 잔차만 실으면 판별선을 넘은 센서
        # 근거가 리포트에서 사라진다. picked 는 넘기지 않는다 - 지목이 있을 수
        # 있지만(하한이 "정직한 제출" 로 넓어졌다) 그것을 **원인으로 확정하지
        # 않기로** 했기 때문이다. picked_by_llm 을 붙이면 리포트가 그 후보를
        # 서술의 축으로 삼아 단정하게 된다.
        _record_evidence(update, _evidence_groups(bundle, groups), None)
        if not claim_id:
            picked_note = ""
        elif claim is None:
            # 하한을 통과했는데 번들에 없다면 **대체된 이름뿐**이다 - 환각은
            # `_honest_pick` 이 이미 걸렀다.
            picked_note = _superseded_note(bundle, claim_id)
        elif claim.kind == "sensor":
            picked_note = f"네가 지목한 {claim_id} 는 2단 센서라 원인으로 확정하지 않았다. "
        else:
            picked_note = (f"네가 지목한 {claim_id} 는 판별선을 넘지 못해 "
                           f"원인으로 확정하지 않았다. ")
        # **절단 전 `len(residuals)` 가 아니라 실제로 실린 수를 말한다.**
        # `_record_evidence` 의 상한은 통과 근거(여기서는 통과한 2단 센서)를 먼저
        # 예약하고 남는 자리만 잔차로 채우므로, 통과 근거가 상한을 채우면 잔차는
        # 한 건도 안 실릴 수 있다 - 그런데도 절단 전 수를 찍으면 리포트에 없는
        # [잔차] 줄을 가리키는 판정문이 나간다(Task 6 리뷰 I-2).
        residual_note = _residual_evidence_note(update)
        return (f"약한 신호 ({_coverage_phrase(coverage)}): {picked_note}"
                f"판별선을 넘은 원인 후보는 없고, {residual_note}"
                f"확정이 아니라 '이 표본으로는 갈리지 않았다' 는 뜻이다. "
                f"리포팅으로 진행한다."), drop

    # (2b) 갈리는 항목 없음 - 전축을 대조했는데 비센서 후보가 났고 그 점수가 전부
    #      아랫선 미만이다.
    #      "봤는데 아무것도 안 갈렸다" 를 말하는 판정이 없어서, 이 상태는 출구가
    #      루프 한계뿐이었다 - 엔지니어는 실제로 일어난 일과 다른 사유("미확정 -
    #      루프 한계 도달")를 본다(실측 재현, 조사 §2.2).
    #
    #      **(2)보다 앞이다.** 한 축은 no_signal, 다른 축은 ok + 약한 후보인 상태에서
    #      두 조건이 동시에 참인데, (2) 뒤에 두면 빈손 제출은 no_signal 이고 지목한
    #      제출은 no_separation 이라 **같은 증거가 제출 형태에 따라 다른 판정**을
    #      받는다. (2a)를 (2) 앞에 둔 것과 같은 원칙이다.
    #      (3)과는 배타적이다 - (3)은 status 가 전부 NO_DATA 일 때만 열리는데
    #      여기는 비센서 claim 이 있어야 한다(= 1단 후보가 실제로 났다). 그래서
    #      (3) 앞뒤는 아무 효과가 없다.
    #
    #      하한이 "정직한 제출" 인 이유는 (2a)와 같다 - 약한 후보를 지목했다고 문을
    #      닫으면 반려를 되풀이하다 루프 한계로 빠져 이 판정이 없애려는 상태가 그대로
    #      재발한다. 환각만 반려한다(`_honest_pick`).
    if _no_separation_state(bundle, coverage) and _honest_pick(bundle, claim_id):
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_separation"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["coverage"] = coverage
        # 정의상 통과 후보도 잔차도 없어 목록은 비거나 통과 센서만 남는다.
        # picked 는 안 붙인다 - (2a)와 같은 이유로 원인으로 확정하지 않는다.
        _record_evidence(update, _evidence_groups(bundle, groups), None)
        # 최고 점수는 **비센서에서만** 뽑는다. 센서는 자기 판별선을 쓰는 다른
        # 눈금이라 같은 줄에 놓으면 "더 센데 졌다" 로 읽힌다.
        top = max(c.score for c in bundle.claims.values() if c.kind != "sensor")
        # (2a)와 같은 이유로 지목 사실을 판정문에 남긴다 - 하한이 똑같이 "정직한
        # 제출" 인데 이름을 안 부르면, 정직하게 지목한 LLM 이 자기 제출이 무시된
        # 승인을 받는다.
        if not claim_id:
            picked_note = ""
        elif claim is None:
            # (2a)와 같은 이유 - 하한을 통과한 "번들에 없는 이름" 은 대체뿐이다.
            picked_note = _superseded_note(bundle, claim_id)
        elif claim.kind == "sensor":
            picked_note = f"네가 지목한 {claim_id} 는 2단 센서라 원인으로 확정하지 않았다. "
        else:
            picked_note = (f"네가 지목한 {claim_id} 는 아랫선({ya_config.RESIDUAL_MIN_SCORE})"
                           f"에도 못 미쳐 원인으로 확정하지 않았다. ")
        # **"가르는 항목이 없다" 를 가설 도구(hyp_*) 축에 한정한다(최종 리뷰 I-1).**
        # `_no_separation_state` 의 ②③④는 비센서 claim 만 본다 - 통과한 2단 센서가
        # 근거로 함께 실린 상태(`_evidence_groups` 가 싣는다)에서 축 전체로 넓히면,
        # 실제로는 갈린 센서를 안 갈렸다고 말하는 거짓 판정문이 된다(리뷰어 재현:
        # `ALL_WEAK + [SENSOR_FINDING]` 빈손 제출 -> 판정문이 "가르는 항목 없음" 인데
        # `[근거 1]` 은 판별선을 넘은 센서다). `_no_candidate_action` 독스트링·
        # weak_signal sys 프롬프트(`llm/client.py` 의 "판정이 weak_signal 이면" 절)가
        # 이미 같은 이유로 센서를
        # 따로 부른다.
        sensor_note = (
            "2단 센서는 판별선을 넘은 근거가 함께 실렸다 - 원인 확정 근거는 아니다. "
            if any(c.kind == "sensor" and c.passes for c in bundle.claims.values())
            else "")
        # **계산 불가(no_data) 축은 "다 대조했다" 는 관측 밖이다(최종 리뷰 I-3, 사용자
        # 결정 (a)).** `_no_separation_state` 의 ①은 `unrun`·`failed` 만 보고
        # `coverage["no_data"]`(`no_paired_stratum` 등)는 안 본다 - 계측 축처럼 호출은
        # 됐지만 대조한 것이 없는 축이 섞여도 이 판정은 그대로 열린다. `no_data` 가
        # 있으면 "분석이 안 돌은 것도 아니라" 를 빼고(그 축은 실제로 계산이 안 됐다)
        # `(3)`/운영 프롬프트 `no_comparable_data` 와 같은 조치(적재 범위·추출 조건
        # 확인)를 붙인다. `no_data` 가 비어 있으면 원래 대조 문장 그대로다 - `①`이
        # 이미 전축이 계산됐음을 보장한다.
        no_data = coverage.get("no_data") or []
        if no_data:
            reason = "근거가 약한 것도 아니라"
            scope_note = (f" 계산 불가 축({', '.join(no_data)})은 적재 범위와 "
                         f"추출 조건을 확인해야 한다.")
        else:
            reason = "분석이 안 돌은 것도 근거가 약한 것도 아니라"
            scope_note = ""
        return (f"갈리는 항목 없음 ({_coverage_phrase(coverage)}): {picked_note}"
                f"계산된 가설 도구(hyp_*) 축에서는 타깃과 대조군을 가르는 항목이 "
                f"없다. {sensor_note}최고 분리 점수 {top:.2f} 로 잔차 "
                f"아랫선({ya_config.RESIDUAL_MIN_SCORE})에도 미달한다. {reason} "
                f"lot 내부 대조로는 갈리지 않는다는 뜻이다.{scope_note} lot 밖 "
                f"대조군 또는 다른 관측축이 필요하다. 리포팅으로 진행한다."), drop

    # (2) 신호 없음 - 돌린 축에서 통과 후보가 하나도 없다.
    #     확신도를 보지 않는다: 물러섬 선언에 높은 확신도를 요구하면 모순이다.
    #     루프 한계(3)보다 **먼저** 판정해야 사유가 정확해진다.
    #
    #     **전축 실행은 더 이상 전제 조건이 아니다.** 예전에는 `not unrun` 을 함께
    #     요구해 등록된 hyp_* 를 전부 돌리기 전에는 물러설 수 없었는데, 그러면 신호를
    #     못 찾는 경로에서 루프 예산이 체크리스트 소화에 강제 배정돼 깊이 탐색이
    #     구조적으로 막혔다(빈손 metro 축이 매번 한 바퀴를 먹는 것이 그 증상이다).
    #     대신 "어디까지 봤는가" 를 coverage 로 실어 리포트까지 내보낸다 - 사유가
    #     틀린 보고(안 본 축까지 없다고 말하는 것)는 그 사실로 막는다.
    #
    #     하한 두 개는 남는다.
    #     - `"no_signal" in statuses`: 결과가 0건이면 '신호 없음' 은 관측이 아니라 추측이다.
    #     - `not claim_id`: **지목을 제출한 것은 물러선 것이 아니다.** 판정선이 앞으로
    #       당겨졌으므로, claim_id 를 안 보면 "확신도 0.9 로 없는 근거를 지목한" 제출이
    #       곧바로 승인으로 빠져나가 환각이 물러섬으로 둔갑한다.
    #     하한이 `statistical_passing()` 인 이유: 센서가 통과했다고 물러설 길을 닫으면
    #     승인(kind 하한)도 물러섬도 막혀 루프 한계까지 왕복한다. 물러섬의 뜻은 "지목할
    #     원인 후보가 없다" 이지 "아무 근거도 없다" 가 아니다.
    if (not bundle.statistical_passing() and not claim_id
            and "no_signal" in bundle.statuses.values()):
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_signal"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["coverage"] = coverage
        _record_evidence(update, groups, picked)
        # **실패 축도 '못 본 축' 이다.** `unrun` 만 보면, 실패 축을 그쪽에서 빼낸
        # 순간 유보가 조용히 꺼져 4축 중 3축이 장애로 못 돈 분석이 전축을 본 것처럼
        # 말한다. 이 문자열은 findings 로 리포트 LLM 에 넘어가고 프롬프트는 그것을
        # "그대로 인용하라" 고 지시한다.
        if unrun or failed:
            return (f"신호 없음 ({_coverage_phrase(coverage)}): 대조한 축에서는 원인을 "
                    f"좁힐 수 없다. 결론은 돌린 축에 한한 것이며 그 사실이 리포트에 "
                    f"함께 나간다. 리포팅으로 진행한다."), drop
        return (f"신호 없음 ({_coverage_phrase(coverage)}, 분리되는 후보 없음): "
                f"lot 내부 대조로는 원인을 좁힐 수 없다. 리포팅으로 진행한다."), drop

    # (3) 계산 불가 - 등록 가설을 다 돌렸는데 전부 그룹 수준 사실(대조 짝 없음·타깃
    #     부족)에서 멈췄다. 사람이 할 일이 다르다(적재/추출 범위 확인).
    #
    #     **(2)번과 달리 여기에는 전축 실행을 요구한다.** 둘은 성격이 다르다:
    #     (2)는 "대조한 축에서는 못 찾았다" 라 부분 커버리지로도 정직하지만, (3)은
    #     "볼 것이 없었다, 적재 범위를 확인하라" 는 **주장**이라 전축을 봐야 참이다.
    #     `no_paired_stratum` 은 축 무관한 사유(대조군 짝 없음)와 축 고유한 사유(그
    #     축 원자료 결측)를 같은 이름으로 부르고, metro 는 계측 짝이 없어 **상시**
    #     후자다. unrun 을 안 보면 metro 하나만 돌고도 (3)이 걸려, 데이터가 있는
    #     챔버·PPID·경로 축을 한 번도 안 건드린 채 엔지니어에게 틀린 조치가 나간다.
    #     `not claim_id` 는 (2)번과 같은 이유다 - 지목을 제출한 것은 물러선 것이 아니다.
    #     `not failed` 도 같은 이유다 - 터진 축은 본 것이 아니므로 "볼 것이 없었다"
    #     의 근거가 되지 못한다. 그 경우는 아래 (3b)가 다른 이름으로 받는다.
    ran_statuses = set(bundle.statuses.values())
    uncomputable = ran_statuses <= cm.NO_DATA_STATUSES
    if (ran_statuses and not unrun and not failed and not claim_id
            and uncomputable):
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_comparable_data"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["coverage"] = coverage
        _record_evidence(update, groups, picked)
        return (f"비교 가능한 데이터 없음 ({', '.join(sorted(ran_statuses))}): "
                f"대조에 쓸 짝이 없어 계산이 성립하지 않는다. 리포팅으로 진행한다."), drop

    # (3b) 도구 실패 - 남은 축이 없는데 본 것 중 계산된 것도 없고, 못 본 이유가
    #      **실행 실패**다. (3)과 사실은 겹칠 수 있지만 **엔지니어의 조치가 다르다**:
    #      (3)은 적재·추출 범위 확인이고 여기는 DB·서비스 상태 확인이다. 터진 축을
    #      (3)으로 흘려 보내면 멀쩡한 적재를 뒤지게 만든다.
    #
    #      이 자리가 없으면 전 축이 터진 분석은 어떤 종료도 못 열고 루프 한계까지
    #      왕복하다 `inconclusive`("확정 근거 없음")로 나가 진짜 사유가 사라진다.
    #      `ran_statuses` 가 비어 있어도(전 축 실패) 성립한다 - 공집합은 부분집합이다.
    #      `not unrun`·`not claim_id` 하한은 (3)과 같은 이유다.
    if failed and not unrun and not claim_id and uncomputable:
        update["finalize_accepted"] = True
        update["finalize_status"] = "tool_failure"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["coverage"] = coverage
        _record_evidence(update, groups, picked)
        return (f"도구 실패로 미수행 ({', '.join(failed)}): 조회가 실패해 대조를 "
                f"돌리지 못했다. 데이터가 없는 것이 아니다. 리포팅으로 진행한다."), drop

    # (4) 루프 한계 도달 강제 종료는 승인이 아니라 '미확정'
    if loop >= ya_config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["finalize_status"] = "inconclusive"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["coverage"] = coverage
        # **잔차도 싣는다 - 지금은 보험이다.** 예전에는 `(2a)` 가 환각을 안 받아 줘서
        # 이 경로가 실제로 열렸고, 여기서 안 실으면 "봤고 후보도 났는데 약하다" 가
        # 통째로 소각됐다(실측 재현). **2026-09-12 부터 루프 한계에서 환각 지목을
        # 버리므로 그 상태는 `(2a)` 가 먼저 받는다**(버리기 규칙 자체는 넷으로 더
        # 넓지만 - `_drop_unapprovable_pick` - `(2a)` 의 하한은 정직한 제출이라
        # **이 논증에 필요한 것은 환각 한 갈래뿐이다**. 나머지 셋은 원래 정직한
        # 제출이라 버리지 않아도 하한을 통과한다) - 잔차가 더해지는 조건
        # (`not statistical_passing()` + 잔차 있음)이 곧 `(2a)` 의 앞 두 항이고,
        # 한계에서는 하한(정직한 제출)이 늘 참이기 때문이다. 그래서 아래
        # `carried is not groups` 갈래는 **현재 도달 불가**다. `(2a)` 의 하한이 다시
        # 좁아지면 살아난다 - 그때 잔차 소각이 조용히 돌아오지 않도록 남겨 둔다.
        # `picked` 는 잔차를 실은 목록에서는 안 붙인다: 그 상태에서 지목할 수
        # 있는 것은 센서나 잔차뿐이고, 그것을 서술의 축으로 삼으면 리포트가 약한
        # 후보를 단정한다((2a)와 같은 이유). 목록이 바뀌면 `is` 비교도 어차피
        # 안 맞는다. **지금은 이 삼항이 갈리지 않는다** - `carried is not groups` 는
        # 도달 불가이고(위 참조), 그래서 `picked` 가 늘 그대로 넘어간다. 그래도
        # 위험하지 않은 이유는 **한계에서 승인이 못 받는 지목이 이미 버려졌기**
        # 때문이다 - 여기 남는 `picked` 는 실재하는 비센서 claim 뿐이라 서술의 축이
        # 돼도 "약한 후보를 단정" 이 아니다. 버리기 규칙이 좁아지거나 `(2a)` 의
        # 하한이 다시 좁아지면 이 삼항이 살아난다.
        carried = _evidence_groups(bundle, groups)
        _record_evidence(update, carried, picked if carried is groups else None)
        # **"확정 근거 없이" 는 실은 근거가 없을 때만 참이다.** `carried` 가
        # 비어 있지 않으면(통과 후보든 잔차든) `_record_evidence` 가 그것을
        # `final_claims` 에 싣고 리포트 LLM 은 이 문자열을 그대로 인용하라는
        # 지시를 받는다 - 근거를 실어 놓고 없다고 말하면 이 브랜치가 없애려던
        # 바로 그 거짓 문장이 된다.
        if carried is not groups:
            # **절단 전 `len(residuals)` 가 아니라 실제로 실린 수를 말한다.** (2a)와
            # 같은 이유 - 통과 근거가 상한을 채우면 잔차는 한 건도 안 실릴 수 있다.
            residual_note = _residual_evidence_note(update)
            return (f"미확정 (루프 한계 도달): 판별선을 넘은 후보를 확정하지 못했다. "
                    f"{residual_note}"
                    f"리포팅으로 진행한다."), drop
        if carried:
            # **절단 전 `len(carried)` 가 아니라 실제로 실린 수를 말한다(최종
            # 리뷰 I-4).** `_record_evidence` 의 상한(`REPORT_MAX_EVIDENCE`)이
            # `carried` 를 자르므로, 절단 전 개수를 찍으면 리포트에 없는 근거를
            # 가리키는 판정문이 나간다(리뷰어 재현: 통과 묶음 11개 -> final_claims
            # 8건인데 판정문은 "근거 11건").
            return (f"미확정 (루프 한계 도달): 판별선을 넘은 근거 "
                    f"{len(update['final_claims'])}건을 싣되 무엇이 원인인지는 "
                    f"확정하지 못했다. 리포팅으로 진행한다."), drop
        return "미확정 (루프 한계 도달): 확정 근거 없이 리포팅으로 진행한다.", drop

    # (5) 반려
    # 반려 경로는 한계 아래에서만 도달하므로 `drop` 은 늘 None 이다 - 그래도 한 자리로
    # 맞춘다(여기만 모양이 다르면 다음 사람이 이 갈래를 빠뜨린다).
    return _gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note,
                           groups, ranks), drop


def _record_evidence(update: dict, groups, picked) -> None:
    """판별선을 넘은 근거를 상태에 싣는다 - **지목 가능한 통과 후보가 없으면**
    판별선을 못 넘은 잔차도 함께 실린다(상한이 남는 한 - 아래 참조)
    ((2a)·(2b)·(4)·백스톱이 `_evidence_groups` 로 같은 규칙을 탄다).
    **모든 종료 경로에서 부른다.**

    예전에는 승인(confirmed) 경로에서만 실었다. 그런데 루프 한계로 끝나는
    inconclusive 는 "확정은 못 했지만 판별선을 넘은 후보나 잔차가 있다" 는
    상태라(위 하한이 잔차를 싣게 된 뒤로는 잔차만 있는 inconclusive 가 정상이다),
    거기서 목록을 버리면 **가장 도움이 필요한 보고서에서 근거가 전부 사라진다**
    (다축 fixture M2423 이 실제로 그렇게 끝났다: 통과 후보 3개, 리포트 근거 0줄).
    no_comparable_data 는 정의상 통과 후보가 없어 빈 목록이 되지만, no_signal 은
    아니다 - 1단이 침묵해도 판별선을 넘은 2단 센서는 실린다(그것이 이 브랜치가
    `passing()`/`statistical_passing()` 을 가른 이유다). 어느 경로가 무엇을 남기는지를
    여기서 다시 따지지 않도록 전부 같은 함수를 탄다.

    상한을 두는 이유: 후보는 도구마다 `COMMONALITY_TOP_K` 만큼 나올 수 있고
    계측 축은 무신호에서도 절반 가까이가 판별선을 넘는다. 상한이 없으면 리포트와
    운영 LLM 프롬프트에 근거 블록이 수십 개 쏟아져, 근거를 살리려던 변경이
    보고서를 오히려 못 읽게 만든다. 잘린 수는 마지막 항목에 남겨 숨기지 않는다.

    **통과 근거는 상한에 밀려나지 않는다.** 순위는 통계 등급을 비통계 등급보다
    위에 두므로(`dominates`), 잔차(통계적이나 미통과)가 통과한 센서(비통계)보다
    앞설 수 있다 - 상한을 앞에서부터 그대로 자르면 그 잔차들이 통과 근거를 밀어내,
    "잔차는 근거를 밀어내는 것이 아니라 더하는 것이다" (설계 §5) 는 약속이
    `REPORT_MAX_EVIDENCE` 를 넘는 규모에서 깨진다. `picked` 예약과 같은 모양으로,
    통과 근거를 전부 먼저 예약하고 남는 자리만 잔차로 채운다 - 표시 순서는 원래
    순위 순서를 그대로 따른다(어느 것이 잘렸는지만 바뀐다).
    """
    limit = ya_config.REPORT_MAX_EVIDENCE
    dicts = evidence.groups_to_dicts(groups, picked)
    if len(dicts) > limit:
        passing = [d for d in dicts if d["passes"]]
        keep = set(map(id, passing[:limit]))
        if len(passing) < limit:
            residual = [d for d in dicts if not d["passes"]]
            keep |= set(map(id, residual[:limit - len(passing)]))
        elif picked is not None and not any(d.get("picked_by_llm") for d in passing[:limit]):
            # **지목한 묶음은 잘라 내지 않는다.** 1등이 동점으로 여럿일 때 LLM 이
            # 정렬상 뒤쪽을 지목하면 그것이 상한 밖으로 밀려날 수 있는데, 그러면
            # 리포트에 서술의 축이 없어지고 승인 문구가 참조할 대상도 사라진다.
            keep = set(map(id, passing[:limit - 1]))
            keep |= {id(d) for d in passing if d.get("picked_by_llm")}
        kept = [d for d in dicts if id(d) in keep]
        dicts, hidden = kept, len(dicts) - len(kept)
        if hidden:
            dicts[-1]["more_below"] = hidden
    update["final_claims"] = dicts


def _residual_evidence_note(update: dict) -> str:
    """판정문이 잔차를 말할 때 쓰는 문구 - **`_record_evidence` 가 실제로 `final_claims`
    에 실은 잔차 수**로 센다 (반드시 `_record_evidence` 호출 뒤에 불러야 한다).

    절단 전 `bundle.residuals()` 의 길이를 쓰면 안 된다 - `_record_evidence` 의
    상한(`REPORT_MAX_EVIDENCE`)은 통과 근거를 전부 먼저 예약하고 남는 자리만
    잔차로 채우므로, 통과 근거(통과한 2단 센서 포함)가 상한을 채우면 잔차는 한
    건도 안 실릴 수 있다. 그 상태에서 절단 전 수를 찍으면 리포트에는 없는
    [잔차] 줄을 가리키는 거짓 판정문이 나간다(Task 6 리뷰 I-2).

    **절단 전 잔차가 실재하는 경로에서만 부른다**((2a) 의 `and residuals`,
    (4) 의 `carried is not groups` 하한) - 0건 갈래가 "있었으나" 를 단언하기
    때문이다. 이 전제는 `REPORT_MAX_EVIDENCE >= 1` 도 함께 든다 - env 로 0 이
    되면 통과 근거가 하나도 없어도 이 갈래에 들어와 "상한을 채워" 가 거짓이
    되지만, 그런 설정 오용에 대한 방어는 넣지 않는다.
    """
    n = sum(1 for c in update["final_claims"] if not c.get("passes", True))
    if n:
        return f"아랫선을 넘은 잔차 {n}건을 근거로 싣는다. "
    return "아랫선을 넘은 잔차가 있었으나 통과 근거가 상한을 채워 리포트에는 실리지 않는다. "


def _coverage(bundle) -> dict:
    """어느 축까지 봤는가 - **전제 조건이 아니라 보고하는 사실.**

    `no_data` 를 따로 세는 이유: 계측(metro) 축은 계측 짝이 없으면
    `no_paired_stratum` 으로 끝난다. 호출은 됐지만 대조한 것은 없다는 뜻이라,
    `ran` 으로만 세면 커버리지가 실제보다 넓어 보인다.

    `failed` 를 따로 세는 이유도 같은 종류다 - 실행 중 터진 축을 `unrun` 에 두면
    커버리지가 "아직 안 봤다(더 볼 수 있다)" 로 읽히는데 사실은 "볼 수 없었다
    (인프라를 확인하라)" 다. **등록 축으로 한정한다**: 번들의 `failed` 는 센서 등
    가설이 아닌 도구의 실패도 담는다.
    """
    registered = {n for n in TOOLS_BY_NAME if n.startswith("hyp_")}
    return {
        "ran": sorted(bundle.ran),
        "failed": sorted(registered & bundle.failed),
        "unrun": sorted(registered - bundle.ran - bundle.failed),
        "no_data": sorted(t for t, st in bundle.statuses.items()
                          if st in cm.NO_DATA_STATUSES),
    }


def _has_coverage_to_report(coverage: dict) -> bool:
    """커버리지 줄을 붙일 만한 상태인가.

    `ran` 만 보면 **전 축이 터진 장애 보고에서 커버리지가 통째로 사라진다** - 그때가
    바로 "4개 축이 도구 실패로 미수행" 을 읽어야 할 자리다. 반대로 분석 루프에
    들어가지도 않은 종료(이상 없음 등)에는 여전히 안 붙는다.
    """
    return bool(coverage.get("ran") or coverage.get("failed"))


def _coverage_phrase(coverage: dict) -> str:
    """커버리지를 사람이 읽는 한 줄로. 게이트 응답과 리포트가 같은 문장을 쓴다."""
    ran = coverage.get("ran") or []
    unrun = coverage.get("unrun") or []
    no_data = coverage.get("no_data") or []
    failed = coverage.get("failed") or []
    # `ran` 은 계산이 성립하지 않은 축도 포함한다. 그대로 세면 "2개 대조" 라고 해 놓고
    # 바로 뒤에서 그중 하나는 계산이 안 됐다고 말하는 엇갈린 줄이 된다 - 같은 줄 안에서
    # 바로 깎아 준다.
    hole = f"(그중 {len(no_data)}개는 계산 불가: {', '.join(no_data)})" if no_data else ""
    # 분모는 등록 축 전부다 - 실패 축을 빼면 "3개 중 3개 대조" 가 되어 장애가 사라진다.
    parts = [f"등록 축 {len(ran) + len(unrun) + len(failed)}개 중 {len(ran)}개 대조{hole}"]
    if failed:
        # '안 돌린 축' 과 다른 문장으로 적는다. 조치가 다르다(인프라 확인 vs 더 보기).
        parts.append(f"도구 실패로 미수행 {len(failed)}개: {', '.join(failed)}")
    if unrun:
        parts.append(f"안 돌린 축 {len(unrun)}개: {', '.join(unrun)}")
    return ". ".join(parts)


def _confidence(raw) -> tuple[float, str]:
    try:
        return float(raw), ""
    except (TypeError, ValueError):
        return 0.0, (f" (confidence 로 받은 '{raw}' 은 숫자가 아니다 - "
                     f"0~1 사이 숫자로 다시 제출하라)")


def _gate_rejection(claim_id, claim, bundle, coverage, conf, conf_note,
                    groups, ranks) -> str:
    """왜 승인하지 않았는지를 LLM 이 다음 행동으로 옮길 수 있게 돌려준다."""
    if claim_id and claim is None:
        # **없는 것과 대체된 것을 가른다.** LLM 은 재실행 뒤에도 앞 실행의 claim_id 를
        # 대화 문맥에서 그대로 보고 있다(tools_node 가 도구 결과를 ToolMessage 로
        # 싣는다). 그것을 제출한 것은 환각이 아닌데 "도구 결과에 없다" 로 답하면
        # 거짓이고, 그 문구는 지어낸 claim_id 를 겨눈 것이라 LLM 은 자기가 환각을 낸
        # 줄 알고 같은 문맥을 다시 읽는다. 폐기 사실을 리포트에만 알리고 여기에는
        # 안 알린 것이 M3 수정에 남아 있던 비대칭이다.
        # **사실만 적고 다음 행동은 아래 두 분기에 맡긴다.** 여기에 "최신 실행에서
        # 골라라" 를 넣었더니 통과 후보가 0건일 때 바로 뒤에 "지목할 수 있는 후보가 없다" 가
        # 붙어 한 문장 안에서 모순이 났다 - 실행 불가능한 지시는 H1 이 막으려던
        # "같은 문맥을 다시 읽는" 행동을 약한 형태로 되살린다.
        why = (f"claim_id '{claim_id}' 는 {bundle.dropped_claims[claim_id]} 를 다시 "
               f"돌려 대체된 앞 실행의 후보다."
               if claim_id in bundle.dropped_claims
               else f"claim_id '{claim_id}' 는 도구 결과에 없다.")
        # 안내 대상은 **통과 후보뿐**이다. 번들 전체를 안내하면 LLM 이 거기서
        # 미통과 후보를 골라 다시 제출하고 또 반려당하는 왕복이 생긴다 -
        # claim_id 미제출 분기(아래)와 같은 것을 안내해야 한다.
        # 센서도 뺀다 - 지목할 수 없는 것을 목록에 넣으면 LLM 이 골라 제출하고
        # 또 반려당하는 왕복이 생긴다.
        valid = sorted(c.claim_id for c in bundle.statistical_passing())
        if valid:
            return f"반려: {why} 통과 후보: {', '.join(valid)}."
        # 지목할 대상이 아예 없으면 목록 대신 다음 행동을 안내한다 - 여기서 멈추면
        # LLM 이 할 일을 못 찾아 루프 한계까지 왕복만 한다.
        return f"반려: {why} {_no_candidate_action(bundle, coverage)}"

    if claim is not None:
        # **지목 불가는 그 이름으로 반려한다.** 게이트 (1) 에 kind 하한만 걸고 여기에
        # 분기를 안 두면, 통과한 1등 센서를 지목한 제출이 아래 확신도 줄까지
        # 굴러떨어져 "확신도 0.95 < 0.8" 이라는 거짓말이 나간다(통과했고 1등이라
        # 미통과 분기도 순위 분기도 안 걸린다). 판정 (2)·(3)·(3b)는 전부
        # `not claim_id` 를 요구하므로 종료도 안 열려, `statistical_passing()` 으로
        # 막은 라이브락이 claim_id 를 낸 경로로 되살아난다.
        # **단 (2a)·(2b) 는 예외다.** 둘 다 하한이 "정직한 제출" 이라, 통과 후보가
        # 없고 잔차가 있으면 지목한 센서는 (2a) 가, 잔차가 없어도 전축을 다
        # 대조했고 비센서 claim 이 있는데 **그 점수가 전부 아랫선(0.25) 미만**이면
        # (2b) 가 먼저 받아 여기에 도달조차 하지 않는다. 이 분기가 실제로 도는
        # 것은 두 문이 다 닫힌 상태다 - 통과 후보가 있거나, (잔차가 없고 (전축을
        # 못 봤거나 비센서 claim 이 없거나 그중 점수가 아랫선 이상인 것이 하나라도
        # 있을 때))다. "claim_id 를 낸 제출을 받아 주는 종료 경로는 없다" 로
        # 읽으면 안 된다.
        # 순위 문구로 흘려보내도 안 된다 - 센서는 p 를 안 내므로 "p None" 을
        # 인용하게 되고, 효과크기가 분리 점수와 같은 "점수" 이름으로 나란히 놓여
        # **더 센데 규칙 때문에 졌다**로 읽힌다.
        if claim.kind == "sensor":
            why = (f"{claim.claim_id} 는 2단 센서 근거라 지목 대상이 아니다 "
                   f"(다중비교 보정을 하지 않는 도구다). 근거로는 게이트가 함께 싣는다.")
            valid = sorted(c.claim_id for c in bundle.statistical_passing())
            if valid:
                return f"반려: {why} 통과 후보: {', '.join(valid)}."
            return f"반려: {why} {_no_candidate_action(bundle, coverage)}"
        if not claim.passes:
            # 지목할 통과 후보가 **하나도 없으면** "통과한 후보를 지목하라" 는 실행할 수
            # 없는 지시다. 지어낸 claim_id 는 위에서 `_no_candidate_action` 을 타 물러설
            # 길을 안내받는데, 실재하는 미통과 claim 을 정직하게 지목한 쪽만 막다른 길에
            # 몰려 루프 한계까지 왕복하다 inconclusive 로 끝나던 자리다.
            if not bundle.statistical_passing():
                return (f"반려: {claim.claim_id} 는 판별선을 넘지 못했다 "
                        f"({claim.reject_reason}). {_no_candidate_action(bundle, coverage)}")
            return (f"반려: {claim.claim_id} 는 판별선을 넘지 못했다 ({claim.reject_reason}). "
                    f"통과한 후보를 지목하라.")
        picked = evidence.find_group(groups, claim_id)
        picked_rank = next((r for g, r in zip(groups, ranks) if g is picked), None)
        if picked is not None and groups and picked_rank != 1:
            # **실제로 이긴 근거**를 댄다. 3등을 지목했으면 그것을 이긴 것은 2등일
            # 수 있고, 그때 1등을 대면 LLM 은 왜 졌는지 못 읽는다.
            best = next((g.lead for g in groups if evidence.dominates(g, picked)),
                        groups[0].lead)
            # 바닥값을 같이 인용한다. 참조집합이 후보마다 좁혀지면서 **p 의 해상도가
            # 후보마다 달라졌기** 때문이다 - 바닥이 0.33 인 후보는 완전 분리여도 거기서
            # 멈추므로, 숫자 둘만 보여 주면 LLM 은 신호 차이로 읽고 반려를 고칠 수 없다.
            return (f"반려: {claim.claim_id}(p {claim.p_permutation}{_floor(claim)}, "
                    f"점수 {claim.score}) 는 {best.claim_id}"
                    f"(p {best.p_permutation}{_floor(best)}, 점수 {best.score}) 에게 "
                    f"두 후보가 **함께 표현할 수 있는 해상도**에서 졌다. p 는 자기 "
                    f"바닥과 함께 읽어야 한다 - 바닥에 걸린 후보는 더 작은 p 에게 "
                    f"지지 않는다. 1등 층의 근거를 서술의 축으로 지목하라, 나머지 "
                    f"근거는 게이트가 함께 싣는다.")
        return (f"반려: 확신도 {conf:.2f} < {ya_config.CONFIDENCE_THRESHOLD}.{conf_note} "
                f"근거를 좁힐 tool 을 더 호출하라.")

    # claim_id 미제출
    valid = sorted(c.claim_id for c in bundle.statistical_passing())
    if valid:
        return (f"반려: claim_id 를 제출하지 않았다. 결론은 도구가 발급한 claim_id 로 "
                f"지목해야 한다. 통과 후보: {', '.join(valid)}.")
    return f"반려: {_no_candidate_action(bundle, coverage)}"


def _floor(claim) -> str:
    """반려 문구에 덧붙일 바닥값 조각. 순열을 안 돌렸으면 빈 문자열이다."""
    return "" if claim.p_min_possible is None else f", 바닥 {claim.p_min_possible}"


def _no_candidate_action(bundle, coverage) -> str:
    """지목할 통과 후보가 하나도 없을 때 LLM 이 다음에 할 일.

    claim_id 를 지어낸 경로와 아예 안 낸 경로가 같은 막다른 상태에 도달하므로
    안내도 같아야 한다 - 한쪽만 다음 행동을 알려주면 다른 쪽은 왕복만 하다
    루프 한계로 끝난다.

    문구가 "통과한 후보가 없다" 가 아니라 **"지목할 수 있는 후보가 없다"** 인 이유:
    센서는 판별선을 넘어 근거로 실리면서도 지목 대상이 아니라, 통과 자체를 부정하면
    LLM 이 방금 받은 도구 결과와 어긋나는 말을 듣는다. 여기가 답하는 것은 "무엇이
    통과했나" 가 아니라 "무엇을 지목할 수 있나" 다.
    """
    # 물러서는 길은 **실제로 열려 있을 때만** 알려 준다. 열려 있지도 않은데 "비우고
    # 제출하라" 고 하면 같은 반려가 돌아와 라이브락이다.
    #
    # 판단 기준은 "(2)가 열리는가" 가 아니라 **"물러서면 어떤 종료든 열리는가"** 다.
    # (2)만 보면 (3)이 열리는 상태 - 정의상 NO_DATA 상태만 있어 no_signal 이 섞일 수
    # 없다 - 에는 한 번도 안 붙어, no_comparable_data(적재/추출 범위 확인)여야 할 것이
    # inconclusive(재시도)로 나간다.
    ran_statuses = set(bundle.statuses.values())
    # **실패 축은 부를 대상이 아니다.** `unrun` 에 섞여 있던 동안에는, 방금 터진
    # 도구를 다시 부르라고 이름을 대면서 동시에 실패 안내는 "다른 축이나 finalize"
    # 라고 말하는 모순이 났다 - 안내와 게이트 중 어느 쪽을 따라도 막힌다.
    unrun = coverage["unrun"]
    failed = coverage["failed"]
    uncomputable = ran_statuses <= cm.NO_DATA_STATUSES
    opens_no_signal = "no_signal" in ran_statuses                       # (2)
    opens_weak = bool(bundle.residuals())                                # (2a)
    opens_no_data = (bool(ran_statuses) and not unrun                    # (3)
                     and not failed and uncomputable)
    opens_tool_failure = bool(failed) and not unrun and uncomputable     # (3b)
    opens_no_separation = _no_separation_state(bundle, coverage)         # (2b)
    step_back = (" 지목할 것이 없어 물러설 때는 claim_id 를 비우고 finalize 하라."
                 if opens_no_signal or opens_weak or opens_no_data
                 or opens_tool_failure or opens_no_separation
                 else "")
    # 축이 0개 돌아간 상태를 **먼저** 가른다. 아래 "하나를 더 보거나" 는 사실과 안 맞고,
    # 2단 센서는 step_seq 를 요구하는데 그 값을 낼 근거가 아직 없다. (이 분기가 맨
    # 아래에 있을 때는 unrun 이 항상 비어 있지 않아 도달할 수 없는 죽은 코드였다.)
    if not bundle.ran:
        # 전 축이 터졌으면 부를 이름이 하나도 없다. 그대로 두면 빈 목록을 내밀며
        # "먼저 대조하라" 고 해, LLM 이 할 일을 못 찾고 루프 한계까지 왕복한다.
        if not unrun:
            return (f"등록 가설이 전부 도구 실패로 끝났다 ({', '.join(failed)}). "
                    f"부를 수 있는 축이 남아 있지 않다.{step_back}")
        return (f"그룹 대조 근거가 없다. 가설 도구로 두 그룹을 먼저 대조하라: "
                f"{', '.join(unrun)}.")
    if unrun:
        # 명령문이 아니라 선택지다. 판정에서 전축 강제를 걷어내 놓고 여기에
        # "먼저 호출하라" 를 남기면 LLM 은 여전히 체크리스트를 소화하러 간다 -
        # 규칙은 판정과 안내 두 곳에 쓰여 있었다.
        return (f"지목할 수 있는 통과 후보가 없다. 아직 안 돌린 가설 도구: {', '.join(unrun)}. "
                f"이 중 하나를 더 보거나, 2단 센서로 근거를 좁혀라 - 전부 돌릴 "
                f"의무는 없다.{step_back}")
    if failed:
        # "다 돌렸다" 가 거짓인 자리다 - 못 돈 축이 있고 그 이유가 실패다.
        return (f"지목할 수 있는 후보가 없다. 축 {len(failed)}개는 도구 실패로 미수행이다 "
                f"({', '.join(failed)}). 2단 센서로 근거를 더 좁히거나 대조군을 "
                f"다시 보라.{step_back}")
    return ("등록 가설을 다 돌렸으나 지목할 수 있는 후보가 없다. "
            "2단 센서로 근거를 더 좁히거나 대조군을 다시 보라." + step_back)


def _gateless_finalize(audit: list[dict]) -> tuple[str, str, list[dict]]:
    """게이트를 안 거치고 끝난 종료의 사유를 **증거 상태에서** 낸다.

    돌려주는 것은 `(finalize_status, 판정문, final_claims)`.

    **루프 한계는 종료 트리거이지 사유가 아니다** - 그 원칙은 게이트 밖에도 적용된다.
    `_after_tools` 의 한계 가드레일과 `_after_analyze` 의 텍스트 응답 이탈은 게이트를
    통째로 건너뛰는데, 거기서 무조건 `inconclusive` 를 찍으면 "봤는데 안 갈렸다" 와
    "예산 안에 못 끝냈다" 가 같은 이름으로 나간다 - 엔지니어가 할 조치가 다르다.
    이 경로는 LLM 협조와 무관하게 코드 라우팅이 만들므로 프롬프트로는 못 막는다.

    **사슬을 추출하지 않고 빈손 제출로 그대로 부른다.** 규칙을 두 자리에 적으면 한쪽만
    고치는 이 저장소의 반복 결함이 그대로 재발한다. 제출이 없는데 제출인 척하는 대가는
    치르되, 그 대가가 무엇을 막는지는 아래 두 줄에 적는다.

    **`loop` 를 한계로 강제하는 것이 `(5) 반려` 를 닫는다.** 텍스트 응답 이탈은 loop 1
    에도 일어나므로, 강제하지 않으면 종료 노드가 "반려" 문구를 내보낸다 - 되돌아갈
    루프가 없는 자리에서 반려는 뜻이 없다.

    **승인은 구조적으로 불가능하다.** `claim_id` 가 빈손이라 `bundle.claims.get("")` 이
    `None` 이고 `(1)` 은 지목한 claim 을 요구한다. 같은 이유로 `_drop_unapprovable_pick`
    도 `None` 을 돌려주므로 버린 지목 괄호가 붙을 일이 없다 - 버릴 제출이 없다.

    **꺼내 오는 것은 셋뿐이다.** `finalize_accepted` 는 상태에 거짓을 남기고(읽는 곳인
    `build.py` 라우팅과 `tools_node` 는 이미 다 지나왔다), `final_hypothesis` 는 제출이
    없었으니 비어 있는 것이 사실이며, `coverage` 는 `report_node` 가 같은 findings 로
    이미 다시 세고 있다(같은 값을 두 경로로 들이면 나중에 한쪽만 바뀐다).
    """
    scratch: dict = {}
    verdict = _finalize_gate({"claim_id": "", "hypothesis": "", "confidence": 0.0},
                             ya_config.MAX_LOOPS, scratch, audit)
    # **코드가 판정했다는 사실을 판정문에 남긴다.** 증거 상태가 같아도 분석 과정은
    # 다르다 - 이 사실이 필요한 것은 엔지니어가 아니라 프롬프트·스크립트를 고치는
    # 사람이다(LLM 이 종료를 제안하지 않았다는 신호). 판정 이름을 새로 만들지 않는
    # 이유이기도 하다: 어휘가 늘면 게이트·목·운영 프롬프트 세 곳이 같이 움직인다.
    verdict += " (LLM 이 종료를 제안하지 않아 코드가 증거 상태로 판정했다.)"
    return scratch["finalize_status"], verdict, scratch["final_claims"]


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    claims = state.get("final_claims") or []
    # **state 의 커버리지를 믿지 않고 감사 기록에서 다시 센다.** 낡은 값이 남을 수
    # 있는 경로가 하나라도 있으면 "커버리지는 사실이다" 라는 전제가 무너지고, 운영
    # 프롬프트가 "안 본 축 이름을 반드시 적어라" 로 지시하는 탓에 LLM 이 실제로 다
    # 돌린 축을 안 봤다고 지어낸다. findings 가 유일한 진실이다.
    # **한 리스트로 통일한다.** bundle 이 낸 superseded 는 이 리스트의 위치이므로,
    # 여기서 쓰는 것과 아래 표시·[대체됨] 줄이 쓰는 것이 다르면 인덱스가 어긋난다.
    audit = state.get("findings") or []
    bundle = evidence.build_bundle(audit)
    coverage = _coverage(bundle)
    # **게이트를 안 거치고 끝나는 종료를 여기서 메운다** (루프 한계 강제 종료, tool 없는
    # 텍스트 응답). 그 경로에는 판정도 근거도 안 실려서, 판정이 '미상' 이면 운영
    # 프롬프트의 "확정 결론을 쓰지 마라" 가드가 하나도 안 붙고, 감사 기록에 판별선을
    # 넘은 후보나 잔차가 있어도 리포트 근거가 0줄이 된다 - 게이트 안에만 있던 계약이라
    # 게이트를 안 타면 통째로 빠졌다. **사유도 여기서 낸다** - 무조건 inconclusive 로
    # 찍으면 "봤는데 안 갈렸다" 와 "예산 안에 못 끝냈다" 가 같은 이름으로 나간다
    # (`_gateless_finalize` 참조). 승인만은 여기서 안 나온다 - 금지가 아니라 지목이
    # 없어 `(1)` 이 성립하지 않는다.
    verdict = state.get("finalize_status")
    gateless_verdict = ""
    if not verdict:
        # **이 종료에는 finalize 판정이 실린 적이 없다** - 앞 루프에서 반려를
        # 받았을 수는 있지만 그 반려는 `finalize_status` 를 안 찍는다(`(4)` 는
        # 그 필드가 찍힌 상태로도 올 수 있는 경로라 다르다).
        verdict, gateless_verdict, claims = _gateless_finalize(audit)
    # **대체된 실행에 표시를 붙여 넘긴다.** 같은 축을 다시 돌리면 build_bundle 이 앞
    # 후보를 버리는데(그룹이 바뀌면 분모가 달라 거짓이므로 옳다), findings 는 그대로
    # 넘어가고 운영 프롬프트는 그 수치를 "그대로 인용하라" 고 지시한다 - 표시가 없으면
    # 게이트가 버린 통과 후보를 LLM 이 살아 있는 근거로 읽는다. 지우지 않고 표시만 하는
    # 이유는 추적성이 이 기록의 존재 이유이기 때문이다. **사본에만 붙인다** - 상태의
    # findings 를 건드리면 감사 기록 자체가 오염된다.
    sent_findings = audit
    if bundle.superseded:
        sent_findings = [{**f, "superseded": True} if i in bundle.superseded else f
                         for i, f in enumerate(audit)]
    if gateless_verdict:
        # **판정문이 LLM 에 닿는 유일한 길이다.** 경로 B 에는 finalize 호출이 없어
        # findings 에 게이트 줄이 없고, 운영 프롬프트는 판정문을 인용하라고 지시한다.
        # `tools_node` 가 만드는 레코드와 같은 계약으로 얹어 목이 `[분석 과정]` 의
        # `- 게이트:` 줄로 렌더링하게 한다. **끝에 붙인다** - `bundle.superseded` 는
        # `audit` 안의 위치라, 앞에 끼우면 그 인덱스가 어긋난다.
        sent_findings = [*sent_findings,
                         {"loop": state.get("loop_count", 0), "tool": "finalize",
                          "args": {}, "result": gateless_verdict, "thought": ""}]
    try:
        report = _llm_lazy().generate_report(
            target_wafers=state.get("target_wafers", []),
            target_source=state.get("target_source", "manual"),
            target_group=state["target_group"],
            status_summary=state["status_summary"],
            findings=sent_findings,
            hypothesis=state.get("final_hypothesis"),
            confidence=state.get("final_confidence"),
            finalize_status=verdict,
            claims=claims,
            # 커버리지 줄을 소음이라 지운 보고서에는 프롬프트에도 넘기지 않는다 -
            # 두 렌더링이 엇갈리면 "이상 없음" 보고서에서 LLM 이 안 본 축을 나열한다.
            coverage=coverage if _has_coverage_to_report(coverage) else None,
        )
    except Exception as e:
        # 여기가 마지막 노드다 - 예외를 내보내면 분석을 다 해 놓고 결과를 전부 버린다.
        # 산문만 포기하고 결론은 코드로 적는다. 현황·감사 기록은 main.py 가 상태에서
        # 따로 찍으므로, 여기서 필요한 것은 '왜 산문이 없는지'와 결론뿐이다.
        # **게이트가 버린 지목은 결론으로 찍지 않는다.** `final_hypothesis` 는 LLM 이
        # 쓴 문장 그대로라 버린 후보를 원인으로 단정한 채 남아 있다 - 산문 LLM 은
        # 판정문으로 그 사실을 받지만 이 폴백은 문장을 그대로 찍으므로, 바로 위
        # [판정] 줄이 "무시했다" 고 말하는데 [결론] 이 그 후보를 원인이라고 적는
        # 리포트가 나간다. 확신도도 같이 뺀다 - LLM 자기 신고라 근거가 아니다.
        dropped_pick = state.get("dropped_pick")
        conclusion = (f"원인 미확정 (게이트가 마지막 지목 '{dropped_pick}' 을 버렸다 "
                      f"- 사유는 위 [판정] 줄)"
                      if dropped_pick else
                      f"{state.get('final_hypothesis') or '원인 미확정'}"
                      f" (확신도 {state.get('final_confidence')})")
        report = (f"[리포트 생성 실패] LLM 호출이 실패해 산문 리포트를 만들지 못했다 "
                  f"({type(e).__name__}: {e}). 아래는 코드가 적은 결론이다.\n"
                  f"[판정] {verdict}\n"
                  f"[결론] {conclusion}")
    # [근거] 줄은 클라이언트(LLM)가 아니라 여기서 코드로 붙인다 - 운영에서도
    # 근거가 리포트에서 사라지지 않게 하려는 것이 이 기능의 목적이다.
    # 여러 줄인 이유: 축이 여럿이면 근거도 여럿이고, 그중 하나만 남기던 것이
    # 고치려던 문제다. 순서는 코드가 매긴 순위이며 LLM 이 고른 것은 표시된다.
    for group in claims:
        mark = " ←서술 기준" if group.get("picked_by_llm") else ""
        # **잔차는 다른 이름으로 찍는다.** 판별선을 못 넘은 후보를 `[근거]` 로 찍으면
        # 통과한 것과 글자 하나 다르지 않아, 엔지니어가 그 줄을 보고 설비를 세운다.
        # 기본값이 True 인 이유: 이 자리를 지나는 dict 는 전부 게이트가 만든 것이라
        # `passes` 가 늘 있지만, 없으면 '근거' 로 읽는 쪽이 옛 동작과 같다.
        label = "근거" if group.get("passes", True) else "잔차"
        # 번호는 위치가 아니라 **등수**다. 동점이 1·2 로 찍히면 앞선 것이 더 강해
        # 보이는데, 그 오독을 막으려고 등수를 따로 계산해 둔 것이다.
        report += (f"\n[{label} {group.get('rank', '?')}]{mark} "
                   f"{evidence.format_group_line(group)}")
        # 왜 약한지를 같은 줄에 남긴다 - 수치만 보면 0.4 가 강한지 약한지 못 읽는다.
        # 문구를 새로 짓지 않는다: `_passes` 가 만든 문장이 이미 정확하다.
        if not group.get("passes", True) and group.get("reject_reason"):
            report += f" (판별선 미달: {group['reject_reason']})"
        if group.get("more_below"):
            # 중립어를 쓴다 - `근거` 도 `잔차` 도 아니고, 마지막 표시 항목의
            # label 을 재사용하면 숨겨진 것들이 그것과 같은 종류라는 근거 없는
            # 보증을 하게 된다. `[근거 ...]` 로 찍으면 근거가 0건인 리포트가
            # "근거 N건 생략" 이라 말하는 거짓이 생긴다.
            #
            # "순위 밖" 이 아니라 "상한 밖" 이라고 쓴다 - `_record_evidence` 가
            # 통과 근거를 상한에서 예약한 뒤로는 잘려 나간 항목이 **더 이상 늘
            # 가장 약한 것이 아니다.** 통과 근거보다 등수가 높은 잔차가 상한 밖으로
            # 밀려날 수 있다(잔차 6건이 등수 1, 통과 센서 5건이 등수 2인 상태에서
            # 상한이 8이면 잘리는 3건은 등수 1이다) - "순위 밖" 은 그 경우 거짓이다.
            # "상한 밖" 은 잘린 이유(표시 개수 제한)만 말하고 순위상 위치는 말하지
            # 않으므로 꼬리가 잘릴 때도, 상위 등수가 밀려날 때도 참이다.
            report += (f"\n[생략] 상한 밖 {group['more_below']}건은 생략했다 "
                       f"(전체는 분석 과정 기록에 있다)")
    # [커버리지] 줄도 여기서 코드로 붙인다 - [근거] 와 같은 이유다. 클라이언트에
    # 맡기면 운영 경로에서만 조용히 사라진다.
    # 하나도 안 돌렸으면 붙이지 않는다 - "4개 중 0개 대조" 는 사실이지만 셀 것이
    # 없는 보고서(이상 없음 등)에서는 소음일 뿐이다.
    if _has_coverage_to_report(coverage):
        report += f"\n[커버리지] {_coverage_phrase(coverage)}"
    # [대체됨] 줄도 코드가 붙인다. LLM 프롬프트에만 표시하면 산문이 죽는 경로(운영
    # 클라이언트 실패)에서 대체 사실이 통째로 사라지고, 리포트만 받아 보는 사람은
    # "판정은 신호 없음인데 같은 축을 왜 두 번 돌렸나" 를 읽을 방법이 없다.
    # (main.py 의 감사 기록 출력은 tool·args·thought 와 finalize 결과만 찍고 hyp_*
    #  의 후보·p·passes 는 안 찍는다 - 콘솔 독자가 통과 후보를 본다는 뜻이 아니다.)
    # 후보를 실제로 버린 실행만 담기므로(Bundle.superseded) 빈손 재실행에는 안 붙는다.
    for i in sorted(bundle.superseded):
        dropped = audit[i]
        report += (f"\n[대체됨] loop {dropped.get('loop', '?')} 의 "
                   f"{dropped.get('tool', '?')} 결과는 같은 축을 다시 돌린 뒤 실행으로 "
                   f"대체되었다 - 그 실행의 후보는 근거가 아니다")
    return {"report": report, "finalize_status": verdict}
