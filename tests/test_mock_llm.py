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


def test_scripted_never_picks_a_sensor_even_when_it_outranks_the_first_stage():
    """센서가 순위 1등이어도 각본은 **지목 가능한 것**을 낸다.

    1단이 비통계 등급(참조 회차 0 - `p_min_possible` 이 없다)이면 `dominates` 가
    어느 쪽도 못 이겨 센서와 같은 층에 서고, 표시 순서는 점수순이라 효과크기가 큰
    센서가 앞에 선다. `_top_ranked` 는 `ranked_groups()`(근거로 실을 것 전부)를
    그대로 받으므로 그 센서를 돌려주는데, 각본은 그 값을 finalize 의 claim_id 로
    쓴다 - 게이트가 반려하고 각본에는 그 반려에 반응할 분기가 없어 같은 호출을
    루프 한계까지 되풀이한다(확정될 분석이 inconclusive 로 끝난다).

    문장도 거짓이 된다: 효과크기가 "분리 점수" 로, 투영이 채운 통과 카운트 0 이
    "불량군 0장 전용" 으로 인쇄된다 - 이 브랜치가 근거 줄에서 없앤 가짜 2x2 가
    `final_hypothesis` 산문으로 새는 것이라 렌더러 수정으로는 안 막힌다.
    """
    llm = ScriptedMockLLMClient()
    msgs = [HUMAN]
    msgs += [llm.analyze_step(msgs), _tm("finalize", "반려")]
    msgs += [llm.analyze_step(msgs), _tm("hyp_eqp_ch_commonality", {
        "hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            # 순열을 못 돌린 후보다 (p_permutation 없음) - 소표본에서 흔하다
            {"level": "chamber", "key": "ETCH9_B", "value": ["Etch", "ETCH9_B"],
             "claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
             "step_seq": "CC002000", "score": 1.0, "target_pass": 3,
             "target_total": 3, "control_pass": 0, "control_total": 3,
             "passes": True}]})]
    msgs += [llm.analyze_step(msgs), _tm("hyp_ppid_commonality", {
        "hypothesis_id": "ppid_commonality", "status": "no_signal", "candidates": []})]
    ai = llm.analyze_step(msgs)
    assert ai.tool_calls[0]["name"] == "compare_sensor_distribution"
    msgs += [ai, _tm("compare_sensor_distribution", {
        "kind": "sensor", "status": "ok", "candidates": [
            # 효과크기가 1단 분리 점수(1.0)보다 크다 - 표시 순서에서 앞에 선다
            {"claim_id": "sensor:CC002000:RF_1", "sensor_name": "RF_1",
             "effect_size": 14.99, "passes": True, "reject_reason": None,
             "target_mean": 812.4, "control_mean": 799.1,
             "target_std": 3.0, "control_std": 2.8,
             "n_target": 12, "n_control": 40}]})]

    args = llm.analyze_step(msgs).tool_calls[0]["args"]
    assert args["claim_id"] == "eqp_ch_commonality:chamber:CC002000:ETCH9_B"
    assert "불량군 0장 전용" not in args["hypothesis"]   # 센서에는 2x2 가 없다


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
    # weak_signal 에서는 이 목록의 전부가 잔차일 수 있어 "근거" 로 고정해 부르면
    # 안 된다(리뷰 지적) - 그래서 "항목" 으로 부른다.
    assert "항목 2건" in prompt
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


def test_operational_client_scopes_a_partial_coverage_conclusion_for_weak_signal_too():
    """weak_signal 도 커버리지 고백 지시를 받아야 한다.

    (2a) 는 loop 2 에도 열리도록 설계됐다(설계 §13) - `weak_signal` 로 끝나는 분석은
    등록 축 4개 중 3개가 안 돌린 채로 끝나는 것이 흔하다. 그런데 이 지시 문장은
    `no_signal` 이거나 `inconclusive` 일 때만 걸려 있었다 - 가장 필요한 판정에
    커버리지 고백을 안 시키는 구멍이었다.

    'weak_signal' 이라는 문자열만 세면 공허하다 - 시스템 프롬프트에는 이미
    "판정이 weak_signal 이면 '약한 신호'로 서술하라" 문장이 따로 있다
    (grep 으로 이 사실을 먼저 확인했다: 커버리지 고백 문장과 이어붙인 새 문자열
    "weak_signal 이거나 no_signal 이거나 inconclusive" 는 고치기 전에는 파일
    어디에도 없었다). 그래서 **이어붙은 문자열**을 찾는다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="weak_signal", claims=[],
        coverage={"ran": ["hyp_eqp_ch_commonality"],
                  "unrun": ["hyp_metro_commonality"], "no_data": []})
    assert "weak_signal 이거나 no_signal 이거나 inconclusive" in client.llm.seen_sys


def test_operational_client_tells_the_report_what_a_sensor_claim_is():
    """리포트 LLM 은 센서 근거를 **처음** 받는다 (이 브랜치의 투영으로 생겼다).

    센서 항목에는 2x2 도 순열 p 도 없고 효과크기와 두 분포뿐인데, 프롬프트는
    "근거가 여러 건이면 전부 서술하라" 만 말한다. 무엇인지 안 알려주면 1단 근거와
    같은 무게로 원인을 단정하는 문장이 나간다 - 다중비교 보정을 안 한 후보를
    확정 결론의 주어로 쓰는 것이다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.9,
        finalize_status="confirmed", coverage=None,
        claims=[{"claim_id": "sensor:CC002000:TEMP_1", "kind": "sensor",
                 "score": 2.31, "rank": 1}])
    # claims JSON 에 "sensor:..." 가 이미 있으므로 문자열 'sensor' 만 세면 공허하다 -
    # **지시 문장**을 찾는다.
    assert "kind 가 sensor" in client.llm.seen
    assert "확정 결론의 주어로 쓰지 마라" in client.llm.seen


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


