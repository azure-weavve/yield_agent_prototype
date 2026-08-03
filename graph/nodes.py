"""LangGraph 노드: 현황파악(고정) / 분석(LLM) / 도구 실행+게이트 / 리포팅(고정).

- 골격(status, report)은 고정 — 순서는 개발자가 못박는다.
- analyze ⇄ tools 순환 구간만 LLM 이 자율 판단한다.
- tools 노드는 세 가지를 한다:
    (1) 분석 tool 실행 (수치는 여기서만 나온다)
    (2) 감사 기록: 매 실행을 findings 에 {loop, tool, args, result, thought} 로 남긴다
    (3) finalize 게이트: LLM 의 종료 제안을 confidence 로 승인/반려 (LLM 은 제안, 코드가 결정)
"""

import json
from dataclasses import asdict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import ya_config
from graph import evidence
from llm.client import get_llm
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
- 확신이 부족하면 근거를 좁힐 tool 을 하나 더 호출하라. 그룹 간 차이(장비·파라미터)가 핵심 근거다 — 가설 도구(hyp_*)로 두 그룹을 대조하라.
- tool 을 호출할 때는 reason 인자에 현재 가설과 그 tool 을 고른 이유를 한 문장으로 반드시 담아라 — 이 서술이 그대로 분석 감사 기록에 남는다.
- 원인을 좁혔고 근거가 충분하면 finalize(claim_id, hypothesis, confidence) 로 종료를 제안하라. claim_id 는 가설 도구 결과의 후보에 실려 온 값을 **그대로** 옮겨야 한다 - 지어내거나 문장으로 대신하면 반려된다. 지목할 근거가 없어 물러설 때는 claim_id 를 비우고 낮은 확신도로 제출하라.
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
                   f"EDS 유사맵 조회 실패: {norm['eds_error']} — "
                   f"wafer 는 yield DB 에 있으나 형제 묶기를 하지 못했다.")
        return {"target_group": norm["target_group"], "control_group": [],
                "status_summary": summary, "findings": findings,
                "finalize_status": "eds_lookup_failed"}
    if norm["isolated"]:
        summary = (f"분석 대상 입력 ({source}): {', '.join(targets)}\n"
                   f"형제 묶기 (EDS, 컷오프 {ya_config.SIBLING_MIN_SIMILARITY}): 형제 없음 — "
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
                     f"{len(norm['target_group'])}장 — 입력 + {sib}")
        if norm.get("unmatched_siblings"):
            lines.append(f"EDS 형제 중 yield DB 미확인 {len(norm['unmatched_siblings'])}장 "
                         f"제외: {', '.join(norm['unmatched_siblings'])} "
                         f"(인덱스/DB 동기화 확인 필요)")
    else:
        lines.append(f"그룹 입력: {len(norm['target_group'])}장 그대로 사용 (묶기 생략)")
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
                     f"{ya_config.CONTROL_MIN_SIZE} (root_lot 내 대조 한계 — 추후 분석 필요)")
    return "\n".join(lines)


