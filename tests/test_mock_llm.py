"""ScriptedMockLLMClient: 그룹 대조 시나리오 순서·파싱·finalize 인자 검증.

mock 은 tools 노드가 만들 ToolMessage(name=..., content=json)를 보고
다음 tool 을 결정한다 — 여기서는 그 ToolMessage 를 손으로 만들어 단계를 진행시킨다.
"""

import json

from langchain_core.messages import HumanMessage, ToolMessage

from llm.client import ScriptedMockLLMClient

HUMAN = HumanMessage(
    "현황: ...\n\n불량 그룹: W2406_02, W2406_04, W2406_06\n"
    "대조 그룹 (정상): W2406_01, W2406_03, W2406_05\n"
    "분석 대상: W2406_02 의 불량 원인 분석\n"
    'GROUPS_JSON={"target": ["W2406_02", "W2406_04", "W2406_06"], '
    '"control": ["W2406_01", "W2406_03", "W2406_05"]}'
)
TARGET = ["W2406_02", "W2406_04", "W2406_06"]


def _tm(name, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ToolMessage(content, tool_call_id=f"call_{name}", name=name)


def test_scripted_sequence():
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]

    # 1) 근거 없이 조기 finalize (낮은 확신도 → 게이트 반려 시연용)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] < 0.8
    assert ai.content  # thought(가설 서술)가 감사 기록 재료로 반드시 존재
    assert ai.tool_calls[0]["args"]["claim_id"] == ""   # 근거가 없을 때도 키 자체는 제출한다
    msgs += [ai, _tm("finalize", "반려: 확신도 0.60 < 0.8. 근거를 좁힐 tool 을 더 호출하라.")]

    # 2) 1단 — 챔버 편중 가설
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"
    # 대조 분모는 인자가 아니다 - LLM 스키마에 없고 tools 노드가 state 에서 주입한다.
    # 각본이 이것을 넘기면 운영에서는 못 일어나는 모양을 e2e 가 시험하게 된다.
    assert not {"group_ids", "control_ids"} & set(ai.tool_calls[0]["args"])
    msgs += [ai, _tm("hyp_eqp_ch_commonality", {"hypothesis_id": "eqp_ch_commonality",
                                                "status": "ok", "candidates": [
        {"level": "chamber", "key": "ETCH9_B", "value": ["Etch", "ETCH9_B"],
         "claim_id": "eqp_ch_commonality:chamber:Etch:ETCH9_B",
         "step_seq": "Etch", "score": 1.0, "target_pass": 3, "passes": True},
    ]})]

    # 3) 챔버가 갈렸어도 레시피 축을 **함께** 돌린다 - 교락 확인용.
    #    여기서 멈추면 같은 wafer 를 두 이름으로 부르는 상황이 관측되지 않아,
    #    게이트가 접을 것도 없고 리포트가 근거 하나만 든 채 확신에 찬 문장을 쓴다.
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "hyp_ppid_commonality"
    assert not {"group_ids", "control_ids"} & set(ai.tool_calls[0]["args"])
    msgs += [ai, _tm("hyp_ppid_commonality", {"hypothesis_id": "ppid_commonality",
                                              "status": "no_signal", "candidates": []})]

    # 4) 2단 — 지목된 스텝의 센서 분포
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "compare_sensor_distribution"
    assert ai.tool_calls[0]["args"]["step_seq"] == "Etch"
    msgs += [ai, _tm("compare_sensor_distribution", {"status": "ok", "candidates": [
        {"sensor_name": "rf_power_steady_avg", "effect_size": 14.99},
    ]})]

    # 4) 근거를 갖춘 finalize (승인)
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] >= 0.8
    hyp = ai.tool_calls[0]["args"]["hypothesis"]
    assert "ETCH9_B" in hyp
    assert "rf_power_steady_avg" in hyp       # 2단 근거가 결론에 실린다
    assert ai.tool_calls[0]["args"]["claim_id"] == "eqp_ch_commonality:chamber:Etch:ETCH9_B"


def test_generate_report_contains_findings_and_conclusion():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        target_wafers=["W2406_02"], target_source="manual",
        target_group=TARGET,
        status_summary="LOT2406 평균 84.8",
        findings=[{"loop": 1, "tool": "hyp_eqp_ch_commonality", "args": {"wafer_ids": TARGET},
                   "result": [], "thought": "챔버 편중 확인"}],
        hypothesis="Etch 공정 ETCH-9 장비 rf_power 스펙 이탈이 원인",
        confidence=0.9,
    )
    assert "W2406_02" in report
    assert "hyp_eqp_ch_commonality" in report
    assert "ETCH-9" in report