def test_operational_client_hedges_a_conclusion_whose_axes_crashed():
    """유보 지시가 `unrun` 하나에만 매달려 있으면 실패 축에서 조용히 꺼진다.

    축이 `unrun` -> `failed` 로 옮겨진 것뿐인데 "결론은 돌린 축에 한한다" 가 사라져,
    4축 중 3축이 DB 장애로 못 돈 분석에서 전축 결론이 유보 없이 나간다. 실패 축을
    '실패한 축' 이라고 부르라는 표기 지시는 결론 범위를 제한하지 않는다.
    """
    coverage = {"ran": ["hyp_metro_commonality"],
                "failed": ["hyp_eqp_ch_commonality", "hyp_ppid_commonality",
                           "hyp_step_passage_commonality"],
                "unrun": [], "no_data": []}
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis=None, confidence=0.2,
        finalize_status="no_signal", claims=[], coverage=coverage)
    # **문장이 붙었는지가 아니라 무엇을 조건으로 다는지를 본다.** 유보 문장은 판정이
    # confirmed 가 아니면 언제나 붙고 조건은 그 안에 글로 적혀 있다 - "돌린 축에 한한"
    # 이 있는지만 보면 unrun 전용으로 되돌려도 초록이다.
    assert "unrun 이나 failed 가 비어 있지 않으면" in client.llm.seen
    # sys 지시도 같이 열려야 산문 톤이 바뀐다 - user 쪽 JSON 만으로는 안 바뀐다.
    assert "도구 실패로 못 돈 축(failed)이 있으면" in client.llm.seen_sys


def _rolled_up_claims():
    return [{"claim_id": "eqp_ch_commonality:chamber:CC001000:PHOT7_B",
             "level": "chamber", "key": "PHOT7_B", "step_seq": "CC001000",
             "score": 0.667, "p_permutation": 0.03, "rank": 1, "tied": False,
             "target_pass": 4, "target_total": 6, "control_pass": 0, "control_total": 6,
             "confounded_with": [],
             "rolled_up_as": [{"claim_id": "eqp_ch_commonality:equipment:CC001000:PHOT7",
                               "level": "equipment", "key": "PHOT7",
                               "resolution": "coarser", "of": "PHOT7_B",
                               "target_pass": 4, "target_total": 6,
                               "control_pass": 0, "control_total": 6}]}]


def test_operational_client_tells_the_report_that_a_roll_up_is_not_a_rival():
    """굵은 해상도(설비)와 세밀한 이름(챔버)은 경합하는 두 근거가 아니다.

    지시가 없으면 LLM 은 confounded_with 지시를 유추 적용해 "설비 PHOT7 인지 챔버
    PHOT7_B 인지 현재 증거로는 구분되지 않는다" 로 쓴다 - 엔지니어가 읽으면 당연한
    소리이고, 진짜 미해결(챔버냐 레시피냐)과 같은 문장이라 조사할 거리가 흐려진다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", hypothesis="h", confidence=0.9,
        finalize_status="confirmed", claims=_rolled_up_claims(), findings=[])
    assert "rolled_up_as" in client.llm.seen_sys
    # 목록에는 **양방향**이 담긴다 - 대표가 굵은 이름일 수도 있다(챔버 분모가 작아
    # 설비 점수가 더 큰 경우). 방향은 항목의 resolution 이 말하고, 그 필드를 읽으라는
    # 지시가 없으면 LLM 은 목록 전체를 "대표보다 굵은 이름" 으로 읽어 되돌린다.
    # 필드 이름만 대는 지시는 값의 뜻을 안 알려 준다 - LLM 은 coarser/finer 를
    # 어느 쪽이 굵은지로 되짚을 길이 없어 방향을 뒤집어 쓴다.
    assert "coarser" in client.llm.seen_sys and "finer" in client.llm.seen_sys


def test_operational_client_repeats_the_roll_up_instruction_beside_the_claims():
    """지시가 sys 에만 있으면 claims JSON 바로 옆의 지시와 어긋난다.

    `rolled_up_as` 라는 키 이름은 claims 를 통째로 실으면 저절로 user 에 들어가므로
    그것만 확인하면 아무것도 못 잡는다. 여기서 잠그는 것은 **지시 문구**다 - 이
    저장소에서 sys 와 user 두 렌더링이 엇갈리는 결함이 반복해서 나왔다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", hypothesis="h", confidence=0.9,
        finalize_status="confirmed", claims=_rolled_up_claims(), findings=[])
    assert "대조군 범위의 한계로 적어라" in client.llm.seen


