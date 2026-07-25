"""LangGraph 노드: 현황파악(고정) / 분석(LLM) / 도구 실행+게이트 / 리포팅(고정).

- 골격(status, report)은 고정 — 순서는 개발자가 못박는다.
- analyze ⇄ tools 순환 구간만 LLM 이 자율 판단한다.
- tools 노드는 세 가지를 한다:
    (1) 분석 tool 실행 (수치는 여기서만 나온다)
    (2) 감사 기록: 매 실행을 findings 에 {loop, tool, args, result, thought} 로 남긴다
    (3) finalize 게이트: LLM 의 종료 제안을 confidence 로 승인/반려 (LLM 은 제안, 코드가 결정)
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import config
from llm.client import get_llm
from tools import grouping
from tools import yield_tools as yt
from tools.agent_tools import TOOLS_BY_NAME

_llm = get_llm()

ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 불량 그룹(유사 불량 wafer 들)과 대조 그룹(같은 lot 의 정상 wafer 들)을 비교해, 불량 그룹만의 공통 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. 그룹 간 차이(장비·파라미터)가 핵심 근거다 — 가설 도구(hyp_*)로 두 그룹을 대조하라.
- tool 을 호출할 때는 reason 인자에 현재 가설과 그 tool 을 고른 이유를 한 문장으로 반드시 담아라 — 이 서술이 그대로 분석 감사 기록에 남는다.
- 원인을 좁혔고 근거가 충분하면 finalize(hypothesis, confidence) 로 종료를 제안하라. 확신도가 낮으면 반려된다.
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
    if norm["isolated"]:
        summary = (f"분석 대상 입력 ({source}): {', '.join(targets)}\n"
                   f"형제 묶기 (EDS, 컷오프 {config.SIBLING_MIN_SIMILARITY}): 형제 없음 — "
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

    label = norm["label_counts"][0]["defect_type"] if norm["label_counts"] else "미상"
    groups_json = json.dumps(
        {"target": norm["target_group"], "control": ctrl["control_group"]},
        ensure_ascii=False)
    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n"
            f"불량 그룹 ({label}): {', '.join(norm['target_group'])}\n"
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
        lines.append(f"형제 묶기 (EDS, 컷오프 {config.SIBLING_MIN_SIMILARITY}): "
                     f"{len(norm['target_group'])}장 — 입력 + {sib}")
        if norm.get("unmatched_siblings"):
            lines.append(f"EDS 형제 중 yield DB 미확인 {len(norm['unmatched_siblings'])}장 "
                         f"제외: {', '.join(norm['unmatched_siblings'])} "
                         f"(인덱스/DB 동기화 확인 필요)")
    else:
        lines.append(f"그룹 입력: {len(norm['target_group'])}장 그대로 사용 (묶기 생략)")
    labels = ", ".join(f"{c['defect_type']} {c['count']}장" for c in norm["label_counts"])
    lines.append(f"defect 라벨 (참고): {labels}")
    src = ", ".join(f"{rl} {len(ws)}장" for rl, ws in sorted(ctrl["sources"].items()))
    line = f"대조군 (같은 root_lot 비타깃): {len(ctrl['control_group'])}장 — {src}"
    ys = ctrl["yield_summary"]
    if ys:
        # 라벨이 없어 저수율 wafer 를 거를 수 없다 — 거르는 대신 분포를 보인다
        line += (f" · 수율 중앙값 {ys['median']}, 임계 {ys['threshold']} 미만 "
                 f"{ys['n_below_threshold']}장")
    lines.append(line)
    if ctrl["insufficient"]:
        lines.append(f"대조군 부족: {len(ctrl['control_group'])}장 < "
                     f"{config.CONTROL_MIN_SIZE} (root_lot 내 대조 한계 — 추후 분석 필요)")
    return "\n".join(lines)


# ------------------------------------------------ 자유 루프: 분석 (LLM)
def analyze_node(state: dict) -> dict:
    ai = _llm.analyze_step(state["messages"])
    return {"messages": [ai], "loop_count": state.get("loop_count", 0) + 1}


# ------------------------------------------------ 자유 루프: 도구 실행 + 게이트
def tools_node(state: dict) -> dict:
    ai = state["messages"][-1]
    loop = state["loop_count"]
    out_msgs, findings, update = [], [], {}

    for call in ai.tool_calls:
        if call["name"] == "finalize":
            # 증거는 누적 findings + 이번 메시지에서 방금 실행된 tool 결과(findings)까지 포함
            verdict = _finalize_gate(call["args"], loop, update,
                                     state.get("findings", []) + findings)
            out_msgs.append(ToolMessage(verdict, tool_call_id=call["id"], name="finalize"))
            findings.append({
                "loop": loop, "tool": "finalize", "args": call["args"],
                "result": verdict, "thought": ai.content or "",
            })
        else:
            tool = TOOLS_BY_NAME.get(call["name"])
            if tool is None:
                result = (f"오류: '{call['name']}' 는 존재하지 않는 tool 이다. "
                          f"사용 가능한 tool: {', '.join(TOOLS_BY_NAME)}. "
                          f"이 중에서 다시 선택해 호출하라.")
            else:
                try:
                    result = tool.invoke(call["args"])
                except Exception as e:  # 인자 스키마 위반·조회 실패 등
                    result = (f"오류: {call['name']} 실행 실패 "
                              f"({type(e).__name__}: {e}). 인자를 확인하고 다시 호출하라.")
            out_msgs.append(ToolMessage(
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["id"], name=call["name"],
            ))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": result, "thought": ai.content or call["args"].get("reason", ""),
            })

    return {"messages": out_msgs, "findings": findings, **update}


def _finalize_gate(args: dict, loop: int, update: dict, findings: list[dict]) -> str:
    """LLM 의 종료 제안을 코드가 최종 판정한다 (부품 4b).

    승인 실권은 confidence 자기 신고가 아니라 findings 의 결정론적 증거에 있다:
    (a) 그룹 대조 근거가 존재하고 (b) 가설의 장비가 그 근거의 suspect 와 일치해야 승인.
    (c) 루프 한계 도달 강제 종료는 승인이 아니라 '미확정' 으로 구분 기록한다.
    """
    raw = args.get("confidence", 0.0)
    try:
        conf = float(raw)
    except (TypeError, ValueError):
        conf = 0.0
        conf_note = (f" (confidence 로 받은 '{raw}' 은 숫자가 아니다 — "
                     f"0~1 사이 숫자로 다시 제출하라)")
    else:
        conf_note = ""

    hypothesis = args.get("hypothesis", "")
    suspects = _collect_evidence(findings)

    if conf >= config.CONFIDENCE_THRESHOLD and any(eq in hypothesis for eq in suspects):
        update["finalize_accepted"] = True
        update["finalize_status"] = "confirmed"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        return "승인 (확신도·증거 충족): 리포팅으로 진행한다."

    if loop >= config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["finalize_status"] = "inconclusive"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        return "미확정 (루프 한계 도달): 확정 근거 없이 리포팅으로 진행한다."

    if conf < config.CONFIDENCE_THRESHOLD:
        return (f"반려: 확신도 {conf:.2f} < {config.CONFIDENCE_THRESHOLD}."
                f"{conf_note} 근거를 좁힐 tool 을 더 호출하라.")
    if not suspects:
        return "반려: 그룹 대조 근거가 없다. 가설 도구(hyp_*)로 두 그룹을 먼저 대조하라."
    return (f"반려: 가설의 장비가 tool 결과의 suspect 목록({', '.join(sorted(suspects))})에 없다. "
            f"근거가 지목한 장비로 가설을 세우라.")


def _collect_evidence(findings: list[dict]) -> set[str]:
    """findings 에서 판별 통과 후보의 토큰을 모은다 (LLM 이 만들 수 없는 근거).

    레지스트리 도구 결과(HypothesisResult, candidates 보유)만 훑는다.
    토큰 = value 의 마지막 요소 (범주형 (공정,값)->값, 수치형 (공정,파라미터)->파라미터).
    """
    tokens = set()
    for f in findings:
        result = f.get("result")
        if not isinstance(result, dict) or "candidates" not in result:
            continue
        for c in result["candidates"]:
            if c.get("passes"):
                v = c["value"]
                tokens.add(v[-1] if isinstance(v, (list, tuple)) else str(v))
    return tokens


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    report = _llm.generate_report(
        target_wafers=state.get("target_wafers", []),
        target_source=state.get("target_source", "manual"),
        target_group=state["target_group"],
        status_summary=state["status_summary"],
        findings=state["findings"],
        hypothesis=state.get("final_hypothesis"),
        confidence=state.get("final_confidence"),
        finalize_status=state.get("finalize_status"),
    )
    return {"report": report}