# ------------------------------------------------ 자유 루프: 분석 (LLM)
def analyze_node(state: dict) -> dict:
    ai = _llm_lazy().analyze_step(state["messages"])
    return {"messages": [ai], "loop_count": state.get("loop_count", 0) + 1}


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

    승인 실권은 confidence 자기 신고도, LLM 이 쓴 문장도 아니라 **EvidenceBundle
    조회 결과**에 있다. LLM 은 도구가 발급한 claim_id 를 지목하고, 게이트는 그
    claim 이 판별선을 넘었는지와 같은 도구 안에서 최고 점수인지를 확인한다.

    판정은 위에서부터 처음 걸리는 줄로 결정된다:
      (1) 지목한 claim 이 통과 + 최고 점수 + 확신도 충족 -> confirmed
      (2) 등록 가설을 다 돌렸는데 통과 후보 0 + no_signal 있음 -> no_signal
      (3) 루프 한계 -> inconclusive (승인이 아니라 '미확정')
      (4) 그 외 -> 반려. 무엇이 모자란지 그대로 돌려준다.
    """
    bundle = evidence.build_bundle(findings)
    conf, conf_note = _confidence(args.get("confidence", 0.0))
    hypothesis = args.get("hypothesis", "")
    claim_id = (args.get("claim_id") or "").strip()
    claim = bundle.claims.get(claim_id)
    registered = {n for n in TOOLS_BY_NAME if n.startswith("hyp_")}
    unrun = sorted(registered - bundle.ran)

    # (1) 승인
    if (claim is not None and claim.passes
            and claim.score >= bundle.top_score(claim.tool)
            and conf >= ya_config.CONFIDENCE_THRESHOLD):
        update["finalize_accepted"] = True
        update["finalize_status"] = "confirmed"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        update["final_claim"] = asdict(claim)
        return (f"승인 (근거 확인): {evidence.format_evidence_line(update['final_claim'])}. "
                f"리포팅으로 진행한다.")

    # (2) 신호 없음 - 등록 가설을 다 돌렸는데 통과 후보가 하나도 없다.
    #     확신도를 보지 않는다: 물러섬 선언에 높은 확신도를 요구하면 모순이다.
    #     루프 한계(3)보다 **먼저** 판정해야 사유가 정확해진다.
    if not bundle.passing() and not unrun and "no_signal" in bundle.statuses.values():
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_signal"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        return ("신호 없음 (등록 가설 전부 대조 완료, 분리되는 후보 없음): "
                "lot 내부 대조로는 원인을 좁힐 수 없다. 리포팅으로 진행한다.")

    # (3) 루프 한계 도달 강제 종료는 승인이 아니라 '미확정'
    if loop >= ya_config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["finalize_status"] = "inconclusive"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        return "미확정 (루프 한계 도달): 확정 근거 없이 리포팅으로 진행한다."

    # (4) 반려
    return _gate_rejection(claim_id, claim, bundle, unrun, conf, conf_note)


def _confidence(raw) -> tuple[float, str]:
    try:
        return float(raw), ""
    except (TypeError, ValueError):
        return 0.0, (f" (confidence 로 받은 '{raw}' 은 숫자가 아니다 - "
                     f"0~1 사이 숫자로 다시 제출하라)")


def _gate_rejection(claim_id, claim, bundle, unrun, conf, conf_note) -> str:
    """왜 승인하지 않았는지를 LLM 이 다음 행동으로 옮길 수 있게 돌려준다."""
    if claim_id and claim is None:
        valid = sorted(bundle.claims)
        avail = ("유효한 claim_id: " + ", ".join(valid)) if valid else "아직 유효한 claim 이 없다"
        return f"반려: claim_id '{claim_id}' 는 도구 결과에 없다. {avail}."

    if claim is not None:
        if not claim.passes:
            return (f"반려: {claim.claim_id} 는 판별선을 넘지 못했다 ({claim.reject_reason}). "
                    f"통과한 후보를 지목하라.")
        top = bundle.top_score(claim.tool)
        if claim.score < top:
            best = max((c for c in bundle.passing() if c.tool == claim.tool),
                       key=lambda c: c.score)
            return (f"반려: {claim.claim_id}(점수 {claim.score}) 보다 강한 후보가 있다: "
                    f"{best.claim_id}(점수 {best.score}). 근거가 가장 강한 후보를 지목하라.")
        return (f"반려: 확신도 {conf:.2f} < {ya_config.CONFIDENCE_THRESHOLD}.{conf_note} "
                f"근거를 좁힐 tool 을 더 호출하라.")

    # claim_id 미제출
    valid = sorted(c.claim_id for c in bundle.passing())
    if valid:
        return (f"반려: claim_id 를 제출하지 않았다. 결론은 도구가 발급한 claim_id 로 "
                f"지목해야 한다. 통과 후보: {', '.join(valid)}.")
    if unrun:
        return (f"반려: 통과한 후보가 없다. 아직 실행하지 않은 가설 도구가 있다: "
                f"{', '.join(unrun)}. 먼저 호출하라.")
    if bundle.ran:
        return ("반려: 등록 가설을 다 돌렸으나 판별선을 넘은 후보가 없다. "
                "2단 센서로 근거를 더 좁히거나 대조군을 다시 보라.")
    return "반려: 그룹 대조 근거가 없다. 가설 도구(hyp_*)로 두 그룹을 먼저 대조하라."


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    claim = state.get("final_claim")
    report = _llm_lazy().generate_report(
        target_wafers=state.get("target_wafers", []),
        target_source=state.get("target_source", "manual"),
        target_group=state["target_group"],
        status_summary=state["status_summary"],
        findings=state["findings"],
        hypothesis=state.get("final_hypothesis"),
        confidence=state.get("final_confidence"),
        finalize_status=state.get("finalize_status"),
        claim=claim,
    )
    if claim:
        # [근거] 줄은 클라이언트(LLM)가 아니라 여기서 코드로 붙인다 - 운영에서도
        # 근거가 리포트에서 사라지지 않게 하려는 것이 이 기능의 목적이다.
        report += f"\n[근거] {evidence.format_evidence_line(claim)}"
    return {"report": report}
