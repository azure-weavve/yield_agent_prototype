"""ScriptedMockLLMClient: 그룹 대조 시나리오 순서·파싱·finalize 인자 검증.

mock 은 tools 노드가 만들 ToolMessage(name=..., content=json)를 보고
다음 tool 을 결정한다 — 여기서는 그 ToolMessage 를 손으로 만들어 단계를 진행시킨다.
"""

import json

from langchain_core.messages import HumanMessage, ToolMessage

from llm.client import ScriptedMockLLMClient

HUMAN = HumanMessage(
    "현황: ...\n\n불량 그룹 (center_spot): W2406_02, W2406_04, W2406_06\n"
    "대조 그룹 (정상): W2406_01, W2406_03, W2406_05\n질문: 원인 분석해줘"
)
TARGET = ["W2406_02", "W2406_04", "W2406_06"]
CONTROL = ["W2406_01", "W2406_03", "W2406_05"]


def _tm(name, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ToolMessage(content, tool_call_id=f"call_{name}", name=name)


def test_scripted_sequence():
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]

    # 1) 불량 그룹의 defect 공유 확인부터
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "aggregate_defects"
    assert ai.tool_calls[0]["args"]["wafer_ids"] == TARGET
    assert ai.content  # thought(가설 서술)가 감사 기록 재료로 반드시 존재
    msgs += [ai, _tm("aggregate_defects", [{"defect_type": "center_spot", "count": 3}])]

    # 2) 조기 finalize (낮은 확신도 → 게이트 반려 시연용)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    msgs += [ai, _tm("finalize", "반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.")]

    # 3) 그룹 대조로 원인 공정/장비를 좁힌다
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "compare_process_logs"
    assert ai.tool_calls[0]["args"] == {"group_ids": TARGET, "control_ids": CONTROL}
    msgs += [ai, _tm("compare_process_logs", {
        "suspect_equipment": [{"process_step": "Etch", "equipment_id": "ETCH-9",
                               "group_count": 3, "control_count": 0}],
        "equipment_usage": [],
        "group_spec_violations": [
            {"wafer_id": w, "process_step": "Etch", "equipment_id": "ETCH-9",
             "param_name": "rf_power", "param_value": 570.0,
             "spec_low": 450.0, "spec_high": 550.0}
            for w in TARGET
        ],
    })]

    # 4) 최종 finalize — 스펙 이탈 장비를 가설에 명시
    ai = llm.analyze_step(msgs)
    call = ai.tool_calls[0]
    assert call["name"] == "finalize"
    assert call["args"]["confidence"] >= 0.8
    assert "ETCH-9" in call["args"]["hypothesis"]


def test_generate_report_contains_findings_and_conclusion():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="원인 분석해줘",
        target_group=TARGET,
        status_summary="LOT2406 평균 84.8",
        findings=[{"loop": 1, "tool": "aggregate_defects", "args": {"wafer_ids": TARGET},
                   "result": [], "thought": "불량 유형 공유 확인"}],
        hypothesis="Etch 공정 ETCH-9 장비 rf_power 스펙 이탈이 원인",
        confidence=0.9,
    )
    assert "W2406_02" in report
    assert "aggregate_defects" in report
    assert "ETCH-9" in report


def test_generate_report_handles_no_hypothesis():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="q", target_group=["W1"], status_summary="s",
        findings=[], hypothesis=None, confidence=None,
    )
    assert "미확정" in report


def test_generate_report_distinguishes_ungrouped_from_no_anomaly():
    # 문제 3 (2026-07-18 리뷰): "그룹 못 묶음"(분석 미수행)과 "이상 없음"은 다른 결론이다
    llm = ScriptedMockLLMClient()
    ungrouped = llm.generate_report(
        question="q", target_group=[], status_summary="LOT2407 평균 89.8",
        findings=[], hypothesis=None, confidence=None, finalize_status="ungrouped",
    )
    no_anomaly = llm.generate_report(
        question="q", target_group=[], status_summary="수율 임계 미만인 lot 없음.",
        findings=[], hypothesis=None, confidence=None, finalize_status="no_anomaly",
    )
    assert "묶지 못" in ungrouped        # 수율 이상은 실재 — 분석 미수행임을 밝힌다
    assert "이상 없음" in no_anomaly
    assert "이상 없음" not in ungrouped  # 두 결론이 서로 뭉개지지 않는다


def test_generate_report_renders_inconclusive_status():
    # 한계 도달(inconclusive) 종료: 결론을 "미확정 + 유력 가설(후보)" 톤으로 표기
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        question="q", target_group=TARGET, status_summary="s",
        findings=[], hypothesis="ETCH-9 rf_power 이상 추정", confidence=0.5,
        finalize_status="inconclusive",
    )
    assert "미확정" in report
    assert "한계" in report          # 왜 미확정인지 (루프 한계 도달)
    assert "ETCH-9" in report        # 유력 가설은 후보로 남긴다
