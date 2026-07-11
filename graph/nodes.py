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

ANALYZE_SYSTEM_PROMPT = """너는 반도체 수율 분석 전문가다. 대상 wafer 의 불량 원인을 특정 공정 단계(가능하면 장비)까지 좁혀라.

규칙:
- 매 단계, 지금까지의 tool 결과로 원인을 확신할 수 있는지 스스로 평가하라.
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. tool 호출 시 현재 가설과 이 tool 을 부르는 이유를 한두 문장으로 함께 서술하라 (분석 기록으로 남는다).
- 원인을 좁혔고 근거가 충분하면 finalize(hypothesis, confidence) 로 종료를 제안하라. 확신도가 낮으면 반려된다.
- 수치는 tool 결과를 그대로 인용하고 절대 임의로 만들지 마라."""


# ------------------------------------------------ 고정 골격: 현황 파악
def status_node(state: dict) -> dict:
    lots = yt.find_low_yield_lots()
    summary = _summarize_lots(lots)
    finding = {
        "loop": 0, "tool": "find_low_yield_lots", "args": {},
        "result": lots, "thought": "현황 파악 (고정 골격)",
    }
    if not lots:  # 이상 lot 없음 → 분석 루프 없이 리포팅으로 (build 의 _after_status)
        return {"target_wafer": "", "status_summary": summary, "findings": [finding]}

    target = lots[0]["worst_wafer"]["wafer_id"]
    seed = [
        SystemMessage(content=ANALYZE_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"현황:\n{summary}\n\n대상 wafer: {target}\n질문: {state['question']}"
        )),
    ]
    return {
        "messages": seed,
        "target_wafer": target,
        "status_summary": summary,
        "findings": [finding],
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
            verdict = _finalize_gate(call["args"], loop, update)
            out_msgs.append(ToolMessage(verdict, tool_call_id=call["id"], name="finalize"))
            findings.append({
                "loop": loop, "tool": "finalize", "args": call["args"],
                "result": verdict, "thought": ai.content or "",
            })
        else:
            result = TOOLS_BY_NAME[call["name"]].invoke(call["args"])
            out_msgs.append(ToolMessage(
                json.dumps(result, ensure_ascii=False),
                tool_call_id=call["id"], name=call["name"],
            ))
            findings.append({
                "loop": loop, "tool": call["name"], "args": call["args"],
                "result": result, "thought": ai.content or "",
            })

    return {"messages": out_msgs, "findings": findings, **update}


def _finalize_gate(args: dict, loop: int, update: dict) -> str:
    """LLM 의 종료 제안을 코드가 최종 판정한다 (부품 4b)."""
    conf = float(args.get("confidence", 0.0))
    if conf >= config.CONFIDENCE_THRESHOLD or loop >= config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["final_hypothesis"] = args.get("hypothesis", "")
        update["final_confidence"] = conf
        reason = "확신도 충족" if conf >= config.CONFIDENCE_THRESHOLD else "최대 횟수 도달"
        return f"승인 ({reason}): 리포팅으로 진행한다."
    return (f"반려: 확신도 {conf:.2f} < {config.CONFIDENCE_THRESHOLD}. "
            f"근거를 좁힐 tool 을 더 호출하라.")


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    report = _llm.generate_report(
        question=state["question"],
        target_wafer=state["target_wafer"],
        status_summary=state["status_summary"],
        findings=state["findings"],
        hypothesis=state.get("final_hypothesis"),
        confidence=state.get("final_confidence"),
    )
    return {"report": report}
