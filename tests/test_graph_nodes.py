"""노드 단위 검증 — 특히 tools 노드의 finalize 게이트(승인/반려)와 감사 기록."""

from langchain_core.messages import AIMessage, ToolMessage

from graph import nodes


def _ai_finalize(confidence, hypothesis="Etch ETCH-9 원인"):
    return AIMessage(
        content="종료 제안",
        tool_calls=[{"name": "finalize",
                     "args": {"hypothesis": hypothesis, "confidence": confidence},
                     "id": "call_f"}],
    )


# 게이트 증거 검사용(신형): 챔버 가설이 ETCH-9 를 통과 판정한 감사 기록
EVIDENCE_FINDING = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "eqp_ch_commonality",
               "legend": [{"level": "chamber", "columns": ["eqp_id", "ch_id"]}],
               "status": "ok",
               "candidates": [
                   {"value": ["Etch", "ETCH-9"], "passes": True,
                    "level": "chamber", "key": "ETCH-9",
                    "target_pass": 3, "control_pass": 0, "reject_reason": None},
               ]},
    "thought": "그룹 대조",
}

# 신형(레지스트리) 증거 finding: 챔버 가설이 ETCH9_B 를 통과 판정
EVIDENCE_FINDING_NEW = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "eqp_ch_commonality",
               "legend": [{"level": "chamber", "columns": ["eqp_id", "ch_id"]}],
               "status": "ok",
               "candidates": [
                   {"value": ["Etch", "ETCH9_B"], "passes": True,
                    "level": "chamber", "key": "ETCH9_B",
                    "target_pass": 3, "control_pass": 0, "reject_reason": None},
                   {"value": ["Photo", "PHOTO1_A"], "passes": False,
                    "level": "chamber", "key": "PHOTO1_A",
                    "target_pass": 3, "control_pass": 3, "reject_reason": "분리 없음"},
               ]},
    "thought": "챔버 편중",
}


def test_collect_evidence_gathers_passing_tokens():
    tokens = nodes._collect_evidence([EVIDENCE_FINDING_NEW])
    assert tokens == {"ETCH9_B"}          # 통과 후보만, 미끼(PHOTO1_A) 제외