def test_generate_report_handles_no_hypothesis():
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"], status_summary="s",
        findings=[], hypothesis=None, confidence=None,
    )
    assert "미확정" in report


def test_generate_report_distinguishes_early_exits():
    # 조기 출구 5종이 서로 뭉개지지 않는다 (문제 3 의 일반화)
    llm = ScriptedMockLLMClient()
    kw = dict(target_wafers=["W2407_01"], target_source="manual",
              status_summary="s", findings=[], hypothesis=None, confidence=None)
    isolated = llm.generate_report(target_group=["W2407_01"], finalize_status="isolated", **kw)
    short = llm.generate_report(target_group=["W2407_01"],
                                finalize_status="control_insufficient", **kw)
    unknown = llm.generate_report(target_group=[], finalize_status="unknown_target", **kw)
    no_anomaly = llm.generate_report(target_group=[], finalize_status="no_anomaly", **kw)
    eds_failed = llm.generate_report(target_group=["W2407_01"],
                                     finalize_status="eds_lookup_failed", **kw)
    assert "고립" in isolated and "추후 분석" in isolated       # 6절 4번 문구
    assert "대조군 부족" in short                               # 7절 3단계 문구
    assert "찾을 수 없" in unknown
    assert "이상 없음" in no_anomaly
    assert "이상 없음" not in isolated
    assert "EDS 유사맵 조회 실패" in eds_failed
    # '입력을 찾을 수 없다'(unknown_target)와 뭉개지지 않는다 — 조치가 다르다
    assert "찾을 수 없" not in eds_failed
    assert "고립" not in eds_failed


def test_groups_parsed_from_machine_line_not_prose():
    # 사람용 문구를 바꿔도 GROUPS_JSON 라인만 있으면 mock 이 안 깨진다 (문제 7)
    llm = ScriptedMockLLMClient()
    msgs = [HumanMessage('아무 문구나 자유롭게.\n'
                         'GROUPS_JSON={"target": ["A", "B"], "control": ["C"]}')]
    # GROUPS_JSON 은 이제 도구 인자가 아니라 **가설 서술**의 재료다 (분모는 주입된다).
    # 파싱이 깨지면 여기서 장수가 틀리고, 그 문장이 감사 기록·리포트로 나간다.
    ai = llm.analyze_step(msgs)  # 1) 조기 finalize
    assert "불량 그룹 2장" in ai.tool_calls[0]["args"]["hypothesis"]
    msgs += [ai, _tm("finalize", "반려")]
    ai = llm.analyze_step(msgs)  # 2) 1단 대조
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"


def test_scripted_survives_tool_error_string():
    """tools 노드는 실행 실패 시 오류 '문자열' 을 담는다 — 각본이 거기서 죽으면 안 된다.

    도구가 실패하면 '분리되는 후보가 없다' 와 같은 경로를 타 낮은 확신도로 물러선다.
    """
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    ai = llm.analyze_step(msgs)                      # 1) 조기 finalize
    msgs += [ai, _tm("finalize", "반려")]
    ai = llm.analyze_step(msgs)                      # 2) 1단 호출
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"
    # tools 노드는 오류 문자열도 json.dumps 로 감싸 담는다 (nodes.tools_node) —
    # 그래서 json.loads 결과가 dict 가 아니라 str 이 된다. 그 조건을 그대로 재현한다.
    msgs += [ai, _tm("hyp_eqp_ch_commonality",
                     json.dumps("오류: hyp_eqp_ch_commonality 실행 실패 "
                                "(KeyError: 'legend'). 인자를 확인하고 다시 호출하라.",
                                ensure_ascii=False))]

    ai = llm.analyze_step(msgs)                      # 3) 죽지 않고 폴백을 돈다
    assert ai.tool_calls[0]["name"] == "hyp_ppid_commonality"
    msgs += [ai, _tm("hyp_ppid_commonality",
                     json.dumps("오류: hyp_ppid_commonality 실행 실패 "
                                "(KeyError: 'legend'). 인자를 확인하고 다시 호출하라.",
                                ensure_ascii=False))]

    ai = llm.analyze_step(msgs)                      # 4) 남은 등록 가설도 오류를 낸다
    assert ai.tool_calls[0]["name"] == "hyp_step_passage_commonality"
    msgs += [ai, _tm("hyp_step_passage_commonality",
                     json.dumps("오류: hyp_step_passage_commonality 실행 실패 "
                                "(KeyError: 'legend'). 인자를 확인하고 다시 호출하라.",
                                ensure_ascii=False))]

    ai = llm.analyze_step(msgs)                      # 5) 계측 축도 마찬가지
    assert ai.tool_calls[0]["name"] == "hyp_metro_commonality"
    msgs += [ai, _tm("hyp_metro_commonality",
                     json.dumps("오류: hyp_metro_commonality 실행 실패 "
                                "(KeyError: 'legend'). 인자를 확인하고 다시 호출하라.",
                                ensure_ascii=False))]

    ai = llm.analyze_step(msgs)                      # 6) 그래도 죽지 않고 물러선다
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] == 0.2   # '후보 없음' 후퇴 분기
    assert ai.content


