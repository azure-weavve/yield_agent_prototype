"""적대적 더미 케이스 — 더미가 착해서 안 드러나던 것들.

2026-07-25 더미 우선 개발 결정의 안전장치. 더미 위에서 Stage 2~5 를 만드는 동안
"green 이 실력인지 데이터가 착한 건지" 를 구분해 준다. 각 케이스는 평가셋 항목이기도
하므로, 실데이터 전환(Stage 5.5) 때 같은 판정이 유지되는지 다시 본다.

케이스 5(대조군 부족)는 LOT2407 로 이미 존재하고 tests/test_grouping.py
::test_control_insufficient_reported_honestly 가 지킨다 — 여기서 중복하지 않는다.
"""

import ya_config
from langchain_core.messages import AIMessage

from data.generate_dummy import (ADV_COUNTEREX_LOT, ADV_DECOY_LOT, ADV_MISSING_LOT,
                                 ADV_MISSING_WAFER, ADV_NOSIGNAL_LOT, adv_group)
from domain import engine, registry
from tools import commonality as cm


def _run(lot):
    t, c = adv_group(lot)
    return cm.find_commonality(t, c)


def test_case1_counterexample_lowers_score_below_one():
    """반례(원인 챔버를 거쳤는데 정상인 대조군 wafer)가 있으면 score 가 1.0 미만이어야 한다.

    지금까지 더미는 원인 챔버가 불량군 전용 1:1 이라 score 가 항상 1.0 이었다.
    임계 경계에서 판정이 흔들리는지를 볼 수 없었다.
    """
    res = _run(ADV_COUNTEREX_LOT)
    top = res["candidates"][0]
    assert top["key"] == "ETCH1_B"
    assert top["control_pass"] == 1              # 반례 1장
    assert top["score"] < 1.0
    assert top["score"] == 0.8                   # 4/4 - 1/5
    # 설비 레벨(ETCH1)은 양쪽이 같은 설비라 롤업 점수 0 → 후보에서 빠진다
    assert [x["key"] for x in res["candidates"]] == ["ETCH1_B"]


def test_case2_decoy_does_not_outrank_the_real_cause():
    """진짜(1.0) 옆에 근접 미끼(0.75)를 놔도 순위가 뒤집히지 않아야 한다."""
    res = _run(ADV_DECOY_LOT)
    assert res["candidates"][0]["key"] == "ETCH2_B"
    assert res["candidates"][0]["score"] == 1.0
    decoy = [x for x in res["candidates"] if x["key"] == "PHOT2_X"]
    assert decoy, "미끼 후보가 심기지 않았다"
    assert 0.7 <= decoy[0]["score"] <= 0.85


