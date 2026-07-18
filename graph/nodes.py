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
from tools import yield_tools as yt
from tools.agent_tools import TOOLS_BY_NAME

_llm = get_llm()

ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 불량 그룹(유사 불량 wafer 들)과 대조 그룹(같은 lot 의 정상 wafer 들)을 비교해, 불량 그룹만의 공통 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. 그룹 간 차이(장비·파라미터)가 핵심 근거다 — compare_process_logs 로 두 그룹을 대조하라.
- tool 을 호출할 때는 reason 인자에 현재 가설과 그 tool 을 고른 이유를 한 문장으로 반드시 담아라 — 이 서술이 그대로 분석 감사 기록에 남는다.
- 원인을 좁혔고 근거가 충분하면 finalize(hypothesis, confidence) 로 종료를 제안하라. 확신도가 낮으면 반려된다.
- 수치는 tool 결과를 그대로 인용하고 절대 임의로 만들지 마라."""


# ------------------------------------------------ 고정 골격: 현황 파악
def status_node(state: dict) -> dict:
    lots = yt.find_low_yield_lots()
    summary = _summarize_lots(lots)
    findings = [{
        "loop": 0, "tool": "find_low_yield_lots", "args": {},
        "result": lots, "thought": "현황 파악 (고정 골격)",
    }]
    if not lots:  # 출구 A: 이상 lot 없음 → 분석 루프 없이 리포팅으로 (build 의 _after_status)
        return {"target_group": [], "control_group": [],
                "status_summary": summary, "findings": findings,
                "finalize_status": "no_anomaly"}

    grp = yt.find_defect_group(lots[0]["lot_id"])
    findings.append({
        "loop": 0, "tool": "find_defect_group", "args": {"lot_id": lots[0]["lot_id"]},
        "result": grp, "thought": "그룹 대조 대상 묶기 (고정 골격)",
    })
    if not grp["target_group"]:  # 출구 B: 수율 이상은 있으나 defect 패턴으로 못 묶음
        # '이상 없음'(출구 A)과 다른 신호다 — 리포트가 구분하도록 별도 상태로 기록
        return {"target_group": [], "control_group": grp["control_group"],
                "status_summary": summary, "findings": findings,
                "finalize_status": "ungrouped"}

    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n"
            f"불량 그룹 ({grp['defect_type']}): {', '.join(grp['target_group'])}\n"
            f"대조 그룹 (정상): {', '.join(grp['control_group'])}\n"
            f"질문: {state['question']}"
        )),
    ]
    return {
        "messages": seed,
        "target_group": grp["target_group"],
        "control_group": grp["control_group"],
        "status_summary": summary,
        "findings": findings,
    }


def _summarize_lots(lots: list[dict]) -> str:
    if not lots:
        return "수율 임계 미만인 lot 없음."
    lines = []
    for lot in lots:
        w = lot["worst_wafer"]
        lines.append(
            f"- {lot['lot_id']}: 평균 수율 {lot['avg_yield']} ({lot['wafer_count']}장), "
            f"최저 wafer {w['wafer_id']} (수율 {w['yield']}, 불량 {w['defect_type']})"
        )
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
    suspects = _collect_suspects(findings)

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
        return "반려: 그룹 대조 근거가 없다. compare_process_logs 로 두 그룹을 먼저 대조하라."
    return (f"반려: 가설의 장비가 tool 결과의 suspect 목록({', '.join(sorted(suspects))})에 없다. "
            f"근거가 지목한 장비로 가설을 세우라.")


def _collect_suspects(findings: list[dict]) -> set[str]:
    """findings 에서 결정론적 tool 이 지목한 장비 ID 를 모은다 (LLM 이 만들 수 없는 근거)."""
    suspects = set()
    for f in findings:
        if f["tool"] != "compare_process_logs":
            continue
        result = f["result"]
        for row in result.get("suspect_equipment", []) + result.get("group_spec_violations", []):
            suspects.add(row["equipment_id"])
    return suspects


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    report = _llm.generate_report(
        question=state["question"],
        target_group=state["target_group"],
        status_summary=state["status_summary"],
        findings=state["findings"],
        hypothesis=state.get("final_hypothesis"),
        confidence=state.get("final_confidence"),
        finalize_status=state.get("finalize_status"),
    )
    return {"report": report}