def test_mock_report_has_a_sentence_for_weak_signal():
    """판정 어휘를 늘리면 mock 결론문도 같이 늘려야 한다 - 안 그러면 새 판정이
    `else` 로 떨어져 LLM 이 쓴 가설이 확정처럼 찍힌다.

    `claims` 에 실제로 passes=False 항목을 실어 보낸다 - report_node 가 넘기는
    실제 호출과 같은 모양이다(잔차가 없으면 이 문장이 안 붙도록 조건이 걸려
    있다, Task 6 fix 1 Part B).
    """
    from llm.client import ScriptedMockLLMClient
    report = ScriptedMockLLMClient().generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="ETCH9_B 편중", confidence=0.3,
        finalize_status="weak_signal",
        claims=[{"claim_id": "a", "passes": False, "rank": 1,
                 "reject_reason": "score below threshold"}])
    assert "약한 신호" in report
    assert "[잔차] 줄" in report


def test_mock_report_has_no_residual_sentence_for_weak_signal_without_residuals():
    """잔차가 실제로 안 실리면 "[잔차] 줄이 그 후보들이다" 를 말하면 안 된다.

    (2a) 는 통계 통과 후보 없이도 열리므로 `claims` 가 전부 `passes: true`(통과한
    2단 센서만)일 수 있다 - 그 상태에서도 무조건 잔차 문장을 붙이면 존재하지 않는
    [잔차] 줄을 가리키는 거짓 문장이 나간다.
    """
    from llm.client import ScriptedMockLLMClient
    report = ScriptedMockLLMClient().generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="weak_signal",
        claims=[{"claim_id": "sensor:CC002000:TEMP_1", "passes": True, "rank": 1}])
    assert "약한 신호" in report
    assert "[잔차] 줄" not in report


def test_operational_prompt_tells_the_report_what_weak_signal_means():
    """운영 리포트 LLM 은 판정 이름만 받는다 - 무엇인지 안 알려주면 잔차를 원인으로
    단정하거나, 반대로 신호 없음으로 뭉갠다. 다음 행동(표본·대조군)까지 적게 한다."""
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="weak_signal", coverage=None, claims=[])
    assert "weak_signal" in client.llm.seen_sys
    assert "'약한 신호'로 서술하라" in client.llm.seen_sys
    assert "타깃/대조군 표본을 넓히기" in client.llm.seen_sys
    # (2a) 는 **통과한 2단 센서가 있는 상태에서도** 열린다(하한은 statistical_passing()
    # = 비센서 통과 claim 뿐이다). 그래서 이 절이 "후보는 나왔으나 판별선을 넘지
    # 못한 것" 이라고 한 갈래만 말하면 그 상태에서 거짓이 되고, 리포트가 [근거] 로
    # 실려 나간 통과 센서를 "아무것도 안 나왔다" 로 뭉갠다.
    assert "2단 센서 근거는 통과했을 수 있으니" in client.llm.seen_sys


