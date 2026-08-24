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
- **claim_id 는 결론 하나를 고르는 것이 아니라 서술의 축을 정하는 것이다.** 판별선을 넘은 후보는 게이트가 전부 접어서 줄 세워 리포트에 싣는다 - 다른 축의 근거를 버릴까 걱정해 지목을 미루지 마라. 다만 순위 1등이 아닌 것을 지목하면 반려된다.
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
    claim 이 판별선을 넘었는지와 **축을 가로지른 순위에서 1등 묶음인지**를 확인한다.

    게이트의 성격이 바뀌었다: 예전에는 "LLM 이 고른 하나를 승인/반려" 하는 이진
    판정이었고, 지금은 **통과 후보 전부를 접어서 줄 세운 뒤 종료**한다. LLM 의
    지목은 서술의 축을 정할 뿐이고, 무엇이 근거로 남는지는 코드가 정한다.
    예전 계약은 도구 안 최고 점수 하나만 승인해서, 축이 여럿일 때 나머지 근거가
    리포트에 도달하지 못했다(같은 wafer 를 가리키는 교락도 구분되지 않았다).

    판정은 위에서부터 처음 걸리는 줄로 결정된다:
      (1) 지목한 claim 이 통과 + 1등 묶음 + 확신도 충족 -> confirmed
      (2) 등록 가설을 다 돌렸는데 통과 후보 0 + no_signal 있음 -> no_signal
      (3) 돌아간 가설이 전부 '계산 불가' -> no_comparable_data
      (4) 루프 한계 -> inconclusive (승인이 아니라 '미확정')
      (5) 그 외 -> 반려. 무엇이 모자란지 그대로 돌려준다.
    """
    bundle = evidence.build_bundle(findings)
    conf, conf_note = _confidence(args.get("confidence", 0.0))
    hypothesis = args.get("hypothesis", "")
    claim_id = (args.get("claim_id") or "").strip()
    claim = bundle.claims.get(claim_id)
    coverage = _coverage(bundle)
    update["coverage"] = coverage
    unrun = coverage["unrun"]
    groups = bundle.ranked_groups()
    picked = evidence.find_group(groups, claim_id) if claim_id else None

    # (1) 승인
    if (claim is not None and claim.passes
            and picked is not None and picked.rank_key == groups[0].rank_key
            and conf >= ya_config.CONFIDENCE_THRESHOLD):
        update["finalize_accepted"] = True
        update["finalize_status"] = "confirmed"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        # **통과 후보를 전부 싣는다.** LLM 이 고른 것만 남기면 나머지 축의 근거가
        # 여기서 사라진다 - 그게 예전 계약의 결함이었다.
        _record_evidence(update, groups, picked)
        # 머리말은 **LLM 이 지목한 묶음**으로 쓴다. 1등이 여럿일 때 groups[0] 을 쓰면
        # "승인" 이라면서 제출한 것과 다른 claim 의 수치를 보여 주게 되고, LLM 이
        # 산문에서 엉뚱한 claim 을 인용하게 된다.
        head = evidence.format_group_line(
            next(c for c in update["final_claims"] if c.get("picked_by_llm")))
        more = (f" 그 밖에 {len(groups) - 1}개 근거를 함께 싣는다."
                if len(groups) > 1 else "")
        return f"승인 (근거 확인): {head}.{more} 리포팅으로 진행한다."

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
    if (not bundle.passing() and not claim_id
            and "no_signal" in bundle.statuses.values()):
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_signal"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        _record_evidence(update, groups, picked)
        if unrun:
            return (f"신호 없음 ({_coverage_phrase(coverage)}): 대조한 축에서는 원인을 "
                    f"좁힐 수 없다. 결론은 돌린 축에 한한 것이며 그 사실이 리포트에 "
                    f"함께 나간다. 리포팅으로 진행한다.")
        return (f"신호 없음 ({_coverage_phrase(coverage)}, 분리되는 후보 없음): "
                f"lot 내부 대조로는 원인을 좁힐 수 없다. 리포팅으로 진행한다.")

    # (3) 계산 불가 - 돌아간 가설이 전부 그룹 수준 사실(대조 짝 없음·타깃 부족)에서 멈췄다.
    #     이 상태는 legend 와 무관하므로 **아직 안 돌린 가설을 기다리지 않는다** - 기다리면
    #     LLM 이 루프 한계까지 왕복하다 inconclusive("확정 근거 없음")로 끝나고, 진짜 사유인
    #     데이터 결측이 리포트에서 사라진다. 사람이 할 일도 다르다(적재/추출 범위 확인).
    ran_statuses = set(bundle.statuses.values())
    if ran_statuses and ran_statuses <= cm.NO_DATA_STATUSES:
        update["finalize_accepted"] = True
        update["finalize_status"] = "no_comparable_data"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        _record_evidence(update, groups, picked)
        return (f"비교 가능한 데이터 없음 ({', '.join(sorted(ran_statuses))}): "
                f"대조에 쓸 짝이 없어 계산이 성립하지 않는다. 리포팅으로 진행한다.")

    # (4) 루프 한계 도달 강제 종료는 승인이 아니라 '미확정'
    if loop >= ya_config.MAX_LOOPS:
        update["finalize_accepted"] = True
        update["finalize_status"] = "inconclusive"
        update["final_hypothesis"] = hypothesis
        update["final_confidence"] = conf
        _record_evidence(update, groups, picked)
        return "미확정 (루프 한계 도달): 확정 근거 없이 리포팅으로 진행한다."

    # (5) 반려
    return _gate_rejection(claim_id, claim, bundle, unrun, conf, conf_note, groups)


def _record_evidence(update: dict, groups, picked) -> None:
    """판별선을 넘은 근거를 상태에 싣는다. **모든 종료 경로에서 부른다.**

    예전에는 승인(confirmed) 경로에서만 실었다. 그런데 루프 한계로 끝나는
    inconclusive 는 "확정은 못 했지만 판별선을 넘은 후보는 있다" 는 상태라,
    거기서 목록을 버리면 **가장 도움이 필요한 보고서에서 근거가 전부 사라진다**
    (다축 fixture M2423 이 실제로 그렇게 끝났다: 통과 후보 3개, 리포트 근거 0줄).
    no_signal·no_comparable_data 는 정의상 통과 후보가 없어 빈 목록이 되지만,
    "왜 비었는가" 를 경로마다 다시 따지지 않도록 같은 함수를 탄다.

    상한을 두는 이유: 후보는 도구마다 `COMMONALITY_TOP_K` 만큼 나올 수 있고
    계측 축은 무신호에서도 절반 가까이가 판별선을 넘는다. 상한이 없으면 리포트와
    운영 LLM 프롬프트에 근거 블록이 수십 개 쏟아져, 근거를 살리려던 변경이
    보고서를 오히려 못 읽게 만든다. 잘린 수는 마지막 항목에 남겨 숨기지 않는다.
    """
    limit = ya_config.REPORT_MAX_EVIDENCE
    dicts = evidence.groups_to_dicts(groups, picked)
    if len(dicts) > limit:
        kept = dicts[:limit]
        if picked is not None and not any(d.get("picked_by_llm") for d in kept):
            # **지목한 묶음은 잘라 내지 않는다.** 1등이 동점으로 여럿일 때 LLM 이
            # 정렬상 뒤쪽을 지목하면 그것이 상한 밖으로 밀려날 수 있는데, 그러면
            # 리포트에 서술의 축이 없어지고 승인 문구가 참조할 대상도 사라진다.
            kept = kept[:limit - 1] + [d for d in dicts if d.get("picked_by_llm")]
        dicts, hidden = kept, len(dicts) - len(kept)
        if hidden:
            dicts[-1]["more_below"] = hidden
    update["final_claims"] = dicts


def _coverage(bundle) -> dict:
    """어느 축까지 봤는가 - **전제 조건이 아니라 보고하는 사실.**

    `no_data` 를 따로 세는 이유: 계측(metro) 축은 계측 짝이 없으면
    `no_paired_stratum` 으로 끝난다. 호출은 됐지만 대조한 것은 없다는 뜻이라,
    `ran` 으로만 세면 커버리지가 실제보다 넓어 보인다.
    """
    registered = {n for n in TOOLS_BY_NAME if n.startswith("hyp_")}
    return {
        "ran": sorted(bundle.ran),
        "unrun": sorted(registered - bundle.ran),
        "no_data": sorted(t for t, st in bundle.statuses.items()
                          if st in cm.NO_DATA_STATUSES),
    }


def _coverage_phrase(coverage: dict) -> str:
    """커버리지를 사람이 읽는 한 줄로. 게이트 응답과 리포트가 같은 문장을 쓴다."""
    ran = coverage.get("ran") or []
    unrun = coverage.get("unrun") or []
    parts = [f"등록 축 {len(ran) + len(unrun)}개 중 {len(ran)}개 대조"]
    if unrun:
        parts.append(f"안 돌린 축 {len(unrun)}개: {', '.join(unrun)}")
    no_data = coverage.get("no_data") or []
    if no_data:
        parts.append(f"돌았으나 계산이 성립하지 않은 축: {', '.join(no_data)}")
    return ". ".join(parts)


def _confidence(raw) -> tuple[float, str]:
    try:
        return float(raw), ""
    except (TypeError, ValueError):
        return 0.0, (f" (confidence 로 받은 '{raw}' 은 숫자가 아니다 - "
                     f"0~1 사이 숫자로 다시 제출하라)")


def _gate_rejection(claim_id, claim, bundle, unrun, conf, conf_note, groups) -> str:
    """왜 승인하지 않았는지를 LLM 이 다음 행동으로 옮길 수 있게 돌려준다."""
    if claim_id and claim is None:
        # 안내 대상은 **통과 후보뿐**이다. 번들 전체를 안내하면 LLM 이 거기서
        # 미통과 후보를 골라 다시 제출하고 또 반려당하는 왕복이 생긴다 -
        # claim_id 미제출 분기(아래)와 같은 것을 안내해야 한다.
        valid = sorted(c.claim_id for c in bundle.passing())
        if valid:
            return (f"반려: claim_id '{claim_id}' 는 도구 결과에 없다. "
                    f"통과 후보: {', '.join(valid)}.")
        # 지목할 대상이 아예 없으면 목록 대신 다음 행동을 안내한다 - 여기서 멈추면
        # LLM 이 할 일을 못 찾아 루프 한계까지 왕복만 한다.
        return (f"반려: claim_id '{claim_id}' 는 도구 결과에 없다. "
                f"{_no_candidate_action(bundle, unrun)}")

    if claim is not None:
        if not claim.passes:
            return (f"반려: {claim.claim_id} 는 판별선을 넘지 못했다 ({claim.reject_reason}). "
                    f"통과한 후보를 지목하라.")
        picked = evidence.find_group(groups, claim_id)
        if picked is not None and groups and picked.rank_key != groups[0].rank_key:
            # 순위는 코드가 매긴다. 순열 p 가 먼저이고 동점이면 분리 점수다 —
            # 점수만 보고 고르면 탐색 폭이 넓은 축(계측)이 늘 이긴다.
            best = groups[0].lead
            return (f"반려: {claim.claim_id}(p {claim.p_permutation}, 점수 {claim.score}) "
                    f"보다 앞선 근거가 있다: {best.claim_id}"
                    f"(p {best.p_permutation}, 점수 {best.score}). "
                    f"순위 1등을 서술의 축으로 지목하라 - 나머지 근거는 게이트가 함께 싣는다.")
        return (f"반려: 확신도 {conf:.2f} < {ya_config.CONFIDENCE_THRESHOLD}.{conf_note} "
                f"근거를 좁힐 tool 을 더 호출하라.")

    # claim_id 미제출
    valid = sorted(c.claim_id for c in bundle.passing())
    if valid:
        return (f"반려: claim_id 를 제출하지 않았다. 결론은 도구가 발급한 claim_id 로 "
                f"지목해야 한다. 통과 후보: {', '.join(valid)}.")
    return f"반려: {_no_candidate_action(bundle, unrun)}"


def _no_candidate_action(bundle, unrun) -> str:
    """지목할 통과 후보가 하나도 없을 때 LLM 이 다음에 할 일.

    claim_id 를 지어낸 경로와 아예 안 낸 경로가 같은 막다른 상태에 도달하므로
    안내도 같아야 한다 - 한쪽만 다음 행동을 알려주면 다른 쪽은 왕복만 하다
    루프 한계로 끝난다.
    """
    # 물러서는 길은 **실제로 열려 있을 때만** 알려 준다. (2)번은 어떤 축이
    # no_signal 을 냈을 때만 열리므로, 그렇지 않은데 "비우고 제출하라" 고 하면
    # 같은 반려가 돌아와 라이브락이 된다.
    step_back = (" 지목할 것이 없어 물러설 때는 claim_id 를 비우고 finalize 하라."
                 if "no_signal" in bundle.statuses.values() else "")
    if unrun:
        # 명령문이 아니라 선택지다. 판정에서 전축 강제를 걷어내 놓고 여기에
        # "먼저 호출하라" 를 남기면 LLM 은 여전히 체크리스트를 소화하러 간다 -
        # 규칙은 판정과 안내 두 곳에 쓰여 있었다.
        return (f"통과한 후보가 없다. 아직 안 돌린 가설 도구: {', '.join(unrun)}. "
                f"이 중 하나를 더 보거나, 2단 센서로 근거를 좁혀라 - 전부 돌릴 "
                f"의무는 없다.{step_back}")
    if bundle.ran:
        return ("등록 가설을 다 돌렸으나 판별선을 넘은 후보가 없다. "
                "2단 센서로 근거를 더 좁히거나 대조군을 다시 보라." + step_back)
    return "그룹 대조 근거가 없다. 가설 도구(hyp_*)로 두 그룹을 먼저 대조하라."


# ------------------------------------------------ 고정 골격: 리포팅
def report_node(state: dict) -> dict:
    claims = state.get("final_claims") or []
    try:
        report = _llm_lazy().generate_report(
            target_wafers=state.get("target_wafers", []),
            target_source=state.get("target_source", "manual"),
            target_group=state["target_group"],
            status_summary=state["status_summary"],
            findings=state["findings"],
            hypothesis=state.get("final_hypothesis"),
            confidence=state.get("final_confidence"),
            finalize_status=state.get("finalize_status"),
            claims=claims,
            coverage=state.get("coverage"),
        )
    except Exception as e:
        # 여기가 마지막 노드다 - 예외를 내보내면 분석을 다 해 놓고 결과를 전부 버린다.
        # 산문만 포기하고 결론은 코드로 적는다. 현황·감사 기록은 main.py 가 상태에서
        # 따로 찍으므로, 여기서 필요한 것은 '왜 산문이 없는지'와 결론뿐이다.
        report = (f"[리포트 생성 실패] LLM 호출이 실패해 산문 리포트를 만들지 못했다 "
                  f"({type(e).__name__}: {e}). 아래는 코드가 적은 결론이다.\n"
                  f"[판정] {state.get('finalize_status') or '미상'}\n"
                  f"[결론] {state.get('final_hypothesis') or '원인 미확정'}"
                  f" (확신도 {state.get('final_confidence')})")
    # [근거] 줄은 클라이언트(LLM)가 아니라 여기서 코드로 붙인다 - 운영에서도
    # 근거가 리포트에서 사라지지 않게 하려는 것이 이 기능의 목적이다.
    # 여러 줄인 이유: 축이 여럿이면 근거도 여럿이고, 그중 하나만 남기던 것이
    # 고치려던 문제다. 순서는 코드가 매긴 순위이며 LLM 이 고른 것은 표시된다.
    for group in claims:
        mark = " ←서술 기준" if group.get("picked_by_llm") else ""
        # 번호는 위치가 아니라 **등수**다. 동점이 1·2 로 찍히면 앞선 것이 더 강해
        # 보이는데, 그 오독을 막으려고 등수를 따로 계산해 둔 것이다.
        report += (f"\n[근거 {group.get('rank', '?')}]{mark} "
                   f"{evidence.format_group_line(group)}")
        if group.get("more_below"):
            report += (f"\n[근거 ...] 순위 밖 {group['more_below']}건은 생략했다 "
                       f"(전체는 분석 과정 기록에 있다)")
    # [커버리지] 줄도 여기서 코드로 붙인다 - [근거] 와 같은 이유다. 클라이언트에
    # 맡기면 운영 경로에서만 조용히 사라진다.
    # 게이트를 안 거치고 끝나는 경로가 있다(루프 한계 강제 종료, tool 없는 텍스트
    # 응답). 거기서 state 에 coverage 가 없다고 줄을 빼면, 설명이 가장 필요한
    # 보고서에서만 커버리지가 사라진다 - 감사 기록에서 다시 센다.
    coverage = state.get("coverage") or _coverage(
        evidence.build_bundle(state.get("findings") or []))
    # 하나도 안 돌렸으면 붙이지 않는다 - "4개 중 0개 대조" 는 사실이지만 셀 것이
    # 없는 보고서(이상 없음 등)에서는 소음일 뿐이다.
    if coverage.get("ran"):
        report += f"\n[커버리지] {_coverage_phrase(coverage)}"
    return {"report": report}