def test_scripted_walks_every_registered_hypothesis_before_backing_off():
    """EQP_CH 로 안 갈리면 남은 등록 가설을 순서대로 다 돌린 뒤에야 물러선다.

    첫 no_signal 로 물러서면 등록된 가설을 안 써보고 포기하는 셈이고, 게이트도
    no_signal 을 선언하지 않는다(등록 가설을 전부 돌린 뒤에만 판정한다). 그러면
    데모가 루프 한계까지 가서 사유가 틀린 inconclusive 로 끝난다.
    """
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]          # 1) 조기 finalize
    ai = llm.analyze_step(msgs)                                        # 2) 1단 EQP_CH
    assert ai.tool_calls[0]["name"] == "hyp_eqp_ch_commonality"
    msgs += [ai, _tm("hyp_eqp_ch_commonality", {"hypothesis_id": "eqp_ch_commonality",
                                                "status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)                                        # 3) 폴백 PPID
    assert ai.tool_calls[0]["name"] == "hyp_ppid_commonality"
    assert not {"group_ids", "control_ids"} & set(ai.tool_calls[0]["args"])
    msgs += [ai, _tm("hyp_ppid_commonality", {"hypothesis_id": "ppid_commonality",
                                              "status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)                                        # 4) 폴백 스텝 통과
    assert ai.tool_calls[0]["name"] == "hyp_step_passage_commonality"
    msgs += [ai, _tm("hyp_step_passage_commonality",
                     {"hypothesis_id": "step_passage_commonality",
                      "status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)                                        # 5) 폴백 계측
    assert ai.tool_calls[0]["name"] == "hyp_metro_commonality"
    msgs += [ai, _tm("hyp_metro_commonality",
                     {"hypothesis_id": "metro_commonality",
                      "status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)                                        # 6) 물러선다
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] == 0.2
    assert ai.tool_calls[0]["args"]["claim_id"] == ""    # 지목할 근거가 없다

    # 각본이 등록 가설을 하나도 빠뜨리지 않았는지 레지스트리와 대조한다 —
    # 하드코딩된 이름 목록만 보면 YAML 에 가설이 늘어도 이 테스트는 초록이다
    from domain import registry
    called = {c["name"] for m in msgs if getattr(m, "tool_calls", None)
              for c in m.tool_calls}
    assert {f"hyp_{s['id']}" for s in registry.load_hypotheses()} <= called


def test_scripted_uses_ppid_claim_when_eqp_ch_is_silent():
    """PPID 로 갈리면 그 claim_id 를 지목한다 — 폴백이 장식이 아니라 경로다."""
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]
    msgs += [llm.analyze_step(msgs), _tm("hyp_eqp_ch_commonality",
                                         {"hypothesis_id": "eqp_ch_commonality",
                                          "status": "no_signal", "candidates": []})]
    ai = llm.analyze_step(msgs)
    msgs += [ai, _tm("hyp_ppid_commonality", {"hypothesis_id": "ppid_commonality",
                                              "status": "ok", "candidates": [
        {"level": "ppid", "key": "PPID_X", "value": ["CC002000", "PPID_X"],
         "claim_id": "ppid_commonality:ppid:CC002000:PPID_X", "step_seq": "CC002000",
         "score": 1.0, "target_pass": 3, "passes": True}]})]

    ai = llm.analyze_step(msgs)                          # 2단 센서로 넘어간다
    assert ai.tool_calls[0]["name"] == "compare_sensor_distribution"
    assert ai.tool_calls[0]["args"]["step_seq"] == "CC002000"


def test_scripted_keeps_claim_id_when_stage2_fails():
    """2단이 근거를 못 내도 1단 claim 은 실재한다 - 지목을 지우면 게이트가 근거를 못 찾는다."""
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]
    msgs += [llm.analyze_step(msgs), _tm("hyp_eqp_ch_commonality", {
        "hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"level": "chamber", "key": "ETCH9_B", "value": ["Etch", "ETCH9_B"],
             "claim_id": "eqp_ch_commonality:chamber:Etch:ETCH9_B",
             "step_seq": "Etch", "score": 1.0, "target_pass": 3, "passes": True}]})]
    # 챔버가 갈렸어도 레시피 축을 함께 돌린다 (교락 확인) - 그다음이 2단이다
    msgs += [llm.analyze_step(msgs), _tm("hyp_ppid_commonality", {
        "hypothesis_id": "ppid_commonality", "status": "no_signal", "candidates": []})]
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "compare_sensor_distribution"
    msgs += [ai, _tm("compare_sensor_distribution",
                     {"status": "fetch_failed", "candidates": []})]

    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "finalize"
    assert ai.tool_calls[0]["args"]["confidence"] == 0.5
    assert ai.tool_calls[0]["args"]["claim_id"] == "eqp_ch_commonality:chamber:Etch:ETCH9_B"


def test_generate_report_renders_inconclusive_status():
    # 한계 도달(inconclusive) 종료: 결론을 "미확정 + 유력 가설(후보)" 톤으로 표기
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        target_wafers=["W2406_02"], target_source="manual",
        target_group=TARGET, status_summary="s",
        findings=[], hypothesis="ETCH-9 rf_power 이상 추정", confidence=0.5,
        finalize_status="inconclusive",
    )
    assert "미확정" in report
    assert "한계" in report          # 왜 미확정인지 (루프 한계 도달)
    assert "ETCH-9" in report        # 유력 가설은 후보로 남긴다


def test_generate_report_no_longer_renders_evidence_line_itself():
    """[근거] 줄은 이제 mock 이 아니라 report_node 가 코드로 붙인다 (Task 8 최종 검토).

    claims 를 넘겨도 mock 의 generate_report 자체는 [근거] 를 내지 않아야 한다 —
    안 그러면 report_node 가 붙이는 줄과 겹쳐 두 번 나온다.
    같은 계약(claim_id·분리 점수·3/3·0/6 단언)은 `tests/test_graph_nodes.py` 의
    `test_report_node_appends_evidence_line_for_approved_claim` 로 옮겼다.
    """
    llm = ScriptedMockLLMClient()
    report = llm.generate_report(
        target_wafers=["W2406_02"], target_source="manual", target_group=TARGET,
        status_summary="s", findings=[], hypothesis="원인은 그 챔버다", confidence=0.9,
        finalize_status="confirmed",
        claims=[{"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "score": 1.0,
                 "target_pass": 3, "target_total": 3,
                 "control_pass": 0, "control_total": 6}],
    )
    assert "[근거]" not in report


# ---------------------------------------------------------------- 운영 클라이언트 계약
# mock 만 테스트하면 사내 경로(LLM_MODE=openai)는 **한 줄도 실행되지 않는다.**
# 실제로 generate_report 의 인자 이름만 바꾸고 본문을 안 고쳐 NameError 가 났는데,
# 297개 테스트가 전부 통과했다. 리포트는 report_node 가 예외를 삼켜 stub 으로
# 대체하므로 사내에서는 **조용히 산문 리포트가 사라질** 뿐이었다.

class _CapturingLLM:
    """사내 서빙 대역. 프롬프트만 받아 둔다."""

    def __init__(self):
        self.seen = None
        self.seen_sys = None

    def invoke(self, messages):
        self.seen = messages[-1].content
        # 시스템 메시지도 잡는다. 산문 톤을 실제로 바꾸는 지시는 여기 있는데
        # user 쪽만 보던 탓에 sys 프롬프트가 통째로 커버리지 0 이었다.
        self.seen_sys = messages[0].content

        class _Resp:
            content = "산문 리포트"
        return _Resp()


def _openai_client():
    from llm.client import OpenAILLMClient

    client = OpenAILLMClient.__new__(OpenAILLMClient)   # 연결 없이 메서드만 시험
    client.llm = _CapturingLLM()
    return client


def test_operational_client_renders_a_report_without_raising():
    """운영 클라이언트의 generate_report 가 실제로 돌아야 한다.

    report_node 가 예외를 삼키므로 여기서 안 잡으면 사내에서만 조용히 깨진다.
    """
    client = _openai_client()
    report = client.generate_report(
        target_wafers=["W2406_02"], target_source="manual", target_group=["W2406_02"],
        status_summary="요약", findings=[], hypothesis="h", confidence=0.9,
        finalize_status="confirmed",
        claims=[{"claim_id": "a", "rank": 1}, {"claim_id": "b", "rank": 1}])
    assert report == "산문 리포트"


def test_operational_client_passes_every_claim_to_the_prompt():
    """근거를 **전부** 프롬프트에 넣어야 한다 - 하나만 넣으면 다축이 무의미해진다."""
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.9,
        finalize_status="confirmed",
        claims=[{"claim_id": "chamber-a", "rank": 1}, {"claim_id": "ppid-b", "rank": 1}])
    prompt = client.llm.seen
    assert "chamber-a" in prompt and "ppid-b" in prompt
    assert "근거 2건" in prompt
    # 하나만 고르지 말라는 지시가 함께 가야 한다
    assert "전부 서술" in prompt


def test_operational_client_puts_coverage_in_the_prompt():
    """부분 커버리지 사실이 산문을 쓰는 LLM 에게 가야 한다.

    안 가면 한 축만 보고 물러선 분석을 두고 "lot 내부 대조로는 원인이 없다" 는
    확정 톤 문장을 쓴다 - 사유가 틀린 보고다. 운영 경로에서만 깨지는 자리라
    여기서 잡지 않으면 사내에서만 조용히 어긋난다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[],
        coverage={"ran": ["hyp_eqp_ch_commonality"],
                  "unrun": ["hyp_metro_commonality"], "no_data": []})
    prompt = client.llm.seen
    assert "hyp_metro_commonality" in prompt
    assert "커버리지" in prompt


def test_operational_client_system_prompt_scopes_a_partial_coverage_conclusion():
    """부분 커버리지 지시는 **시스템 프롬프트**에 있어야 산문 톤이 바뀐다.

    user 쪽에 커버리지 JSON 만 넣고 sys 지시를 지워도 스위트가 통과하던 자리다 -
    운영 클라이언트의 sys 프롬프트를 보는 테스트가 저장소에 한 건도 없었다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[],
        coverage={"ran": ["hyp_eqp_ch_commonality"],
                  "unrun": ["hyp_metro_commonality"], "no_data": []})
    assert "안 본 축" in client.llm.seen_sys


def test_operational_client_does_not_hedge_a_confirmed_conclusion():
    """확정 결론에까지 '돌린 축에 한한다' 는 유보를 달게 하면 안 된다.

    claim_id 조회·순위 1등·순열 p 를 통과한 결론에 강한 유보를 달면 엔지니어가
    근거를 저평가한다. 사실(커버리지 줄)은 코드가 따로 싣는다 - 유보 지시는
    물러선 판정(no_signal·inconclusive)에만 붙는다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="그 챔버다", confidence=0.9,
        finalize_status="confirmed", claims=[{"claim_id": "a", "rank": 1}],
        coverage={"ran": ["hyp_eqp_ch_commonality"],
                  "unrun": ["hyp_metro_commonality"], "no_data": []})
    assert "돌린 축에 한한" not in client.llm.seen
    assert "돌린 축에 한한" not in client.llm.seen_sys


def test_mock_no_signal_conclusion_does_not_claim_full_coverage():
    """mock 의 '신호 없음' 결론이 안 본 축까지 없다고 단정하면 안 된다.

    옛 문구("lot 내부 대조로는 타깃만 거친 설비/챔버/PPID 가 없다")는 전축을 돌린
    전제에서만 참이다. 전축 실행이 전제 조건에서 빠졌으므로 부분 커버리지로 끝나는
    분석이 정상이 됐고, 그 문구는 거짓 단정이 된다.
    """
    from llm.client import ScriptedMockLLMClient

    report = ScriptedMockLLMClient().generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[])
    assert "설비/챔버/PPID 가 없다" not in report
    assert "대조한 축에서는" in report


def test_operational_client_works_without_claims():
    """근거가 없는 판정(no_signal 등)에서도 돌아야 한다."""
    client = _openai_client()
    assert client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[]) == "산문 리포트"


def test_sensor_no_signal_is_not_treated_like_a_missing_sensor():
    """"봤는데 안 갈렸다" 와 "못 봤다" 를 구분한다 - 안 하면 라이브락이다.

    둘 다 0.5 로 물러서면 게이트가 반드시 반려하는데(< CONFIDENCE_THRESHOLD) 이
    스크립트에는 더 시도할 것이 없어 **같은 finalize 를 루프 한계까지 되풀이한다.**
    확정될 분석이 inconclusive 로 끝나고 바퀴 두세 개가 버려진다.

    센서가 안 갈렸다는 것은 관측된 사실이지 근거의 부재가 아니다. 1단 근거로
    판단하되 2단이 무엇을 말했는지를 결론에 남긴다. `fetch_failed`(못 봤다)는
    기존 계약대로 확정하지 않는다 - tests/test_e2e.py 가 그쪽을 지킨다.
    """
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]
    msgs += [llm.analyze_step(msgs), _tm("hyp_eqp_ch_commonality", {
        "hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"level": "chamber", "key": "ETCH9_B", "value": ["Etch", "ETCH9_B"],
             "claim_id": "eqp_ch_commonality:chamber:Etch:ETCH9_B",
             "step_seq": "Etch", "score": 1.0, "target_pass": 3, "passes": True}]})]
    msgs += [llm.analyze_step(msgs), _tm("hyp_ppid_commonality", {
        "hypothesis_id": "ppid_commonality", "status": "no_signal", "candidates": []})]
    msgs += [llm.analyze_step(msgs), _tm("compare_sensor_distribution",
                                         {"status": "no_signal", "candidates": []})]

    ai = llm.analyze_step(msgs)
    args = ai.tool_calls[0]["args"]
    assert ai.tool_calls[0]["name"] == "finalize"
    assert args["confidence"] >= 0.8          # 게이트가 받을 수 있어야 반복이 멈춘다
    assert args["claim_id"] == "eqp_ch_commonality:chamber:Etch:ETCH9_B"
    # 2단이 무엇을 말했는지가 결론에 남는다 (조용히 생략하지 않는다)
    assert "가르지 못했다" in args["hypothesis"]

    # 같은 상태를 다시 물어도 같은 답이다 - 반복이 아니라 종료다
    assert llm.analyze_step(msgs).tool_calls[0]["args"] == args


def test_operational_client_system_prompt_disowns_superseded_runs():
    """대체된 실행을 근거로 인용하지 말라는 지시는 **시스템 프롬프트**에 있어야 한다.

    report_node 가 findings 에 표시를 붙여도 지시가 없으면 LLM 은 그 키를 모른다.
    같은 프롬프트가 findings 의 수치를 "그대로 인용하라" 고 지시하고 있으므로,
    표시는 무시되고 게이트가 버린 통과 후보(passes True)가 그대로 근거로 나간다 -
    운영 경로에서만 깨지는 자리라 여기서 잡지 않으면 사내에서만 조용히 어긋난다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[],
        findings=[{"loop": 2, "tool": "hyp_eqp_ch_commonality", "superseded": True,
                   "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok",
                              "candidates": [{"claim_id": "c", "passes": True}]}}])
    assert "superseded" in client.llm.seen_sys


def test_operational_client_puts_the_superseded_flag_in_the_user_prompt():
    """sys 가 읽으라고 지시하는 키가 user 쪽에 실제로 실려야 한다.

    sys 프롬프트만 보는 테스트로는 "지시는 있는데 그 키가 안 간다" 는 엇갈림이
    안 잡힌다 - 이 저장소에서 두 렌더링이 엇갈리는 결함이 반복해서 나왔다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[],
        findings=[{"loop": 2, "tool": "hyp_eqp_ch_commonality", "superseded": True,
                   "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok",
                              "candidates": [{"claim_id": "c", "passes": True}]}}])
    assert "superseded" in client.llm.seen