def test_gate_accepts_chamber_hypothesis():
    ai = _ai_finalize(0.9, hypothesis="Etch 공정 ETCH9_B 챔버 편중이 원인")
    out = nodes.tools_node({"messages": [ai], "loop_count": 4, "findings": [EVIDENCE_FINDING_NEW]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"


def test_status_node_sets_groups_and_seed_messages():
    out = nodes.status_node({"target_wafers": ["W2406_02"], "target_source": "manual"})
    assert out["target_group"][0] == "W2406_02"
    assert {"W2406_04", "W2406_06"} < set(out["target_group"])   # EDS 형제 (전 lot)
    assert "W2406_07" in out["control_group"]     # 라벨 없는 저수율 wafer 도 대조군 (spec 결정 1)
    seed = out["messages"][-1].content
    assert "GROUPS_JSON=" in seed                                # mock 파싱 계약 (문제 7)
    assert [f["tool"] for f in out["findings"]] == ["normalize_target", "select_control"]
    assert all(f["loop"] == 0 for f in out["findings"])


def test_status_exit_no_anomaly_when_no_targets():
    # 자동 선정이 빈손이면(이상 lot 없음) 대상 없음 = no_anomaly
    out = nodes.status_node({"target_wafers": [], "target_source": "auto"})
    assert out["target_group"] == []
    assert out["finalize_status"] == "no_anomaly"


def test_status_exit_unknown_target():
    out = nodes.status_node({"target_wafers": ["W_NOPE"], "target_source": "manual"})
    assert out["finalize_status"] == "unknown_target"
    assert "W_NOPE" in out["status_summary"]


def test_status_exit_isolated_when_no_siblings():
    # 6절 4번: 형제 없음 = 고립 패턴, 자동 분석 범위 밖 — 별도 상태로 리포트까지
    out = nodes.status_node({"target_wafers": ["W2407_01"], "target_source": "manual"})
    assert out["finalize_status"] == "isolated"
    assert out["control_group"] == []                    # 고립 = 대조군 자체가 성립 안 함
    assert "고립" in out["status_summary"]


def test_summary_notes_unmatched_siblings():
    # EDS/DB 동기화 어긋남으로 대상에서 빠진 형제를 사람용 요약에도 남긴다 (재리뷰 Minor)
    norm = {"mode": "single", "target_group": ["W2406_02", "W2406_04"],
            "siblings": [{"wafer_id": "W2406_04", "similarity": 0.95}],
            "unmatched_siblings": ["W_GHOST"], "unknown_wafers": [], "isolated": False}
    ctrl = {"control_group": ["W2406_01", "W2406_03", "W2406_05"],
            "sources": {"LOT2406": ["W2406_01", "W2406_03", "W2406_05"]},
            "insufficient": False,
            "yield_summary": {"median": 95.3, "n_below_threshold": 0, "threshold": 90.0}}
    summary = nodes._summarize_target("manual", ["W2406_02"], norm, ctrl)
    assert "W_GHOST" in summary


def test_status_exit_control_insufficient():
    # 7절 3단계: 대조군 부족은 확장하지 않고 정직 보고
    out = nodes.status_node({"target_wafers": ["W2407_01", "W2407_02"],
                             "target_source": "manual"})
    assert out["finalize_status"] == "control_insufficient"
    assert out["target_group"] == ["W2407_01", "W2407_02"]


def test_status_respects_user_specified_target():
    # (구 xfail 소생 — 문제 1) 지정 대상이 그대로 분석 대상이 된다. lots[0] 하이재킹 없음.
    out = nodes.status_node({"target_wafers": ["W2407_01", "W2407_02"],
                             "target_source": "manual"})
    assert out["target_group"] == ["W2407_01", "W2407_02"]
    assert not {"W2406_02", "W2406_04", "W2406_06"} & set(out["target_group"])


def test_tools_node_executes_and_records_finding():
    # get_process_log 는 레거시(기본 OFF) 라 기본 노출 도구인 get_wafer 로 대체 —
    # 검증 대상은 tools_node 의 실행·기록 메커니즘이지 특정 도구가 아니다.
    ai = AIMessage(
        content="유사 사례 확인",
        tool_calls=[{"name": "get_wafer",
                     "args": {"wafer_id": "W2406_02"}, "id": "call_1"}],
    )
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    tm = out["messages"][0]
    assert isinstance(tm, ToolMessage) and tm.name == "get_wafer"
    f = out["findings"][0]
    assert (f["loop"], f["tool"], f["thought"]) == (1, "get_wafer", "유사 사례 확인")
    assert f["result"]["wafer_id"] == "W2406_02"              # 결과 원본이 그대로 남는다
    assert "finalize_accepted" not in out


def test_finalize_gate_rejects_low_confidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.6)], "loop_count": 3})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert out["findings"][0]["tool"] == "finalize"          # 반려도 감사 기록에 남는다


def test_finalize_gate_accepts_high_confidence_with_evidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"
    assert out["final_hypothesis"] == "Etch ETCH-9 원인"
    assert out["final_confidence"] == 0.9
    assert "승인" in out["messages"][0].content


def test_finalize_gate_rejects_high_confidence_without_evidence():
    # (a) 조사 없이 결론: confidence 0.9 라도 그룹 대조 근거가 없으면 반려
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 1,
                            "findings": []})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert "hyp_" in out["messages"][0].content  # 무엇을 하라는지 안내


def test_finalize_gate_rejects_hypothesis_not_backed_by_evidence():
    # (b) 조사와 다른 결론: tool 결과는 ETCH-9 를 지목했는데 가설은 CVD-3
    out = nodes.tools_node({
        "messages": [_ai_finalize(0.9, hypothesis="CVD-3 장비의 온도 이상이 원인")],
        "loop_count": 3, "findings": [EVIDENCE_FINDING],
    })
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert "ETCH-9" in out["messages"][0].content  # 실제 suspect 후보를 알려준다