def test_operational_prompt_says_a_submitted_hypothesis_may_name_a_weak_candidate():
    """하한이 넓어져 '지목한 제출'도 weak_signal 로 온다.

    그 제출의 hypothesis 는 후보 하나를 원인으로 지목하는 문장이다. 리포트
    작성자가 그것을 그대로 옮기면 판정("확정이 아니다")과 서술("X가 원인")이
    한 리포트 안에서 어긋난다. 기존 절은 **claims 목록**을 단정하지 말라고만
    했지 **제출된 가설 문장**을 어떻게 다루라고는 말하지 않는다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="ETCH9_B 편중이 원인",
        confidence=0.9, finalize_status="weak_signal", coverage=None, claims=[])
    assert ("제출된 가설이 특정 후보를 원인으로 지목하고 있어도"
            in client.llm.seen_sys), client.llm.seen_sys
    assert ("게이트는 그 후보를 원인으로 확정하지 않았다"
            in client.llm.seen_sys), client.llm.seen_sys
    # **판정 가드까지 잠근다.** 이 sys 리터럴은 조건 없는 단일 문자열이라, 가드를
    # 빼도 문장은 그대로 남아 위 두 단언이 초록이다 - 실제로 그렇게 나가 있었고
    # confirmed 판정에서 거짓이었다(9줄 뒤 "확정된 근거를 유보 톤으로 낮추지 마라"
    # 와 충돌). 주변의 조건부 지시는 예외 없이 "판정이 X 면" 접두를 달고 있다.
    assert ("판정이 weak_signal 인데 제출된 가설이"
            in client.llm.seen_sys), client.llm.seen_sys


def test_operational_client_tells_the_report_what_a_residual_claim_is():
    """(2a) 는 잔차를 `passes: false` 로 claims 목록에 실어 보낸다.

    claims 블록은 `confounded_with`·`rolled_up_as`·`kind == sensor` 는 설명하면서
    잔차만 빠지면, weak_signal 리포트에서 코드는 `[잔차 1]` 로 찍는데 그 위 산문은
    같은 항목을 "게이트가 확인한 근거" 로 부를 수 있다 - 판별선을 못 넘은 후보가
    근거로 단정되는 것이다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="weak_signal", coverage=None,
        claims=[{"claim_id": "a", "passes": False, "rank": 1,
                 "reject_reason": "score below threshold"}])
    # claims JSON 에 "passes": false 가 이미 있으므로 문자열 'passes' 만 세면 공허하다 -
    # **지시 문장**을 찾는다.
    assert "판별선을 넘지 못한 잔차다" in client.llm.seen
    assert "아직 갈리지 않은 후보" in client.llm.seen


def test_analyze_prompt_tells_the_llm_to_step_back_on_weak_candidates():
    """게이트가 받아 주지 않는 것을 계속 지목하게 두면 왕복만 남는다.

    반려 문구(`_gate_rejection`)에도 안내가 있지만, 이 저장소는 규칙을 판정과 프롬프트
    양쪽에 적는다 - 한쪽만 있으면 LLM 은 체크리스트를 소화하러 간다.
    """
    from graph import nodes
    assert "판별선을 넘지 못한 후보만" in nodes.ANALYZE_SYSTEM_PROMPT
    assert "잔차" in nodes.ANALYZE_SYSTEM_PROMPT


def test_mock_report_has_a_sentence_for_no_separation():
    """판정 어휘를 늘리면 mock 결론문도 같이 늘려야 한다 - 안 그러면 새 판정이
    else 로 떨어져 LLM 이 쓴 가설이 확정처럼 찍힌다."""
    from llm.client import ScriptedMockLLMClient
    report = ScriptedMockLLMClient().generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="no_separation")
    assert "갈리는 항목 없음" in report
    assert "lot 밖 대조군" in report


def test_operational_prompt_tells_the_report_what_no_separation_means():
    """운영 리포트 LLM 은 판정 이름만 받는다 - 무엇인지 안 알려주면 '분석 미수행'
    으로 뭉개거나 반대로 '원인 없음' 으로 단정한다. 둘 다 조치가 틀려진다."""
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="no_separation", claims=[])
    assert "판정이 no_separation 이면" in client.llm.seen_sys
    assert "분석 미수행이 아니다" in client.llm.seen_sys
    assert "다른 관측축" in client.llm.seen_sys


def test_operational_prompt_says_inconclusive_can_carry_residuals():
    """(4)가 잔차를 싣게 됐으므로 inconclusive 도 [잔차] 줄을 받을 수 있다.

    '확정 근거가 없다' 로만 지시하면 LLM 이 실제로 실린 잔차 줄을 근거 없음과
    모순되는 것으로 보고 지우거나, 반대로 근거로 승격시킨다.
    """
    client = _openai_client()
    client.generate_report(
        target_wafers=["W1"], target_source="manual", target_group=["W1"],
        status_summary="s", findings=[], hypothesis="h", confidence=0.3,
        finalize_status="inconclusive", claims=[])
    assert "inconclusive 에도 잔차가 실릴 수 있다" in client.llm.seen_sys


def test_analyze_prompt_knows_the_full_axis_case_is_received_not_rejected():
    """분석 프롬프트가 '잔차마저 없으면 반려된다' 로만 말하면 이제 반만 참이다.

    등록 축을 다 돌린 뒤라면 게이트가 '갈리는 항목 없음' 으로 받는다. 반쪽짜리
    문장을 남겨 두면 LLM 이 물러설 수 있는 자리에서 축을 더 부르며 예산을 태운다.
    """
    from graph import nodes
    assert "갈리는 항목 없음" in nodes.ANALYZE_SYSTEM_PROMPT