def test_case2_decoy_passes_the_discriminator_but_the_gate_rejects_it():
    """미끼도 passes=True 다 - 거르는 것은 판별선이 아니라 **게이트의 최고 점수 규칙**이다.

    engine 의 판별선은 (score >= COMMONALITY_PASS_MIN_SCORE, target_pass >= MIN_TARGET)
    뿐이라 0.75 짜리 미끼도 통과한다. 예전에는 LLM 이 미끼를 골라 결론에 쓰면 게이트가
    승인했다. 지금은 같은 도구 안에서 최고 점수가 아니면 반려한다.
    """
    from graph import nodes

    spec = next(s for s in registry.load_hypotheses() if s["id"] == "eqp_ch_commonality")
    t, c = adv_group(ADV_DECOY_LOT)
    res = engine.evaluate(spec, t, c)
    cands = {x["key"]: x for x in res["candidates"]}
    assert cands["ETCH2_B"]["passes"]
    assert cands["PHOT2_X"]["passes"], "판별선은 여전히 미끼를 통과시킨다"

    finding = {"loop": 1, "tool": "hyp_eqp_ch_commonality", "args": {},
               "result": res, "thought": "대조"}
    ai = AIMessage(content="종료 제안", tool_calls=[{"name": "finalize", "args": {
        "claim_id": cands["PHOT2_X"]["claim_id"],
        "hypothesis": "미끼가 원인", "confidence": 0.9}, "id": "call_f"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [finding]})
    assert "finalize_accepted" not in out
    assert cands["ETCH2_B"]["claim_id"] in out["messages"][0].content

    # 진짜 원인을 지목하면 승인된다 - 게이트가 과하게 조여진 것이 아님을 함께 고정한다
    ai_ok = AIMessage(content="종료 제안", tool_calls=[{"name": "finalize", "args": {
        "claim_id": cands["ETCH2_B"]["claim_id"],
        "hypothesis": "ETCH2_B 편중이 원인", "confidence": 0.9}, "id": "call_f"}])
    ok = nodes.tools_node({"messages": [ai_ok], "loop_count": 3, "findings": [finding]})
    assert ok["finalize_status"] == "confirmed"


def test_case3_missing_history_is_separated_and_does_not_pollute_denominator():
    """이력 결측 wafer 는 분모에서 빠지고 missing_history 로 따로 보고돼야 한다."""
    res = _run(ADV_MISSING_LOT)
    assert ADV_MISSING_WAFER in res["meta"]["missing_history"]
    assert res["n_target"] == 3                  # 이력 있는 타깃만
    real = [x for x in res["candidates"] if x["key"] == "ETCH3_B"][0]
    assert real["target_pass"] == 3 and real["target_total"] == 3


def test_case3_null_chamber_does_not_create_a_fake_key():
    """ch_id 가 NULL 인 행에서 챔버 레벨이 조용히 빠져야 한다 (가짜 키 금지)."""
    res = _run(ADV_MISSING_LOT)
    keys = [x["key"] for x in res["candidates"]]
    assert all(k and "None" not in k for k in keys)
    # NULL 인 두 장은 설비 레벨에만 잡히므로 챔버 후보의 대조군 통과 수가 부풀지 않는다
    real = [x for x in res["candidates"] if x["key"] == "ETCH3_B"][0]
    assert real["control_pass"] == 0


def test_case4_cause_spanning_whole_root_lot_yields_no_signal():
    """원인이 root_lot 전원에 걸리면 후보가 없어야 한다 ('모른다' 가 정답).

    lot 내부 대조로는 구조적으로 안 보이는 케이스. 후보를 억지로 내면 허위 확정이다.
    이 계획에서 가장 중요한 케이스 — 물러설 줄 아는지를 시험한다.
    """
    res = _run(ADV_NOSIGNAL_LOT)
    assert res["status"] == "no_signal"
    assert res["candidates"] == []
    assert "lot 내부 대조" in res["note"]


def test_case4_end_to_end_reports_no_signal_not_loop_exhaustion():
    """no_signal 케이스가 그래프 전체를 지나도 **확정 결론이 되면 안 된다**.

    그리고 사유가 정확해야 한다 - "루프를 다 썼다"(inconclusive)와 "lot 내부
    대조로는 신호가 없다"(no_signal)는 사람이 할 조치가 다르다. 전자는 재시도,
    후자는 대조군을 lot 밖으로 넓히는 일이다.
    """
    from graph.build import build_graph

    targets, _ = adv_group(ADV_NOSIGNAL_LOT)
    state = build_graph().invoke({"target_wafers": [targets[0]], "target_source": "manual"})

    assert state["report"]
    assert state["finalize_status"] == "no_signal"
    assert "신호 없음" in state["report"]
    assert "lot 밖 대조군" in state["report"]
    # 도구가 1회차에 아는 사실이므로 루프를 다 태우지 않는다 (숫자가 아니라 의도)
    assert state["loop_count"] < ya_config.MAX_LOOPS
    # 게이트가 이 가설을 승인한 적이 없어야 한다
    gate = [f["result"] for f in state["findings"] if f["tool"] == "finalize"]
    assert not any("승인" in r for r in gate)
    # 등록 가설을 둘 다 돌린 뒤에 판정했다
    tools_used = [f["tool"] for f in state["findings"]]
    assert "hyp_eqp_ch_commonality" in tools_used and "hyp_ppid_commonality" in tools_used


def test_case1_counterexample_still_reaches_confirmed_end_to_end():
    """반례가 있어도 판별선을 넘으면 확정한다 - 게이트를 조였다고 과민해지면 안 된다.

    score 0.8 은 '원인 챔버를 거쳤는데 정상인 대조군 wafer 가 1장 있다' 는 뜻이다.
    현실 데이터에서 흔한 모양이므로 여기서 물러서면 아무것도 확정하지 못한다.
    """
    from graph.build import build_graph

    targets, _ = adv_group(ADV_COUNTEREX_LOT)
    state = build_graph().invoke({"target_wafers": targets, "target_source": "manual"})
    assert state["finalize_status"] == "confirmed"
    assert state["final_claims"][0]["key"] == "ETCH1_B"
    assert state["final_claims"][0]["control_pass"] == 1    # 반례가 근거에 그대로 남는다


def test_case3_missing_history_still_reaches_confirmed_end_to_end():
    """이력 결측 wafer 가 섞여도 판정이 흔들리지 않는다."""
    from graph.build import build_graph

    targets, _ = adv_group(ADV_MISSING_LOT)
    state = build_graph().invoke({"target_wafers": targets, "target_source": "manual"})
    assert state["finalize_status"] == "confirmed"
    assert state["final_claims"][0]["key"] == "ETCH3_B"