def test_finalize_gate_sees_evidence_from_same_message():
    # 한 메시지에 hyp_eqp_ch_commonality + finalize 가 같이 오면, 방금 실행된 대조 결과도 증거다
    ai = AIMessage(
        content="그룹 대조 후 바로 종료 제안",
        tool_calls=[
            {"name": "hyp_eqp_ch_commonality",
             "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
                      "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
             "id": "call_c"},
            {"name": "finalize",
             "args": {"hypothesis": "Etch ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
             "id": "call_f"},
        ],
    )
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": []})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"


def test_finalize_gate_marks_inconclusive_at_max_loops():
    # (c) 한계 도달 강제 종료는 "승인"이 아니라 "미확정"으로 구분 기록
    out = nodes.tools_node({"messages": [_ai_finalize(0.5)], "loop_count": 6,
                            "findings": []})
    assert out["finalize_accepted"] is True                  # 루프는 종료하되
    assert out["finalize_status"] == "inconclusive"          # 확정 결론이 아님을 기록
    assert "미확정" in out["messages"][0].content


def test_report_node_produces_report():
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02", "W2406_04", "W2406_06"], "status_summary": "요약",
        "findings": [], "final_hypothesis": "Etch ETCH-9 원인", "final_confidence": 0.9,
    })
    assert "ETCH-9" in out["report"]


def test_report_node_marks_inconclusive_conclusion():
    # 한계 도달 종료는 리포트 결론도 "미확정" 톤으로 나가야 한다 (확정 결론으로 위장 금지)
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약",
        "findings": [], "final_hypothesis": "ETCH-9 이상 추정", "final_confidence": 0.5,
        "finalize_status": "inconclusive",
    })
    assert "미확정" in out["report"]
    assert "ETCH-9" in out["report"]  # 유력 가설은 후보로는 남긴다

def test_tools_node_recovers_from_unknown_tool_name():
    ai = AIMessage(content="", tool_calls=[
        {"name": "functions.get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert "오류" in out["messages"][0].content
    assert "get_wafer" in out["messages"][0].content


def test_tools_node_recovers_from_bad_args():
    ai = AIMessage(content="", tool_calls=[
        {"name": "get_wafer", "args": {}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert "오류" in out["messages"][0].content


def test_finalize_gate_handles_non_numeric_confidence():
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize", "args": {"hypothesis": "Etch ETCH-9 원인",
                                      "confidence": "high"}, "id": "cf"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": []})
    assert "finalize_accepted" not in out
    assert "숫자" in out["messages"][0].content


def test_tools_node_skips_calls_after_finalize_accepted():
    """승인 뒤 같은 메시지의 잔여 tool 은 실행되지 않는다 — 종료 판정 뒤에 생긴 증거가
    감사 기록에 섞이면 안 된다. 단 ToolMessage 는 tool_call 수만큼 채운다(LangChain 계약)."""
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize",
         "args": {"hypothesis": "Etch 공정 ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
         "id": "cf"},
        {"name": "get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"},
    ])
    out = nodes.tools_node({"messages": [ai], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING_NEW]})

    assert out["finalize_accepted"] is True
    assert len(out["messages"]) == 2                   # 모든 tool_call 에 응답이 있다
    assert "생략" in out["messages"][1].content
    skipped = [f for f in out["findings"] if f["tool"] == "get_wafer"]
    assert len(skipped) == 1
    assert "생략" in skipped[0]["result"]              # 조회 결과(dict)가 아니라 생략 기록
    assert "thought" in skipped[0]                     # 감사 기록 형식은 유지


def test_second_finalize_does_not_overwrite_accepted_hypothesis():
    """한 메시지에 finalize 가 2개면 뒤가 앞의 승인 가설을 덮어썼다."""
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize",
         "args": {"hypothesis": "Etch 공정 ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
         "id": "cf1"},
        {"name": "finalize",
         "args": {"hypothesis": "ETCH9_B 와 무관한 다른 가설", "confidence": 0.95},
         "id": "cf2"},
    ])
    out = nodes.tools_node({"messages": [ai], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING_NEW]})
    assert out["final_hypothesis"] == "Etch 공정 ETCH9_B 챔버 편중이 원인"
    assert len(out["messages"]) == 2


def test_tools_node_falls_back_to_reason_when_content_empty():
    # 실제 LLM 은 tool call 시 content 를 비우므로 reason 인자가 감사 기록을 채운다
    ai = AIMessage(content="", tool_calls=[
        {"name": "get_process_log",
         "args": {"wafer_id": "W2406_02", "reason": "스펙 이탈 확인"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert out["findings"][0]["thought"] == "스펙 이탈 확인"