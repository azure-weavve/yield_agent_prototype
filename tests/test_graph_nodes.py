"""노드 단위 검증 — 특히 tools 노드의 finalize 게이트(승인/반려)와 감사 기록."""

import os
import subprocess
import sys

from langchain_core.messages import AIMessage, ToolMessage

import ya_config
from graph import nodes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_importing_nodes_does_not_acquire_the_llm():
    """import 만으로 LLM 구현이 고정되면 안 된다 (미룸 8번).

    모듈 레벨에서 `get_llm()` 을 부르면 `config.LLM_MODE` 를 바꾸거나 테스트에서
    구현을 갈아끼우는 일이 **import 순서**에 좌우된다. 별도 프로세스로 확인하는 이유:
    같은 세션의 다른 테스트가 이미 `_llm` 을 채웠을 수 있다.
    """
    proc = subprocess.run(
        [sys.executable, "-c", "import graph.nodes as n; print(n._llm)"],
        capture_output=True, cwd=ROOT)

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode().strip() == "None"


def _ai_finalize(confidence, hypothesis="Etch ETCH-9 원인", claim_id="eqp_ch_commonality:chamber:Etch:ETCH-9"):
    return AIMessage(
        content="종료 제안",
        tool_calls=[{"name": "finalize",
                     "args": {"claim_id": claim_id, "hypothesis": hypothesis,
                              "confidence": confidence},
                     "id": "call_f"}],
    )


# 이 파일의 후보 픽스처(모듈 상수 + 각 테스트 함수 안)는 실제 도구가 낼 수 있는
# 값만 쓴다. 게이트는 `score` 와 `passes` 만 읽어서 어긋나도 안 죽지만, 픽스처를
# 복사해 쓰는 다음 사람이 실재하지 않는 조합을 근거로 삼게 된다. 두 가지를 맞춘다:
#   score         = target_pass/target_total - control_pass/control_total (commonality 정의)
#   reject_reason = domain/engine.py:17-19 형식 + ya_config 실제 임계
#                   (COMMONALITY_PASS_MIN_SCORE=0.5, COMMONALITY_PASS_MIN_TARGET=2)

# 게이트 증거 검사용(신형): 챔버 가설이 ETCH-9 를 통과 판정한 감사 기록
EVIDENCE_FINDING = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality",
    "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "eqp_ch_commonality",
               "legend": [{"level": "chamber", "columns": ["eqp_id", "ch_id"]}],
               "status": "ok",
               "candidates": [
                   {"claim_id": "eqp_ch_commonality:chamber:Etch:ETCH-9",
                    "value": ["Etch", "ETCH-9"], "passes": True,
                    "level": "chamber", "key": "ETCH-9", "step_seq": "Etch", "score": 1.0,
                    "target_pass": 3, "target_total": 3,
                    "control_pass": 0, "control_total": 3, "reject_reason": None},
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
                   {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                    "value": ["Etch", "ETCH9_B"], "passes": True,
                    "level": "chamber", "key": "ETCH9_B", "step_seq": "CC002000", "score": 1.0,
                    "target_pass": 3, "target_total": 3,
                    "control_pass": 0, "control_total": 3, "reject_reason": None},
                   {"claim_id": "eqp_ch_commonality:chamber:CD004000:PHOTO1_A",
                    "value": ["Photo", "PHOTO1_A"], "passes": False,
                    "level": "chamber", "key": "PHOTO1_A", "step_seq": "CD004000", "score": 0.0,
                    "target_pass": 3, "target_total": 3,
                    "control_pass": 3, "control_total": 3, "reject_reason": "분리 없음"},
               ]},
    "thought": "챔버 편중",
}

# 전축 실행은 더 이상 no_signal 의 전제 조건이 아니다(부분 커버리지로도 물러설 수
# 있고, 무엇을 안 봤는지는 coverage 로 나간다). 그래도 "전부 침묵" 을 겨눈 시험은
# 가설 수만큼 침묵 finding 이 있어야 이름값을 한다 — 가설을 추가하면 여기도 늘려야
# 하고, 안 늘리면 테스트 이름과 달리 부분 커버리지를 시험하게 된다.
PPID_SILENT = {
    "loop": 3, "tool": "hyp_ppid_commonality", "args": {},
    "result": {"hypothesis_id": "ppid_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "2차 legend",
}
EQP_CH_SILENT = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
    "result": {"hypothesis_id": "eqp_ch_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "1차 legend",
}
STEP_PASSAGE_SILENT = {
    "loop": 4, "tool": "hyp_step_passage_commonality", "args": {},
    "result": {"hypothesis_id": "step_passage_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "스텝 통과 여부",
}
METRO_SILENT = {
    "loop": 5, "tool": "hyp_metro_commonality", "args": {},
    "result": {"hypothesis_id": "metro_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "계측 구간",
}
ALL_SILENT = [EQP_CH_SILENT, PPID_SILENT, STEP_PASSAGE_SILENT, METRO_SILENT]

# 2단 센서 finding. 게이트 계약(claim_id/passes)을 갖지만 등록 축이 아니다.
SENSOR_FINDING = {
    "loop": 3, "tool": "compare_sensor_distribution",
    "args": {"step_seq": "CC002000",
             "group_ids": ["W2406_02", "W2406_04", "W2406_06"],
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"kind": "sensor", "status": "ok", "candidates": [
        {"claim_id": "sensor:CC002000:TEMP_1", "sensor_name": "TEMP_1",
         "effect_size": 2.31, "passes": True, "reject_reason": None,
         "target_mean": 812.4, "control_mean": 799.1,
         "target_std": 3.0, "control_std": 2.8,
         "n_target": 12, "n_control": 40}]},
    "thought": "2단으로 좁힌다",
}


def _assert_covers_every_hypothesis(findings):
    """이 findings 가 등록된 hyp_* 를 전부 채웠는지 못박는다.

    옛 계약에서는 `unrun` 이 비어야 no_signal 판정에 도달했고, 픽스처를 안 늘리면
    게이트가 "아직 안 돌린 가설이 있다" 로 먼저 반려해 테스트가 무력화됐다(3번째
    가설 추가 `292b5b8` 때 실제로 두 테스트가 조용히 죽어 있었다). 전축 강제를
    걷어낸 지금은 반려 대신 **부분 커버리지 no_signal** 이 나온다 - 테스트는 통과하고
    이름만 거짓이 되므로, 조용히 어긋나는 방식이 오히려 더 나빠졌다. 그래서 이
    단언은 남는다.
    """
    registered = {n for n in nodes.TOOLS_BY_NAME if n.startswith("hyp_")}
    missing = registered - {f["tool"] for f in findings}
    assert not missing, f"등록 가설 미포함: {sorted(missing)} - 픽스처를 늘려야 한다"


def test_gate_rejects_text_only_claim():
    """claim_id 없이 hypothesis 문자열만으로는 절대 승인되지 않는다.

    옛 게이트는 `any(eq in hypothesis for eq in suspects)` 였다 - 그래서
    "ETCH-9 는 원인이 아니다" 도 토큰이 들어 있다는 이유로 승인됐다.
    """
    ai = _ai_finalize(0.9, hypothesis="Etch ETCH-9 원인", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "반려" in out["messages"][0].content
    assert "eqp_ch_commonality:chamber:Etch:ETCH-9" in out["messages"][0].content   # 지목할 대상을 알려준다


def test_gate_rejects_negation_when_claim_id_is_absent():
    """부정문이라도 게이트는 문장을 읽지 않는다 - 판정은 claim_id 조회로만 한다."""
    ai = _ai_finalize(0.9, hypothesis="ETCH-9 는 원인이 아니다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out


def test_gate_rejects_unknown_claim_id():
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:Etch:CVD-3")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "CVD-3" in out["messages"][0].content


def test_gate_does_not_advertise_failing_candidates_when_the_claim_id_is_unknown():
    """지어낸 claim_id 를 반려할 때 안내하는 대상은 **통과 후보뿐**이다.

    claim_id 미제출 분기는 `passing()` 만 안내하는데 이 분기만 번들 전체를 안내하면,
    LLM 이 그 목록에서 미통과 후보를 골라 다시 제출하고 또 반려당하는 왕복이 생긴다.
    두 분기가 같은 것을 안내해야 한다.
    """
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CC002000:NOPE")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING_NEW]})
    msg = out["messages"][0].content

    assert "finalize_accepted" not in out
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in msg      # 통과 후보는 안내한다
    assert "eqp_ch_commonality:chamber:CD004000:PHOTO1_A" not in msg  # 미통과 후보는 안내하지 않는다


def test_gate_tells_the_next_action_when_the_claim_id_is_unknown_and_nothing_passed():
    """지어낸 claim_id 인데 통과 후보도 0 이면, 목록 대신 **다음 행동**을 안내해야 한다.

    안내 대상을 통과 후보로 좁힌 대가로, 이 상태에서 문구가 "지목할 수 있는 후보가 없다" 로
    끝나면 LLM 이 다음에 할 일이 없어 루프 한계까지 왕복만 하다 inconclusive 로 끝난다.
    같은 상태를 만난 claim_id 미제출 분기는 미실행 가설 도구를 알려준다 - 같아야 한다.
    """
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CC002000:NOPE")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EQP_CH_SILENT]})
    msg = out["messages"][0].content

    assert "finalize_accepted" not in out
    assert "eqp_ch_commonality:chamber:CC002000:NOPE" in msg   # 무엇이 틀렸는지
    assert "hyp_ppid_commonality" in msg                       # 다음에 무엇을 할지
    assert "hyp_step_passage_commonality" in msg


def test_gate_returns_the_tool_reject_reason_for_a_failing_claim():
    """미통과 후보를 지목하면 도구가 낸 reject_reason 을 그대로 돌려준다.

    이 픽스처는 미통과 후보의 점수가 통과 후보보다 낮아, 승인 조건의 `claim.passes`
    검사를 지워도 점수 비교에 걸려 여전히 반려된다 — 즉 **이 테스트가 잠그는 것은
    반려 사유 전달이지 `passes` 검사 자체가 아니다.** 그 검사를 잠그는 것은
    `test_gate_rejects_claim_that_did_not_pass_even_when_score_ties_the_top` 이다.
    """
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CD004000:PHOTO1_A")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING_NEW]})
    assert "finalize_accepted" not in out
    assert "분리 없음" in out["messages"][0].content


def test_gate_rejects_claim_that_did_not_pass_even_when_score_ties_the_top():
    """실패 후보의 점수가 1등과 같거나 높아도 여전히 반려돼야 한다.

    순위 목록은 **통과 후보만** 담으므로 점수 비교만으로는 passes=False 를 걸러내지
    못한다 — 표본 부족(target_pass 미달)처럼 점수는 높은데 판별선을 못 넘는 후보가
    있다. 판별선 통과가 순위보다 먼저 확인돼야 한다.
    """
    near_miss = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 0.8, "target_pass": 4, "target_total": 4,
             "control_pass": 1, "control_total": 5},
            {"claim_id": "eqp_ch_commonality:chamber:CD004000:PHOT2_X", "step_seq": "CD004000",
             "key": "PHOT2_X", "level": "chamber", "passes": False,
             "reject_reason": "타깃 표본 1 < 2",
             "score": 1.0, "target_pass": 1, "target_total": 1,
             "control_pass": 0, "control_total": 5},
        ]},
        "thought": "표본 부족 근접 미끼",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CD004000:PHOT2_X")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [near_miss]})
    assert "finalize_accepted" not in out
    assert "타깃 표본" in out["messages"][0].content


def test_gate_rejects_lower_scored_claim_and_names_the_stronger_one():
    """근접 미끼: 통과했더라도 더 강한 후보가 있으면 승인하지 않는다."""
    decoy = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH2_B", "step_seq": "CC002000",
             "key": "ETCH2_B", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 4, "target_total": 4,
             "control_pass": 0, "control_total": 5},
            {"claim_id": "eqp_ch_commonality:chamber:CD004000:PHOT2_X", "step_seq": "CD004000",
             "key": "PHOT2_X", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 0.8, "target_pass": 4, "target_total": 4,
             "control_pass": 1, "control_total": 5},
        ]},
        "thought": "미끼 포함",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CD004000:PHOT2_X")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [decoy]})
    assert "finalize_accepted" not in out
    assert "eqp_ch_commonality:chamber:CC002000:ETCH2_B" in out["messages"][0].content


def test_gate_cites_the_p_floor_when_it_names_a_stronger_candidate():
    """순위 반려에 **바닥값**을 같이 싣는다 - 없으면 LLM 이 고칠 수가 없다.

    귀무 참조집합을 표본 크기가 같은 회차로 좁히면서 p 의 해상도가 후보마다 달라졌다.
    아래 픽스처가 그 상태다: 완전 분리(점수 1.0)인 ETCH2_B 는 참조 회차가 적어 p
    0.3333 에서 **바닥에 걸려** 멈췄고, 더 약한 PHOT2_X(점수 0.667)는 참조가 많아
    p 0.05 까지 내려간다. 공통 해상도(둘 다 표현할 수 있는 바닥, 0.3333)로 클램프
    하면 둘은 **동점**이다 - 그 동점은 같은 축(hypothesis_id) 안의 분리 점수가
    깨고, 점수가 더 높은 ETCH2_B 가 이긴다. PHOT2_X 를 지목하면 반려당해야 하는데,
    숫자 둘(p·점수)만 인용하면 "참조가 더 적은 쪽에 왜 졌나" 가 설명이 안 되고
    LLM 은 반려를 받아도 무엇을 고쳐야 할지 알 수 없다 - 두 후보의 바닥값을
    함께 인용해야 동점이 해상도 차이 때문이라는 것이 보인다.
    """
    finding = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH2_B", "step_seq": "CC002000",
             "key": "ETCH2_B", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 3,
             "p_permutation": 0.3333, "p_min_possible": 0.3333},
            {"claim_id": "eqp_ch_commonality:chamber:CD004000:PHOT2_X", "step_seq": "CD004000",
             "key": "PHOT2_X", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 0.6667, "target_pass": 3, "target_total": 3,
             "control_pass": 1, "control_total": 3,
             "p_permutation": 0.05, "p_min_possible": 0.05},
        ]},
        "thought": "해상도가 갈린 두 후보",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CD004000:PHOT2_X")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [finding]})

    assert "finalize_accepted" not in out
    content = out["messages"][0].content
    assert "바닥 0.05" in content, "진 후보(PHOT2_X)의 바닥을 안 알려 준다"
    assert "바닥 0.3333" in content, "이긴 후보(ETCH2_B)가 바닥에 걸렸다는 것을 안 알려 준다"


def test_gate_accepts_a_claim_tied_at_the_top_rank():
    """1등이 여럿이면 그중 아무것이나 지목해도 승인한다.

    타깃 전원이 거친 설비를 대조군이 아무도 안 거치면 설비 롤업과 챔버가 같은
    점수·같은 p 가 된다. 동점을 막으면 더 구체적인 챔버 지목이 반려된다.

    이 fixture 의 후보에는 `target_wafers` 가 없어 접히지 않고 두 묶음으로 남는다 -
    도구가 목록을 실어 보내면 같은 wafer 라 한 묶음으로 접힌다(교락). 여기서
    지키는 것은 **동점 1등 중 무엇을 골라도 반려하지 않는다**는 규칙 쪽이다.
    """
    tied = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:equipment:CC002000:ETCH9", "step_seq": "CC002000",
             "key": "ETCH9", "level": "equipment", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 6},
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 6},
        ]},
        "thought": "동점",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CC002000:ETCH9_B")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [tied]})
    assert out["finalize_status"] == "confirmed"


def test_gate_records_the_approved_claims():
    """승인 시 근거 수치가 상태에 남는다 - 리포트가 LLM 문장에 의존하지 않게.

    이제 담기는 것은 dict 하나가 아니라 **접어서 줄 세운 목록**이다. LLM 이 고른
    것만 남기면 다른 축의 근거가 여기서 사라지는데, 그것이 고치려던 결함이다.
    """
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_status"] == "confirmed"
    lead = out["final_claims"][0]
    assert lead["claim_id"] == "eqp_ch_commonality:chamber:Etch:ETCH-9"
    assert lead["score"] == 1.0
    assert (lead["target_pass"], lead["control_pass"]) == (3, 0)
    assert lead["picked_by_llm"] is True        # LLM 이 서술 축으로 지목한 묶음


def test_analyze_prompt_says_axes_do_not_have_to_be_exhausted():
    """게이트만 풀면 LLM 은 관성으로 계속 전축을 돌린다.

    전축 강제를 걷어낸 목적은 예산을 **깊이** 로 돌리는 것이다. 그런데 시스템
    프롬프트는 그 자유를 한 번도 말하지 않는다 - 게이트 반려 문구는 반려당한
    뒤에야 읽히므로, 애초에 반려되지 않는 경로에서는 아무 것도 안 바뀐다.
    """
    prompt = nodes.ANALYZE_SYSTEM_PROMPT
    assert "전부 돌릴 의무는 없다" in prompt


def test_analyze_prompt_says_a_sensor_claim_id_is_not_pickable():
    """게이트가 막는 것과 LLM 이 아는 것은 다르다.

    시스템 프롬프트는 "도구가 발급한 claim_id 를 그대로 옮겨라" 만 말한다. 센서에도
    claim_id 가 실리기 시작했으므로 그 문장은 이제 센서까지 가리키고, 1단이 빈손인
    흔한 경로에서 LLM 은 센서를 지목했다가 반려당한다 - 반려는 한 바퀴를 버린 뒤에야
    읽힌다. 계약은 **미리** 말해야 한다.
    """
    prompt = nodes.ANALYZE_SYSTEM_PROMPT
    assert "2단 센서" in prompt
    assert "지목" in prompt


def test_analyze_prompt_warns_that_naming_a_sensor_over_a_passing_hyp_tool_is_rejected():
    """반려는 한 바퀴를 버린 뒤에야 읽힌다. 계약은 미리 말해야 한다.

    위 테스트가 잠그는 "2단 센서"·"지목" 은 같은 불릿의 **다른 문장**(claim_id 가
    근거 인용용이라는 문장)에도 있는 느슨한 부분 문자열이라, 센서 지목이 통과한
    가설 도구 앞에서는 반려된다는 **사전 경고 문장**을 지워도 안 잡힌다. (2a) 하한이
    "정직한 제출" 로 넓어져도 통과 후보가 있는 상태의 센서 지목은 여전히 (1)에서
    막혀 (5) 반려로 간다 - LLM 이 그걸 미리 알아야 반려를 한 바퀴 버리지 않는다.
    """
    prompt = nodes.ANALYZE_SYSTEM_PROMPT
    assert "지목해도 원인으로 확정되지 않는다" in prompt, prompt
    assert "통과한 가설 도구(hyp_*) 후보가 있는데도 센서를 지목하면 그 이유로 반려된다" in prompt, prompt


def test_analyze_prompt_tells_the_llm_the_two_outcomes_of_naming_a_weak_candidate():
    """물러설 길 안내가 두 상태를 다 말해야 한다 - 조건부로만 참인 문장은 반쪽이 거짓이 된다.

    기존 가드(`test_analyze_prompt_tells_the_llm_to_step_back_on_weak_candidates`)는
    같은 불릿의 다른 곳에 있는 "판별선을 넘지 못한 후보만"·"잔차" 만 보므로, 이
    불릿을 통째로 예전 문구(하한이 `not claim_id` 이던 시절의 것)로 되돌려도 안
    잡힌다. 지금 계약은 두 상태를 가른다: 잔차가 있으면(최신 도구 결과에 실재하는
    이름을 지목한 한) 지목해도 받아 주고, 잔차마저 없으면 반려된다.

    한정절은 **출처**를 말한다 - "지어내지 않았는가" 다. 하한(`_honest_pick`)이
    `bundle.claims` **와** `bundle.dropped_claims` 를 둘 다 보므로, 대체(superseded)된
    앞 실행의 후보를 지목한 제출도 열린다. 그것은 LLM 이 자기 문맥에서 실제로 받은
    이름이라 환각이 아니다. 예전 문구("실재하는 이름")는 번들에 살아 있는 것만
    가리켜, 대체 이름이 받아들여지는 지금은 거짓이다.
    """
    prompt = nodes.ANALYZE_SYSTEM_PROMPT
    assert "네가 도구 결과에서 실제로 받은 이름을 지목한 한" in prompt, prompt
    assert "잔차마저 없는 상태에서 지목하면 반려되고" in prompt, prompt


def test_gate_declares_no_signal_without_running_every_axis():
    """축 하나만 돌리고 물러서도 게이트가 막지 않는다 - 전축 실행은 전제 조건이 아니다.

    옛 계약은 등록된 hyp_* 를 **전부** 돌리기 전에는 no_signal 을 금지했다. 그러면
    신호를 못 찾는 경로(= 이름 없는 이상을 찾는 경로)에서 루프 예산이 체크리스트
    소화에 강제 배정돼 **깊이 탐색이 구조적으로 막힌다** - 3개 시나리오 전부에서
    빈손인 metro 축이 매번 한 바퀴를 먹는 것이 그 증상이었다.
    전축 실행은 이제 전제 조건이 아니라 **리포트에 적는 커버리지 사실**이다.
    """
    ai = _ai_finalize(0.2, hypothesis="분리되는 후보가 없다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "no_signal"


def test_gate_does_not_read_a_fabricated_claim_id_as_stepping_back():
    """지목을 제출한 것은 물러선 것이 아니다 - 지어낸 claim_id 를 no_signal 로 승인하면 안 된다.

    전축 강제가 사라지면서 (2)번 판정선이 훨씬 앞으로 당겨졌다. claim_id 를 보지
    않으면 "확신도 0.9 로 없는 근거를 지목한" 제출이 곧바로 '신호 없음' 승인으로
    빠져나가, 환각이 물러섬으로 둔갑하고 LLM 은 자기가 틀렸다는 것을 배우지 못한다.
    no_signal 은 **claim_id 를 비우고 물러선** 제출에만 열린다.
    """
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CC002000:NOPE")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT]})
    assert "finalize_accepted" not in out


def test_gate_tells_how_to_step_back_only_when_stepping_back_would_work():
    """물러서는 길은 실제로 열려 있을 때만 알려 준다.

    어떤 축이 no_signal 을 냈으면 claim_id 를 비우는 순간 (2)번으로 종료된다 -
    이때는 그 길을 알려 줘야 LLM 이 루프 한계까지 왕복하지 않는다. 반대로 모든 축이
    status ok 인데 판별선만 못 넘은 상태에서 같은 안내를 하면 **거짓말**이다:
    비우고 제출해도 (2)번에 걸리지 않아 같은 반려가 돌아오고, 그대로 라이브락이 된다.
    """
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CC002000:NOPE")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT]})
    assert "claim_id 를 비우" in out["messages"][0].content


# 전축이 조용한데 한 축만 판별선을 못 넘은 후보를 낸 상태. 통과 후보는 0개다.
_WEAK_IN_SILENCE = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
    "result": {"hypothesis_id": "eqp_ch_commonality", "status": "no_signal", "candidates": [
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
         "key": "ETCH9_B", "level": "chamber", "passes": False,
         "reject_reason": "분리 점수 0.4 < 0.5", "score": 0.4,
         "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5},
    ]},
    "thought": "판별선을 못 넘은 후보",
}
_ALL_NO_PAIR = [{
    "loop": 2, "tool": t, "args": {},
    "result": {"hypothesis_id": h, "status": "no_paired_stratum", "candidates": []},
    "thought": "짝 없음",
} for t, h in [("hyp_eqp_ch_commonality", "eqp_ch_commonality"),
               ("hyp_ppid_commonality", "ppid_commonality"),
               ("hyp_step_passage_commonality", "step_passage_commonality"),
               ("hyp_metro_commonality", "metro_commonality")]]


def test_gate_tells_how_to_step_back_when_the_named_claim_missed_the_line():
    """통과 후보가 0개면, 지목한 claim 이 실재하든 아니든 물러설 길을 알려 줘야 한다.

    '판별선 미달' 분기는 `_no_candidate_action` 을 안 거쳐 "통과한 후보를 지목하라"
    만 돌려준다 - 지목할 통과 후보가 **하나도 없는데도**. 그래서 지어낸 claim_id 를
    낸 LLM 은 물러설 길을 안내받고, 실재하는 미통과 claim 을 정직하게 지목한 LLM 은
    막다른 길에 몰려 루프 한계까지 왕복하다 inconclusive 로 끝난다(조치가 다르다:
    재시도 vs lot 밖 대조군).

    `_WEAK_IN_SILENCE` 의 점수(0.4)는 잔차 아랫선(0.25)을 넘으므로 (2b)("갈리는
    항목 없음")는 안 열린다 - "안 갈렸다" 는 점수가 전부 아랫선 미만이어야 참인
    주장인데 이 상태는 그렇지 않다(M4 재리뷰로 확정, 2026-09-10). 이 분기가
    여전히 시험하는 것은 "판별선 미달 후보를 정직하게 지목했는데 통과 후보가
    없을 때" 다.
    """
    findings = [_WEAK_IN_SILENCE, PPID_SILENT, STEP_PASSAGE_SILENT, METRO_SILENT]
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CC002000:ETCH9_B")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": findings})
    assert "finalize_accepted" not in out
    assert "claim_id 를 비우" in out["messages"][0].content


def test_gate_tells_how_to_step_back_when_every_axis_is_uncomputable():
    """(3)번이 열리는 상태에서도 물러설 길을 알려 줘야 한다.

    안내 조건이 `no_signal in statuses` 뿐이라 (3)이 열리는 상태(정의상 NO_DATA
    상태만 있어 no_signal 이 섞일 수 없다)에는 **한 번도 안 붙었다.** 그래서
    no_comparable_data(→ 적재/추출 범위 확인)여야 할 것이 inconclusive(→ 재시도)로
    나간다 - (3)에 하한을 붙이면서 만든 거울상 오보고다.
    """
    _assert_covers_every_hypothesis(_ALL_NO_PAIR)
    ai = _ai_finalize(0.9, claim_id="지어낸_ID")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": _ALL_NO_PAIR})
    assert "finalize_accepted" not in out
    assert "claim_id 를 비우" in out["messages"][0].content


def test_gate_does_not_promise_stepping_back_while_axes_remain_unrun():
    """반대로, 아직 안 돌린 축이 있으면 (3)은 안 열리므로 물러서기를 권하면 안 된다.

    (2)도 안 열린다(no_signal status 가 없다). 여기서 "비우고 제출하라" 고 하면
    같은 반려가 돌아와 라이브락이다 - 안내 조건을 넓히면서 이 경계가 무너지기 쉽다.
    """
    ai = _ai_finalize(0.9, claim_id="지어낸_ID")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [_ALL_NO_PAIR[0]]})
    assert "claim_id 를 비우" not in out["messages"][0].content


def test_report_node_does_not_send_coverage_when_no_axis_ever_ran():
    """커버리지 줄을 소음이라 지운 보고서에는 클라이언트에도 넘기지 않는다.

    코드는 [커버리지] 줄을 억제하면서 같은 값을 프롬프트에는 무조건 넘겨, "이상
    없음"(분석 루프에 들어가지도 않은) 보고서에서 LLM 이 안 본 축 4개를 나열하게
    했다. 두 렌더링이 엇갈리면 안 된다.
    """
    received = {}

    class _RecordingClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            received.update(kwargs)
            return "고정된 산문 리포트"

    original = nodes._llm
    nodes._llm = _RecordingClient()
    try:
        nodes.report_node({"target_wafers": [], "target_source": "auto",
                           "target_group": [], "status_summary": "수율 임계 미만 lot 없음",
                           "findings": [], "finalize_status": "no_anomaly"})
    finally:
        nodes._llm = original
    assert received["coverage"] is None


def test_report_node_names_a_verdict_when_the_gate_never_judged():
    """게이트를 안 거치고 끝나도 판정이 '미상'으로 나가면 안 된다.

    루프 한계 강제 종료와 tool 없는 텍스트 응답은 게이트를 안 탄다. finalize_status
    가 비면 운영 프롬프트의 "확정 결론을 쓰지 마라" 가드가 **하나도** 안 붙어,
    확정 근거 없이 끝난 분석에 LLM 이 확신에 찬 문장을 쓴다.
    """
    out = nodes.report_node({"target_wafers": ["W1"], "target_source": "manual",
                             "target_group": ["W1"], "status_summary": "s",
                             "findings": [EQP_CH_SILENT]})
    assert out["finalize_status"] == "inconclusive"


def test_report_node_keeps_evidence_when_the_gate_never_judged():
    """게이트를 안 거쳐도 판별선을 넘은 근거는 리포트에 남아야 한다.

    근거를 모든 종료 경로에 싣는 계약(`_record_evidence`)은 게이트 **안**에만
    있었다. 게이트를 안 타는 경로에서는 감사 기록에 p 0.03 · 타깃 3/3 인 후보가
    있는데 리포트 근거가 0줄이다 - 가장 도움이 필요한 보고서에서 근거가 사라진다.
    """
    strong = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
             "step_seq": "CC002000", "key": "ETCH9_B", "level": "chamber",
             "passes": True, "reject_reason": None, "score": 1.0,
             "target_pass": 3, "target_total": 3, "control_pass": 0, "control_total": 6,
             "p_permutation": 0.03, "target_wafers": ["W1", "W2", "W3"],
             "control_wafers": ["C1"]},
        ]},
        "thought": "통과 후보",
    }
    out = nodes.report_node({"target_wafers": ["W1"], "target_source": "manual",
                             "target_group": ["W1"], "status_summary": "s",
                             "findings": [strong]})
    assert "[근거 1]" in out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]


def test_report_node_keeps_residuals_when_the_gate_never_judged():
    """게이트를 아예 안 타는 종료(finalize 미호출)에서도 잔차는 남아야 한다.

    이 경로는 **게이트 협조와 무관하다** - LLM 이 finalize 를 안 부르면 여기로
    오므로 프롬프트로는 못 막는다. `[잔차]` 라벨은 항목의 passes 로 갈리므로
    싣기만 하면 옳게 찍힌다.

    산문 결론에도 잔차 안내 문장이 붙어야 한다 - mock 결론문의 그 문장은 어느
    테스트에도 안 잠겨 있었다(`llm/client.py` 의 조건부 두 줄을 통째로 지워도
    전체 스위트가 초록이었다, Task 6 리뷰 I-1). `[잔차]` 줄이 실제로 찍혔는데
    "그 줄이 판별선을 넘지 못한 후보다" 를 말하는 문장이 없으면, 엔지니어가
    [잔차] 줄을 [근거] 줄과 같은 무게로 읽는다.
    """
    out = nodes.report_node({"target_wafers": ["W1"], "target_source": "manual",
                             "target_group": ["W1"], "status_summary": "s",
                             "findings": [EQP_CH_BELOW_LINE]})
    assert out["finalize_status"] == "inconclusive"
    assert "[잔차 1]" in out["report"], out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]
    assert "아래 [잔차] 줄은 판별선을 넘지 못한 후보다" in out["report"], out["report"]


def test_report_node_does_not_mix_residuals_into_a_passing_backstop():
    """게이트 미경유 종료에도 (2a)·(4)와 같은 하한이 걸려야 한다.

    통과 후보가 실재하면 잔차를 더하지 않는다 - 더하면(하한을 지우면) p 가 작은
    잔차가 `ranked_groups` 의 lead 를 뺏을 수 있다(`_evidence_groups` 독스트링).
    이 테스트가 잠그는 것은 그 하한 자체 - "잔차 미혼입" - 이고, 하한이 무너지는
    극단(통과 근거가 `confounded_with` 로 강등돼 묶음 전체가 `[잔차]` 로 찍히는
    것)까지는 이 픽스처(스텝이 달라 안 접힌다)로는 재현하지 않는다. 이 테스트가
    없으면 백스톱 구현이 헬퍼 대신
    `bundle.ranked_groups(bundle.passing() + bundle.residuals())` 를 직접 적어도
    통과해, "네 자리가 같은 규칙을 쓴다" 가 테스트로는 안 잠긴다.
    """
    out = nodes.report_node({"target_wafers": ["W1"], "target_source": "manual",
                             "target_group": ["W1"], "status_summary": "s",
                             "findings": [EQP_CH_PASSING_AND_RESIDUAL]})
    assert "[잔차" not in out["report"], out["report"]
    assert "[근거 1]" in out["report"], out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]


def test_gate_records_which_axes_it_did_not_run():
    """부분 커버리지로 물러설 때 '무엇을 안 봤는지'가 결론과 함께 나간다.

    사유가 틀린 보고를 막는 자리다 - 한 축만 보고 "lot 내부 대조로는 원인을 좁힐 수
    없다" 고 쓰면 실제로는 안 본 축까지 없다고 말하는 것이 된다. 전축 강제를 걷어낸
    대가로 이 사실이 반드시 따라 나가야 한다.
    """
    ai = _ai_finalize(0.2, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT]})
    coverage = out["coverage"]
    assert coverage["ran"] == ["hyp_eqp_ch_commonality"]
    assert "hyp_metro_commonality" in coverage["unrun"]
    # 게이트가 LLM 에게 돌려주는 문장에도 남는다 - 리포트에만 있으면 LLM 은 자기가
    # 부분만 봤다는 것을 모른 채 확정 톤으로 서술한다.
    assert "hyp_metro_commonality" in out["messages"][0].content


def test_gate_still_needs_one_hypothesis_result_before_no_signal():
    """축을 하나도 안 돌리고 '신호 없음' 을 선언할 수는 없다.

    전축 강제를 걷어내도 이 하한은 남는다 - 근거가 될 결과가 0건이면 no_signal 은
    관측이 아니라 추측이다.
    """
    ai = _ai_finalize(0.2, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": []})
    assert "finalize_accepted" not in out


def test_gate_records_coverage_on_an_approved_exit():
    """커버리지는 no_signal 전용이 아니다 - 승인된 결론도 어디까지 봤는지 함께 나간다."""
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:Etch:ETCH-9")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_status"] == "confirmed"
    assert out["coverage"]["ran"] == ["hyp_eqp_ch_commonality"]
    assert "hyp_metro_commonality" in out["coverage"]["unrun"]


def test_gate_reports_uncomputable_axes_as_coverage_holes():
    """돌았지만 계산이 성립하지 않은 축은 '봤다' 로 세면 안 된다.

    metro 축은 계측 짝이 없으면 no_paired_stratum 으로 끝난다 - 호출은 됐지만
    대조한 것은 없다. 이것을 ran 으로만 세면 커버리지가 실제보다 넓어 보인다.
    """
    metro_no_pair = {
        "loop": 3, "tool": "hyp_metro_commonality", "args": {},
        "result": {"hypothesis_id": "metro_commonality",
                   "status": "no_paired_stratum", "candidates": []},
        "thought": "계측 짝 없음",
    }
    ai = _ai_finalize(0.2, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT, metro_no_pair]})
    assert out["coverage"]["no_data"] == ["hyp_metro_commonality"]


def test_coverage_phrase_does_not_count_uncomputable_axes_as_compared():
    """헤드라인 숫자가 커버리지를 과대하게 세면 안 된다.

    `ran` 은 계산이 성립하지 않은 축도 포함한다. 그대로 세면 같은 줄이 "2개 대조"
    라고 해 놓고 바로 뒤에서 그중 하나는 계산이 안 됐다고 말한다 - 운영 프롬프트에는
    "no_data 는 본 것으로 세면 안 된다" 는 교정이 있는데 코드가 붙이는 줄에는 없어
    두 렌더링이 엇갈렸다.
    """
    line = nodes._coverage_phrase({"ran": ["hyp_a", "hyp_b"],
                                   "no_data": ["hyp_b"], "unrun": ["hyp_c"]})
    assert "2개 대조" in line
    assert "그중 1개는 계산 불가" in line
    assert "hyp_b" in line          # 어느 축인지도 남긴다


def test_gate_does_not_suggest_one_more_axis_when_none_have_run():
    """아무 축도 안 돌린 loop 1 에서 "하나를 **더** 보거나" 는 사실과 안 맞는다.

    2단 센서도 `step_seq` 를 요구하는데 그 값을 낼 근거가 아직 없다. 전축 강제를
    걷어내면서 안내를 선택지로 바꿨는데, 그 문구가 축 0개 상태에까지 그대로 나갔다.
    """
    ai = _ai_finalize(0.6, hypothesis="아직 근거가 없다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": []})
    msg = out["messages"][0].content
    assert "하나를 더" not in msg
    assert "2단" not in msg
    assert "hyp_eqp_ch_commonality" in msg      # 무엇부터 부를지는 알려 준다


def test_gate_offers_narrowing_instead_of_ordering_the_unrun_axes():
    """반려 안내가 '먼저 호출하라'(강제)에서 선택지로 바뀐다.

    규칙은 판정과 안내 **두 곳**에 쓰여 있었다. 판정만 풀어 놓고 안내에 명령문을
    남겨 두면 LLM 은 여전히 체크리스트를 소화하러 간다.
    """
    weak = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            # 점수는 아랫선(RESIDUAL_MIN_SCORE) **아래**여야 한다. 0.4 로 올리면 (2a)가
            # 열려 물러설 길이 실제로 생기고, 이 테스트가 잠그려는 '길이 없다' 상태가
            # 아니게 된다.
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": False,
             "reject_reason": "분리 점수 0.2 < 0.5", "score": 0.2,
             "target_pass": 4, "target_total": 4, "control_pass": 4, "control_total": 5},
        ]},
        "thought": "판별선을 못 넘은 후보",
    }
    ai = _ai_finalize(0.2, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": [weak]})
    msg = out["messages"][0].content
    assert "먼저 호출하라" not in msg
    assert "hyp_metro_commonality" in msg        # 남은 축은 그대로 알려 준다
    assert "2단" in msg                          # 더 좁히는 길도 함께 준다
    # **only 쪽 단언.** 이 상태(모든 축 status ok)에서는 claim_id 를 비우고 제출해도
    # (2)번이 안 열려 같은 반려가 돌아온다 - 물러서기를 권하면 라이브락을 처방하는
    # 것이다. 이 단언이 없으면 조건을 지우고 무조건 붙여도 스위트가 통과한다.
    assert "claim_id 를 비우" not in msg


def test_gate_declares_no_signal_after_all_hypotheses_are_silent():
    """등록 가설을 다 돌렸는데 통과 후보가 없으면 no_signal 로 종료한다.

    확신도는 보지 않는다 - 물러섬 선언에 높은 확신도를 요구하면 모순이다.
    루프 한계보다 먼저 걸려야 한다(loop 2 에서 종료).
    """
    _assert_covers_every_hypothesis(ALL_SILENT)
    ai = _ai_finalize(0.2, hypothesis="lot 내부 대조로는 안 보인다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": ALL_SILENT})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "no_signal"
    assert "신호 없음" in out["messages"][0].content


def test_gate_no_signal_beats_max_loops():
    """루프 한계에 닿아도 사유가 분명하면 no_signal 로 보고한다 (inconclusive 아님)."""
    ai = _ai_finalize(0.2, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 6,
                            "findings": ALL_SILENT})
    assert out["finalize_status"] == "no_signal"


def test_gate_does_not_declare_no_signal_while_a_passing_claim_exists():
    """한 가설에 통과 후보가 있으면, 다른 가설이 no_signal 이어도 전체를 신호 없음으로 뭉개면 안 된다.

    통과 후보가 하나라도 있으면 `not bundle.passing()` 이 거짓이라 (2)번에 닿지
    않는다 - 커버리지와 무관하게 성립하는 명제다. 픽스처를 전부 채우는 것은 옛
    계약의 잔재가 아니라, "다른 축이 조용해도" 라는 전제를 실제로 만들기 위해서다.
    """
    findings = [EVIDENCE_FINDING, PPID_SILENT, STEP_PASSAGE_SILENT, METRO_SILENT]
    _assert_covers_every_hypothesis(findings)
    ai = _ai_finalize(0.2, hypothesis="아직 claim_id 를 못 골랐다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": findings})
    assert "finalize_accepted" not in out


def test_gate_does_not_declare_no_signal_when_candidates_only_missed_the_line():
    """가설이 후보를 냈지만 문턱을 못 넘은 것(status ok)은 no_signal 이 아니라 weak_signal 이다.

    no_signal 은 도구가 후보 자체를 못 낸(status no_signal) 구조적 부재를 뜻한다.
    후보는 있는데 판별선만 못 넘은 경우는 조치가 다르므로(더 좁힐 여지가 있다)
    같은 취급을 하면 안 된다.

    등록 가설을 **전부 status ok 로** 채운다. 하나라도 no_signal 로 채우면 statuses
    에 no_signal 이 섞여 (2)번이 열려 버려 다른 케이스(혼합 상태)를 시험하게 된다.

    4축 전부 판별선 미달인 이 상태가 (2a) 의 동기 그 자체다 - 그중 아랫선(0.25)을
    넘은 것은 score 0.4 인 eqp_ch 하나뿐이고(나머지 셋은 0.2 로 잔차가 아니다),
    그래서 weak_signal 로 끝나고 final_claims 에도 그 하나만 실린다.
    """
    weak_eqp_ch = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": False,
             "reject_reason": "분리 점수 0.4 < 0.5",
             "score": 0.4, "target_pass": 4, "target_total": 4,   # 4/4 - 3/5 = 0.4
             "control_pass": 3, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    weak_ppid = {
        "loop": 3, "tool": "hyp_ppid_commonality", "args": {},
        "result": {"hypothesis_id": "ppid_commonality", "status": "ok", "candidates": [
            {"claim_id": "ppid_commonality:ppid:PPID001:P1", "step_seq": "PPID001",
             "key": "P1", "level": "ppid", "passes": False,
             "reject_reason": "분리 점수 0.2 < 0.5",
             "score": 0.2, "target_pass": 4, "target_total": 4,   # 4/4 - 4/5 = 0.2
             "control_pass": 4, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    weak_step = {
        "loop": 4, "tool": "hyp_step_passage_commonality", "args": {},
        "result": {"hypothesis_id": "step_passage_commonality", "status": "ok", "candidates": [
            {"claim_id": "step_passage_commonality:step_passage:CE005000:CE005000",
             "step_seq": "CE005000", "key": "CE005000", "level": "step_passage",
             "passes": False, "reject_reason": "분리 점수 0.2 < 0.5",
             "score": 0.2, "target_pass": 4, "target_total": 4,   # 4/4 - 4/5 = 0.2
             "control_pass": 4, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    weak_metro = {
        "loop": 5, "tool": "hyp_metro_commonality", "args": {},
        "result": {"hypothesis_id": "metro_commonality", "status": "ok", "candidates": [
            {"claim_id": "metro_commonality:metro:CC001500:THK >= 129.0",
             "step_seq": "CC001500", "key": "THK >= 129.0", "level": "metro",
             "item": "THK", "split_value": 129.0, "split_direction": "ge",
             "passes": False, "reject_reason": "분리 점수 0.2 < 0.5",
             "score": 0.2, "target_pass": 4, "target_total": 4,   # 4/4 - 4/5 = 0.2
             "control_pass": 4, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    findings = [weak_eqp_ch, weak_ppid, weak_step, weak_metro]
    _assert_covers_every_hypothesis(findings)
    ai = _ai_finalize(0.2, hypothesis="약한 후보뿐", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": findings})
    assert out["finalize_status"] == "weak_signal"
    assert out["finalize_status"] != "no_signal"   # 이 테스트의 본래 주장
    ids = [c["claim_id"] for c in out["final_claims"]]
    assert ids == ["eqp_ch_commonality:chamber:CC002000:ETCH9_B"]


def test_gate_declares_no_comparable_data_when_every_axis_is_uncomputable():
    """등록 가설을 다 돌렸는데 전부 계산 자체를 못 했으면 사유를 밝히고 끝낸다.

    `no_paired_stratum`(같은 root_lot 대조 짝 없음)·`insufficient_group`(타깃 부족)은
    그룹 수준 사실이므로 여기서 끝내야 진짜 사유인 **데이터 결측**이 리포트에 남는다.
    (4) 루프 한계로 밀리면 `inconclusive`("확정 근거 없음")가 돼 사유가 사라진다.

    전축 실행을 요구하는 이유는 [[test_gate_does_not_declare_no_comparable_data_before_running_every_axis]]
    에 적혀 있다 - (2)번과 달리 이 판정은 "볼 것이 없었다" 는 주장이라 부분 커버리지로는 참이 아니다.
    """
    no_pair = [{
        "loop": 1, "tool": t, "args": {},
        "result": {"hypothesis_id": h, "status": "no_paired_stratum", "candidates": []},
        "thought": "짝 없음",
    } for t, h in [("hyp_eqp_ch_commonality", "eqp_ch_commonality"),
                   ("hyp_ppid_commonality", "ppid_commonality"),
                   ("hyp_step_passage_commonality", "step_passage_commonality"),
                   ("hyp_metro_commonality", "metro_commonality")]]
    _assert_covers_every_hypothesis(no_pair)
    ai = _ai_finalize(0.2, hypothesis="비교할 짝이 없다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": no_pair})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "no_comparable_data"
    assert "no_paired_stratum" in out["messages"][0].content   # 사유를 그대로 실어 보낸다


def test_gate_does_not_declare_no_comparable_data_when_another_hypothesis_computed():
    """한 가설이 계산 불가여도 다른 가설이 계산됐으면 '데이터 결측'이 아니다.

    결측 판정은 **돌아간 가설 전부**가 계산 불가일 때만 성립한다. 한쪽이라도
    후보를 냈다면 조치가 다르다(더 좁힐 여지가 있다) - 뭉개면 안 된다.
    """
    no_pair = {
        "loop": 1, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality",
                   "status": "no_paired_stratum", "candidates": []},
        "thought": "1차 legend",
    }
    weak_ppid = {
        "loop": 2, "tool": "hyp_ppid_commonality", "args": {},
        "result": {"hypothesis_id": "ppid_commonality", "status": "ok", "candidates": [
            {"claim_id": "ppid_commonality:ppid:PPID001:P1", "step_seq": "PPID001",
             "key": "P1", "level": "ppid", "passes": False,
             "reject_reason": "분리 점수 0.2 < 0.5",
             "score": 0.2, "target_pass": 4, "target_total": 4,   # 4/4 - 4/5 = 0.2
             "control_pass": 4, "control_total": 5},
        ]},
        "thought": "2차 legend",
    }
    ai = _ai_finalize(0.2, hypothesis="약한 후보뿐", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [no_pair, weak_ppid]})
    assert "finalize_accepted" not in out


def test_gate_accepts_chamber_hypothesis():
    ai = _ai_finalize(0.9, hypothesis="Etch 공정 ETCH9_B 챔버 편중이 원인",
                      claim_id="eqp_ch_commonality:chamber:CC002000:ETCH9_B")
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
    out = nodes.tools_node({"messages": [_ai_finalize(0.6)], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "확신도" in out["messages"][0].content     # 근거는 맞는데 확신도가 모자란 경우
    assert out["findings"][0]["tool"] == "finalize"   # 반려도 감사 기록에 남는다


def test_finalize_gate_accepts_high_confidence_with_evidence():
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"
    assert out["final_hypothesis"] == "Etch ETCH-9 원인"
    assert out["final_confidence"] == 0.9
    assert "승인" in out["messages"][0].content
    # 감사 기록에 남는 verdict 수치 자체를 잠근다 (분리 점수·타깃/대조군 통과 수)
    assert ("eqp_ch_commonality:chamber:Etch:ETCH-9 · 분리 점수 1.0 · "
            "타깃 3/3 통과 · 대조군 0/3 통과") in out["messages"][0].content


def test_finalize_gate_rejects_high_confidence_without_evidence():
    # (a) 조사 없이 결론: confidence 0.9 라도 그룹 대조 근거가 없으면 반려
    out = nodes.tools_node({"messages": [_ai_finalize(0.9, claim_id="")],
                            "loop_count": 1, "findings": []})
    assert "finalize_accepted" not in out
    assert "hyp_" in out["messages"][0].content       # 무엇을 하라는지 안내


def test_finalize_gate_sees_evidence_from_same_message():
    # 한 메시지에 hyp_eqp_ch_commonality + finalize 가 같이 오면, 방금 실행된 대조 결과도 증거다
    ai = AIMessage(
        content="그룹 대조 후 바로 종료 제안",
        tool_calls=[
            # 대조 분모는 LLM 스키마에 없다 - state 에서 주입된다.
            {"name": "hyp_eqp_ch_commonality",
             "args": {"reason": "챔버 편중 가설"},
             "id": "call_c"},
            {"name": "finalize",
             "args": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                      "hypothesis": "Etch ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
             "id": "call_f"},
        ],
    )
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": [],
                            "target_group": ["W2406_02", "W2406_04", "W2406_06"],
                            "control_group": ["W2406_01", "W2406_03", "W2406_05"]})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "confirmed"


def test_finalize_gate_marks_inconclusive_at_max_loops():
    # (c) 한계 도달 강제 종료는 "승인"이 아니라 "미확정"으로 구분 기록
    out = nodes.tools_node({"messages": [_ai_finalize(0.5)],
                            "loop_count": ya_config.MAX_LOOPS, "findings": []})
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


def test_report_node_marks_no_comparable_data_conclusion():
    """계산 불가 종료의 결론은 '분석 미수행 - 비교 가능한 데이터 없음' 이어야 한다.

    `inconclusive`("근거를 못 찾았다")와 조치가 다르다 - 이쪽은 사람이 적재/추출
    범위를 봐야 한다. 문구가 같으면 엔지니어가 엉뚱한 곳을 뒤진다.
    """
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약",
        "findings": [], "final_hypothesis": "", "final_confidence": 0.2,
        "finalize_status": "no_comparable_data",
    })
    assert "분석 미수행" in out["report"]
    assert "미확정" not in out["report"]


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
        {"name": "finalize", "args": {"claim_id": "eqp_ch_commonality:chamber:Etch:ETCH-9",
                                      "hypothesis": "Etch ETCH-9 원인",
                                      "confidence": "high"}, "id": "cf"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING]})
    assert "finalize_accepted" not in out
    assert "숫자" in out["messages"][0].content


def test_tools_node_skips_calls_after_finalize_accepted():
    """승인 뒤 같은 메시지의 잔여 tool 은 실행되지 않는다 — 종료 판정 뒤에 생긴 증거가
    감사 기록에 섞이면 안 된다. 단 ToolMessage 는 tool_call 수만큼 채운다(LangChain 계약)."""
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize",
         "args": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                  "hypothesis": "Etch 공정 ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
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


def test_rejected_finalize_does_not_stop_following_calls():
    """반려는 종료가 아니다 — 뒤따르는 tool 은 그대로 실행한다.

    이 절반이 없으면 `stopped = bool(update.get("finalize_accepted"))` 를 무조건
    True 로 단순화해도 스위트가 통과한다. 그러면 게이트가 "근거를 좁힐 tool 을 더
    호출하라" 고 해 놓고 그 호출을 조용히 삼켜 루프가 헛돈다.
    """
    ai = AIMessage(content="근거를 더 모아 본다", tool_calls=[
        {"name": "finalize",
         "args": {"hypothesis": "아직 근거 없음", "confidence": 0.3}, "id": "cf"},
        {"name": "get_wafer", "args": {"wafer_id": "W2406_02"}, "id": "c1"},
    ])
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": []})

    assert "finalize_accepted" not in out          # 반려
    executed = [f for f in out["findings"] if f["tool"] == "get_wafer"]
    assert len(executed) == 1
    assert isinstance(executed[0]["result"], dict)   # 생략이 아니라 실제 조회 결과
    assert executed[0]["result"]["wafer_id"] == "W2406_02"


def test_second_finalize_does_not_overwrite_accepted_hypothesis():
    """한 메시지에 finalize 가 2개면 뒤가 앞의 승인 가설을 덮어썼다."""
    ai = AIMessage(content="종료 제안", tool_calls=[
        {"name": "finalize",
         "args": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                  "hypothesis": "Etch 공정 ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
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
        {"name": "get_wafer",
         "args": {"wafer_id": "W2406_02", "reason": "대상 수율 확인"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1})
    assert out["findings"][0]["thought"] == "대상 수율 확인"


def test_report_node_appends_evidence_line_for_approved_claim():
    """[근거] 줄은 report_node 가 코드로 붙인다 - 클라이언트가 뭘 돌려주든 운영에서도 보장된다.

    이전에는 ScriptedMockLLMClient 만 자기 안에서 [근거] 를 냈다(문제 1, 최종 검토).
    그 계약(claim_id·분리 점수 1.0·3/3·0/6 라벨)을 여기 report_node 층으로 옮긴다.
    """
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
        "final_hypothesis": "원인은 그 챔버다", "final_confidence": 0.9,
        "finalize_status": "confirmed",
        "final_claims": [{"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                          "score": 1.0, "target_pass": 3, "target_total": 3,
                          "control_pass": 0, "control_total": 6, "rank": 1}],
    })
    assert "[근거 1]" in out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]
    assert "분리 점수 1.0" in out["report"]
    assert "타깃 3/3" in out["report"] and "대조군 0/6" in out["report"]
    assert out["report"].count("[근거 1]") == 1   # 클라이언트가 또 붙이면 중복된다


def test_report_labels_a_residual_as_residual_not_as_evidence():
    """라벨이 없으면 미통과 후보가 통과 근거와 글자 하나 다르지 않다.

    엔지니어는 그 줄을 보고 설비를 세운다. 왜 약한지(reject_reason)도 같은 줄에 남긴다 -
    수치만 있으면 '분리 점수 0.4' 가 강한 근거인지 약한 근거인지 읽을 수 없다.
    """
    state = {
        "final_claims": [{
            "claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
            "level": "chamber", "key": "ETCH9_B", "step_seq": "CC002000",
            "score": 0.4, "passes": False, "reject_reason": "분리 점수 0.4 < 0.5",
            "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5,
            "rank": 1, "kind": "statistical", "target_wafers": [], "control_wafers": [],
            "confounded_with": [], "rolled_up_as": [],
        }],
        "finalize_status": "weak_signal", "final_hypothesis": "h",
        "final_confidence": 0.3, "status_summary": "s", "findings": [],
        "target_wafers": ["W1"], "target_group": ["W1"], "messages": [],
    }
    report = nodes.report_node(state)["report"]
    assert "[잔차 1]" in report
    assert "[근거 1]" not in report
    assert "분리 점수 0.4 < 0.5" in report


def test_report_still_labels_a_passing_claim_as_evidence():
    """확정 경로의 라벨은 그대로다 - 잔차 분기를 넣다가 통과 근거까지 바꾸면 안 된다.

    `reject_reason` 을 (실제로는 안 생기지만) 일부러 채워 둔다 - reject_reason 출력
    가드는 `not passes and reject_reason` 두 항인데, `passes` 항이 없으면 통과
    claim 도 reject_reason 이 있기만 하면 "(판별선 미달: ...)" 이 찍힌다. 이 값이
    없으면 그 조건이 참이든 거짓이든 결과가 같아 `passes` 항을 잠그지 못한다.
    """
    state = {
        "final_claims": [{
            "claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
            "level": "chamber", "key": "ETCH9_B", "step_seq": "CC002000",
            "score": 1.0, "passes": True, "reject_reason": "분리 점수 0.4 < 0.5",
            "target_pass": 3, "target_total": 3, "control_pass": 0, "control_total": 3,
            "rank": 1, "kind": "statistical", "target_wafers": [], "control_wafers": [],
            "confounded_with": [], "rolled_up_as": [],
        }],
        "finalize_status": "confirmed", "final_hypothesis": "h",
        "final_confidence": 0.9, "status_summary": "s", "findings": [],
        "target_wafers": ["W1"], "target_group": ["W1"], "messages": [],
    }
    report = nodes.report_node(state)["report"]
    assert "[근거 1]" in report
    assert "[잔차" not in report
    assert "판별선 미달" not in report


def test_report_labels_a_passing_sensor_as_evidence():
    """통과한 센서 근거도 `[근거]` 로 찍혀야 한다 - `[잔차]` 로 새면 안 된다.

    센서는 자기 판별선(0.8)을 갖고 이미 통과/미통과가 갈린 뒤 근거로 실린다. 라벨은
    `passes` 만 보고 정해야 한다 - `kind` 까지 함께 보는 조건이 섞여 들어오면 통과한
    센서가 잔차로 오분류될 수 있다. 이 자리를 실제로 지나는 것은 `report_node` 이고,
    `main.py` 더미 실행에서도 이런 줄이 여러 개 나간다.
    """
    state = {
        "final_claims": [{
            "claim_id": "sensor:CC002000:TEMP_1", "kind": "sensor",
            "level": "sensor", "key": "TEMP_1", "step_seq": "CC002000",
            "score": 2.31, "passes": True, "reject_reason": None,
            "target_total": 12, "control_total": 40,
            "extra": {"target_mean": 812.4, "control_mean": 799.1,
                      "target_std": 3.0, "control_std": 2.8},
            "rank": 1, "target_wafers": [], "control_wafers": [],
            "confounded_with": [], "rolled_up_as": [],
        }],
        "finalize_status": "confirmed", "final_hypothesis": "h",
        "final_confidence": 0.9, "status_summary": "s", "findings": [],
        "target_wafers": ["W1"], "target_group": ["W1"], "messages": [],
    }
    report = nodes.report_node(state)["report"]
    assert "[근거 1]" in report
    assert "[잔차" not in report


def test_report_more_below_summary_is_not_labeled_as_evidence():
    """생략 요약 줄은 `근거` 도 `잔차` 도 아니다.

    잘려 나간 꼬리는 `_order_key` 로 줄 세운 목록의 뒤쪽이라 구조상 가장 약한
    후보들이다. `[근거 ...]` 로 찍으면 통과 근거가 한 줄도 없는 weak_signal
    리포트가 "근거 N건 생략" 이라는 거짓을 말하게 된다.
    """
    state = {
        "final_claims": [{
            "claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
            "level": "chamber", "key": "ETCH9_B", "step_seq": "CC002000",
            "score": 0.4, "passes": False, "reject_reason": "분리 점수 0.4 < 0.5",
            "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5,
            "rank": 1, "kind": "statistical", "target_wafers": [], "control_wafers": [],
            "confounded_with": [], "rolled_up_as": [], "more_below": 3,
        }],
        "finalize_status": "weak_signal", "final_hypothesis": "h",
        "final_confidence": 0.3, "status_summary": "s", "findings": [],
        "target_wafers": ["W1"], "target_group": ["W1"], "messages": [],
    }
    report = nodes.report_node(state)["report"]
    assert "3건은 생략했다" in report
    assert "[근거" not in report


def test_report_node_appends_a_coverage_line():
    """커버리지 줄도 report_node 가 코드로 붙인다 - [근거] 와 같은 이유다.

    클라이언트에 맡기면 운영 경로에서 조용히 사라진다(사내에서만 안 붙는 줄이
    생긴다). 판정이 무엇이든, 어느 축까지 봤는지는 리포트에 남아야 한다.
    """
    out = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual",
        "target_group": ["W1"], "status_summary": "요약",
        "findings": [EQP_CH_SILENT],
        "final_hypothesis": None, "final_confidence": 0.2,
        "finalize_status": "no_signal", "final_claims": [],
    })
    assert "[커버리지]" in out["report"]
    assert "hyp_metro_commonality" in out["report"]


def test_gate_does_not_leave_a_stale_coverage_behind_when_it_rejects():
    """반려는 상태에 커버리지를 남기지 않는다 - 남기면 그 값이 굳어 거짓말이 된다.

    반려 시점의 커버리지를 state 에 쓰면, LLM 이 loop 1 에 종료를 제안했다가
    반려당하는 흔한 경로에서 `ran: []` 가 박힌다. 그 뒤 축을 아무리 더 돌려도
    갱신은 다음 finalize 때만 일어나므로, 마지막 finalize 없이 루프 한계로 끝나면
    **다 돌린 축을 하나도 안 돌렸다고 보고**한다. 커버리지는 종료된 판정의 기록이다.
    """
    ai = _ai_finalize(0.9, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1,
                            "findings": []})
    assert "finalize_accepted" not in out       # 반려가 맞는지 먼저 확인
    assert "coverage" not in out


def test_report_node_recounts_coverage_from_the_audit_trail():
    """리포트는 state 의 커버리지를 믿지 않고 감사 기록에서 다시 센다.

    낡은 값이 상태에 남을 수 있는 경로가 있는 한(반려·게이트 미경유), 리포트가
    그 값을 그대로 쓰면 "커버리지는 사실이다" 라는 전제가 무너진다. findings 가
    유일한 진실이다.
    """
    stale = {"ran": [], "unrun": ["hyp_eqp_ch_commonality", "hyp_metro_commonality",
                                  "hyp_ppid_commonality", "hyp_step_passage_commonality"],
             "no_data": []}
    out = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual",
        "target_group": ["W1"], "status_summary": "요약",
        "findings": [EQP_CH_SILENT], "coverage": stale,
        "final_hypothesis": None, "final_confidence": 0.2,
        "finalize_status": "no_signal", "final_claims": [],
    })
    assert "[커버리지]" in out["report"]
    assert "hyp_eqp_ch_commonality" not in out["report"].split("[커버리지]")[1]


def test_report_node_sends_the_recounted_coverage_to_the_client():
    """다시 센 값이 **클라이언트에도** 가야 한다 - 리포트 줄만 고치면 산문이 거짓말한다.

    운영 시스템 프롬프트는 "안 본 축 이름을 반드시 적어라" 로 지시하므로, 낡은
    커버리지가 가면 LLM 이 실제로 다 돌린 축을 안 봤다고 지어낸다.
    """
    received = {}

    class _RecordingClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            received.update(kwargs)
            return "고정된 산문 리포트"

    original = nodes._llm
    nodes._llm = _RecordingClient()
    try:
        nodes.report_node({
            "target_wafers": ["W1"], "target_source": "manual",
            "target_group": ["W1"], "status_summary": "요약",
            "findings": [EQP_CH_SILENT], "final_claims": [],
            "final_hypothesis": None, "final_confidence": 0.2,
            "finalize_status": "no_signal",
            # 낡은 값이 상태에 있어도 클라이언트에는 다시 센 값이 가야 한다
            "coverage": {"ran": [], "no_data": [],
                         "unrun": ["hyp_eqp_ch_commonality", "hyp_metro_commonality",
                                   "hyp_ppid_commonality", "hyp_step_passage_commonality"]},
        })
    finally:
        nodes._llm = original
    assert received["coverage"]["ran"] == ["hyp_eqp_ch_commonality"]
    assert "hyp_metro_commonality" in received["coverage"]["unrun"]


def test_gate_does_not_declare_no_comparable_data_before_running_every_axis():
    """'볼 것이 없었다' 는 전축을 봐야 참인 주장이다 - (2)번과 성격이 다르다.

    (2) no_signal 은 "대조한 축에서는 못 찾았다" 라 부분 커버리지로도 정직하다.
    (3) no_comparable_data 는 "적재 범위와 추출 조건을 확인하라" 는 조치를 내보내는데,
    축 하나가 계산 불가라고 그렇게 말하면 **데이터가 있는 축을 한 번도 안 건드린 채**
    엔지니어에게 틀린 조치를 준다. metro 는 계측 짝이 없어 상시 no_paired_stratum
    이므로 이 경로는 흔하다.
    """
    metro_no_pair = {
        "loop": 1, "tool": "hyp_metro_commonality", "args": {},
        "result": {"hypothesis_id": "metro_commonality",
                   "status": "no_paired_stratum", "candidates": []},
        "thought": "계측 짝 없음",
    }
    ai = _ai_finalize(0.95, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [metro_no_pair]})
    assert "finalize_accepted" not in out


def test_gate_does_not_read_a_fabricated_claim_id_as_missing_data():
    """(3)번도 지목을 물러섬으로 오독하면 안 된다 - (2)번에 붙인 하한과 대칭이다."""
    no_pair = [{
        "loop": 1, "tool": t, "args": {},
        "result": {"hypothesis_id": h, "status": "no_paired_stratum", "candidates": []},
        "thought": "짝 없음",
    } for t, h in [("hyp_metro_commonality", "metro_commonality"),
                   ("hyp_eqp_ch_commonality", "eqp_ch_commonality"),
                   ("hyp_ppid_commonality", "ppid_commonality"),
                   ("hyp_step_passage_commonality", "step_passage_commonality")]]
    _assert_covers_every_hypothesis(no_pair)
    ai = _ai_finalize(0.95, claim_id="eqp_ch_commonality:chamber:CC002000:NOPE")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2, "findings": no_pair})
    assert "finalize_accepted" not in out


def test_report_node_has_no_coverage_line_when_no_axis_ever_ran():
    """분석 루프에 들어가지도 않은 종료(이상 없음 등)에는 커버리지를 붙이지 않는다.

    "등록 축 4개 중 0개 대조" 는 사실이지만 아무 것도 알려 주지 않는다 - 애초에
    셀 것이 없는 보고서에 세는 줄을 붙이면 소음이다.
    """
    out = nodes.report_node({
        "target_wafers": [], "target_source": "auto",
        "target_group": [], "status_summary": "수율 임계 미만 lot 없음",
        "findings": [], "finalize_status": "no_anomaly",
    })
    assert "[커버리지]" not in out["report"]


def test_report_node_derives_coverage_when_the_gate_never_ran():
    """루프 한계로 게이트를 안 거치고 끝나도 커버리지는 나간다.

    `_after_tools` 는 finalize 승인 없이도 MAX_LOOPS 에서 리포트로 빠지고,
    `_after_analyze` 는 LLM 이 tool 없이 텍스트만 내면 곧바로 리포트로 간다.
    두 경로 모두 게이트를 안 타므로 state 에 coverage 가 없다 - 거기서 줄이
    통째로 사라지면 "커버리지는 결론과 함께 나간다" 는 약속이 **가장 설명이
    필요한 보고서**에서만 깨진다. 감사 기록에서 다시 세어 붙인다.
    """
    out = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual",
        "target_group": ["W1"], "status_summary": "요약",
        "findings": [EQP_CH_SILENT],
        "final_hypothesis": None, "final_confidence": None,
    })
    assert "[커버리지]" in out["report"]
    assert "hyp_metro_commonality" in out["report"]


def test_report_node_has_no_evidence_line_without_claim():
    """확정되지 않은 분석에 근거 줄을 만들어 붙이지 않는다."""
    out = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual",
        "target_group": ["W1"], "status_summary": "s", "findings": [],
        "final_hypothesis": None, "final_confidence": None,
    })
    assert "[근거" not in out["report"]


def test_report_node_appends_evidence_line_regardless_of_client():
    """운영 클라이언트가 [근거] 를 전혀 안 내도 report_node 가 붙인다 - '운영에서도 보장된다'의 유일한 증거.

    OpenAILLMClient.generate_report 는 LLM 응답을 그대로 반환할 뿐 [근거] 를 만들지
    않는다. 그 상황을 최소 스텁으로 재현한다.
    """
    class _StubClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            return "고정된 산문 리포트 (근거 줄 없음)"

    original = nodes._llm
    nodes._llm = _StubClient()
    try:
        out = nodes.report_node({
            "target_wafers": ["W2406_02"], "target_source": "manual",
            "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
            "final_hypothesis": "원인은 그 챔버다", "final_confidence": 0.9,
            "finalize_status": "confirmed",
            "final_claims": [{"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                              "score": 1.0, "target_pass": 3, "target_total": 3,
                              "control_pass": 0, "control_total": 6, "rank": 1}],
        })
    finally:
        nodes._llm = original
    assert "[근거 1]" in out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]


def test_report_node_passes_the_approved_claim_to_the_report():
    """승인된 claim 이 **클라이언트까지** 전달돼야 한다 (리포트 본문 확인만으로는 부족).

    `report_node` 는 `[근거]` 줄을 자기가 붙이므로, 리포트 문자열에서 claim_id 를
    찾는 것만으로는 `generate_report(claims=...)` 인자를 지워도 통과한다. 그 인자는
    운영 클라이언트의 "수치를 그대로 인용하라" 프롬프트를 만드는 유일한 통로라
    여기서 인자 자체를 잠근다.
    """
    received = {}

    class _RecordingClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            received.update(kwargs)
            return "고정된 산문 리포트 (근거 줄 없음)"

    approved = {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "score": 1.0,
                "target_pass": 3, "target_total": 3,
                "control_pass": 0, "control_total": 6, "rank": 1}
    original = nodes._llm
    nodes._llm = _RecordingClient()
    try:
        out = nodes.report_node({
            "target_wafers": ["W2406_02"], "target_source": "manual",
            "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
            "final_hypothesis": "ETCH9_B 편중", "final_confidence": 0.9,
            "finalize_status": "confirmed",
            "final_claims": [approved],
        })
    finally:
        nodes._llm = original

    assert received.get("claims") == [approved]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]

# ---------------------------------------------------------------- LLM 호출 실패
# 사내 LLM 은 타임아웃·5xx 를 낸다. `ya_console.say` 가 막으려던 것과 같은 유실이
# 여기서 다른 경로로 난다 - 그래프를 다 돌린 결과가 예외 하나로 통째로 사라진다.
# `tools_node` 는 도구 실패를 ToolMessage 로 복구하는데(미룸 1번) LLM 쪽만 무방비였다.

class _FailingLLM:
    """analyze/report 양쪽이 사내 LLM 처럼 터지는 스텁."""

    def analyze_step(self, messages):
        raise TimeoutError("사내 LLM 응답 없음")

    def generate_report(self, **kwargs):
        raise TimeoutError("사내 LLM 응답 없음")


def _with_failing_llm(fn):
    original = nodes._llm
    nodes._llm = _FailingLLM()
    try:
        return fn()
    finally:
        nodes._llm = original


def test_analyze_node_survives_an_llm_failure():
    """LLM 호출이 터져도 노드가 죽지 않고 사유를 상태에 남긴다."""
    out = _with_failing_llm(lambda: nodes.analyze_node(
        {"messages": [], "loop_count": 2}))
    assert out["finalize_status"] == "llm_call_failed"
    assert "TimeoutError" in out["findings"][0]["result"]


def test_analyze_node_failure_routes_to_report():
    """실패한 analyze 는 리포팅으로 나가야 한다 (루프에 갇히면 안 된다).

    `_after_analyze` 는 마지막 메시지의 tool_calls 로 갈림길을 정한다. 실패 시
    tool_calls 없는 메시지를 남기면 기존 안전망이 그대로 report 로 보낸다.
    """
    from graph import build

    out = _with_failing_llm(lambda: nodes.analyze_node(
        {"messages": [], "loop_count": 2}))
    assert build._after_analyze({"messages": out["messages"]}) == "report"


def test_report_node_survives_an_llm_failure():
    """리포트 LLM 이 터져도 분석 결과가 통째로 사라지면 안 된다.

    여기서 예외가 나가면 그래프가 죽고, 그때까지의 현황·감사 기록·승인된 근거가
    전부 유실된다(main.py 는 그래프를 **다 돌린 뒤** 출력한다).
    """
    out = _with_failing_llm(lambda: nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
        "final_hypothesis": "ETCH9_B 챔버 편중이 원인", "final_confidence": 0.9,
        "finalize_status": "confirmed",
    }))
    assert "ETCH9_B 챔버 편중이 원인" in out["report"]   # 결론이 살아 있다
    assert "TimeoutError" in out["report"]              # 왜 산문이 없는지도 밝힌다


def test_report_node_keeps_the_evidence_line_when_the_llm_fails():
    """[근거] 줄은 LLM 산문이 없어도 붙어야 한다 - 코드가 붙이는 이유가 그것이다."""
    claim = {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 6, "rank": 1}
    out = _with_failing_llm(lambda: nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
        "final_hypothesis": "원인은 그 챔버다", "final_confidence": 0.9,
        "finalize_status": "confirmed", "final_claims": [claim],
    }))
    assert "[근거 1]" in out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]


def test_graph_completes_when_the_llm_is_down():
    """LLM 이 통째로 죽어도 그래프는 완주해 리포트를 낸다 (E2E).

    노드 단위 방어가 있어도 배선이 어긋나면 여전히 예외가 밖으로 나간다.
    """
    from graph.build import build_graph

    state = _with_failing_llm(lambda: build_graph().invoke(
        {"target_wafers": ["W2406_02"], "target_source": "manual"}))
    assert state["report"]
    assert state["finalize_status"] == "llm_call_failed"


def test_report_states_the_llm_failure_when_only_analyze_died():
    """analyze 만 터지고 리포트 LLM 은 살아난 경우, 결론이 그 사실을 밝혀야 한다.

    이때 산문은 정상 생성되므로 report_node 의 실패 대체 경로를 안 탄다.
    분기가 없으면 결론이 "원인 미확정" 으로 나가, 분석이 돌았는데 못 찾은 것과
    아예 못 돌린 것이 구분되지 않는다.
    """
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
        "final_hypothesis": "", "final_confidence": 0.0,
        "finalize_status": "llm_call_failed",
    })
    assert "분석 미수행" in out["report"]
    assert "LLM" in out["report"]


# ------------------------------------------------ M3: 대체된 재실행
# 같은 축을 다시 돌리면 build_bundle 이 앞 후보를 버린다(그룹이 바뀌면 분모가 달라
# 거짓이므로 옳다). 그런데 findings 는 그대로 리포트 LLM 에 넘어가고 운영 sys
# 프롬프트는 그 수치를 "그대로 인용하라" 고 지시한다 - 대체 사실을 말하지 않으면
# 게이트가 버린 후보(passes True · p 0.01)를 리포트가 근거로 인용하거나, "신호 없음"
# 이라 써 놓고 바로 옆 감사 기록에 통과 후보가 보이는 모순이 나간다.
EQP_CH_RERUN_SILENT = {
    "loop": 5, "tool": "hyp_eqp_ch_commonality",
    "args": {"group_ids": ["W2406_02", "W2406_04"],       # 타깃을 좁혀 다시 돌렸다
             "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
    "result": {"hypothesis_id": "eqp_ch_commonality", "status": "no_signal",
               "candidates": []},
    "thought": "타깃을 좁혀 재확인",
}


def _superseded_state():
    return {"target_wafers": ["W2406_02"], "target_source": "manual",
            "target_group": ["W2406_02"], "status_summary": "요약",
            "findings": [EVIDENCE_FINDING_NEW, EQP_CH_RERUN_SILENT],
            "final_hypothesis": None, "final_confidence": 0.2,
            "finalize_status": "no_signal", "final_claims": []}


def test_report_node_marks_the_superseded_run_for_the_client():
    """대체된 실행에 표시를 붙여 LLM 에 넘긴다 - 안 붙이면 버린 후보를 인용한다.

    운영 프롬프트가 findings 의 수치를 그대로 인용하라고 지시하므로, 게이트가
    폐기한 후보가 표시 없이 그대로 가면 LLM 은 그것을 살아 있는 근거로 읽는다.
    """
    received = {}

    class _RecordingClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            received.update(kwargs)
            return "고정된 산문 리포트"

    original = nodes._llm
    nodes._llm = _RecordingClient()
    try:
        nodes.report_node(_superseded_state())
    finally:
        nodes._llm = original

    sent = received["findings"]
    assert sent[0].get("superseded") is True     # 통과 후보를 낸 앞 실행
    assert not sent[1].get("superseded")         # 살아 있는 뒤 실행
    # 감사 기록 자체는 지우지 않는다 - 추적성이 이 기록의 존재 이유다
    assert sent[0]["result"]["candidates"][0]["passes"] is True


def test_report_node_does_not_mutate_the_audit_trail():
    """표시는 사본에만 붙인다 - 상태의 findings 를 건드리면 감사 기록이 오염된다."""
    state = _superseded_state()
    original_finding = state["findings"][0]
    nodes.report_node(state)
    assert "superseded" not in original_finding


def test_report_node_names_the_superseded_run_in_the_report():
    """사람이 읽는 리포트에도 남긴다 - 감사 기록을 직접 보는 엔지니어를 위해서다.

    LLM 프롬프트에만 표시하면, main.py 가 찍는 감사 기록에서 p 0.01 을 본
    엔지니어는 결론이 왜 '신호 없음' 인지 읽을 방법이 없다.
    """
    out = nodes.report_node(_superseded_state())
    assert "[대체됨]" in out["report"]
    assert "hyp_eqp_ch_commonality" in out["report"].split("[대체됨]")[1]


def test_report_node_has_no_superseded_line_without_a_rerun():
    """재실행이 없으면 그 줄도 없다 - 늘 붙으면 소음이다."""
    state = _superseded_state()
    state["findings"] = [EVIDENCE_FINDING_NEW]
    out = nodes.report_node(state)
    assert "[대체됨]" not in out["report"]


def test_gate_says_a_submitted_claim_was_superseded_not_invented():
    """대체된 claim_id 를 제출하면 '없다' 가 아니라 '대체됐다' 고 답해야 한다.

    tools_node 가 도구 결과를 ToolMessage 로 대화에 실으므로, LLM 은 재실행 뒤에도
    앞 실행의 claim_id 를 자기 문맥에서 그대로 보고 제출한다. 거기에 "도구 결과에
    없다" 고 답하면 거짓이고(있었고, 뒤 실행이 대체했다), 그 문구는 '지어낸
    claim_id' 분기라 LLM 은 자기가 환각을 낸 줄 알고 같은 문맥을 다시 읽는다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.9},
        loop=3, update=update,
        findings=[EVIDENCE_FINDING_NEW, EQP_CH_RERUN_SILENT])
    assert update.get("finalize_accepted") is None      # 승인은 아니다
    assert "대체" in verdict
    assert "도구 결과에 없다" not in verdict
    # 무엇이 대체했는지 이름이 나와야 다음 행동을 고를 수 있다
    assert "hyp_eqp_ch_commonality" in verdict


def test_gate_still_rejects_an_invented_claim_as_absent():
    """지어낸 claim_id 는 여전히 '없다' 다 - 대체 안내를 아무 데나 붙이면 안 된다."""
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "지어낸:claim:id", "hypothesis": "h", "confidence": 0.9},
        loop=3, update=update,
        findings=[EVIDENCE_FINDING_NEW, EQP_CH_RERUN_SILENT])
    assert "도구 결과에 없다" in verdict
    assert "대체" not in verdict


def test_report_node_survives_a_state_without_findings():
    """findings 키가 없어도 마지막 노드는 리포트를 낸다.

    여기가 마지막 노드다 - 예외를 내보내면 분석을 다 해 놓고 결과를 전부 버린다.
    바로 위 커버리지 재계산은 state.get(...) 로 방어하는데 findings 전달만
    state["findings"] 를 쓰면 방어선이 한 칸 후퇴한다.
    """
    out = nodes.report_node({"target_wafers": ["W1"], "target_source": "manual",
                             "target_group": ["W1"], "status_summary": "s",
                             "final_claims": [], "finalize_status": "no_signal"})
    assert out["report"]


def test_report_node_marks_superseded_when_the_gate_never_judged():
    """게이트를 안 거치고 끝난 종료에서도 대체 표시가 붙어야 한다.

    새 테스트가 전부 finalize_status 가 채워진 상태만 넣으면, 루프 한계·tool 없는
    텍스트 응답으로 끝나는 경로에 표시가 붙는지는 아무도 안 본다.

    리포트 줄과 **클라이언트가 받는 findings** 를 둘 다 본다 - 한쪽만 보면 다른
    쪽이 조용히 빠져도 통과한다(두 렌더링이 엇갈리는 이 저장소의 단골 결함).
    """
    received = {}

    class _RecordingClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            received.update(kwargs)
            return "고정된 산문 리포트"

    state = _superseded_state()
    del state["finalize_status"]
    original = nodes._llm
    nodes._llm = _RecordingClient()
    try:
        out = nodes.report_node(state)
    finally:
        nodes._llm = original
    assert out["finalize_status"] == "inconclusive"
    assert "[대체됨]" in out["report"]
    assert received["findings"][0].get("superseded") is True


def test_report_node_keeps_the_superseded_line_when_the_llm_fails():
    """산문이 죽어도 대체 표시는 남아야 한다 - [근거]·[커버리지] 와 같은 이유다."""
    class _DeadClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            raise RuntimeError("LLM down")

    original = nodes._llm
    nodes._llm = _DeadClient()
    try:
        out = nodes.report_node(_superseded_state())
    finally:
        nodes._llm = original
    assert "[리포트 생성 실패]" in out["report"]
    assert "[대체됨]" in out["report"]


# ------------------------------------------------ M3 재리뷰 지적
EQP_CH_RERUN_SAME_ARGS = {
    "loop": 5, "tool": "hyp_eqp_ch_commonality",
    "args": dict(EVIDENCE_FINDING_NEW["args"]),        # 인자가 완전히 같은 재실행
    "result": EVIDENCE_FINDING_NEW["result"],
    "thought": "같은 조건으로 재확인",
}
PPID_EVIDENCE = {
    "loop": 3, "tool": "hyp_ppid_commonality",
    "args": {"group_ids": ["W2406_02"], "control_ids": ["W2406_01"]},
    "result": {"hypothesis_id": "ppid_commonality", "status": "ok",
               "candidates": [
                   {"claim_id": "ppid_commonality:ppid:CE005000:PPID_X",
                    "passes": True, "level": "ppid", "key": "PPID_X",
                    "step_seq": "CE005000", "score": 1.0,
                    "target_pass": 3, "target_total": 3,
                    "control_pass": 0, "control_total": 3, "reject_reason": None},
               ]},
    "thought": "레시피",
}


def test_gate_does_not_tell_it_to_pick_when_nothing_is_left_to_pick():
    """대체 안내가 실행 불가능한 지시로 끝나면 안 된다.

    "최신 실행 결과에서 골라라" 뒤에 "지목할 수 있는 후보가 없다" 가 붙으면 한 문장 안에서
    자기모순이고, H1 이 막으려던 "LLM 이 같은 문맥을 다시 읽는" 행동이 약한 형태로
    되살아난다. 사실(대체됐다)과 다음 행동(무엇을 하라)은 분리한다.
    """
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.9},
        loop=3, update={}, findings=[EVIDENCE_FINDING_NEW, EQP_CH_RERUN_SILENT])
    assert "대체" in verdict
    assert "골라라" not in verdict          # 고를 것이 없다
    assert "지목할 수 있는 통과 후보가 없다" in verdict   # 다음 행동은 이쪽이 안내한다


def test_gate_lists_surviving_candidates_when_a_superseded_claim_is_submitted():
    """대체된 claim 을 냈는데 **다른 축에 통과 후보가 살아 있는** 경우.

    새 테스트가 둘 다 valid 가 빈 상태만 넣어서, 실전에서 더 흔할 이 조합은
    회귀 방어가 0이었다.
    """
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.9},
        loop=3, update={},
        findings=[EVIDENCE_FINDING_NEW, PPID_EVIDENCE, EQP_CH_RERUN_SILENT])
    assert "대체" in verdict
    assert "도구 결과에 없다" not in verdict
    # 살아 있는 통과 후보를 안내해야 다음 행동이 생긴다
    assert "ppid_commonality:ppid:CE005000:PPID_X" in verdict


def test_report_names_the_superseded_loop_not_the_superseding_one():
    """[대체됨] 이 **대체된** 실행을 가리켜야 한다 - 재실행도 같은 도구라 이름으로는 안 갈린다.

    loop 번호는 엔지니어가 감사 기록에서 그 항목을 찾는 유일한 열쇠다.
    """
    out = nodes.report_node(_superseded_state())
    line = [l for l in out["report"].splitlines() if "[대체됨]" in l][0]
    assert "loop 2" in line     # EVIDENCE_FINDING_NEW (대체된 쪽)
    assert "loop 5" not in line  # EQP_CH_RERUN_SILENT (대체한 쪽)


def test_report_carries_every_supersession_not_just_the_first():
    """대체가 2건이면 리포트 줄도 클라이언트 표시도 2건이어야 한다.

    build_bundle 레벨에만 2건짜리 시험이 있고 리포트·클라이언트 경계에는 없었다.
    """
    received = {}

    class _RecordingClient:
        def analyze_step(self, messages):
            raise NotImplementedError

        def generate_report(self, **kwargs):
            received.update(kwargs)
            return "고정된 산문 리포트"

    ppid_rerun = {**PPID_EVIDENCE, "loop": 6,
                  "result": {"hypothesis_id": "ppid_commonality",
                             "status": "no_signal", "candidates": []}}
    state = _superseded_state()
    state["findings"] = [EVIDENCE_FINDING_NEW, PPID_EVIDENCE,
                         EQP_CH_RERUN_SILENT, ppid_rerun]
    original = nodes._llm
    nodes._llm = _RecordingClient()
    try:
        out = nodes.report_node(state)
    finally:
        nodes._llm = original
    assert out["report"].count("[대체됨]") == 2
    marked = [f["loop"] for f in received["findings"] if f.get("superseded")]
    assert sorted(marked) == [2, 3]


def test_a_rerun_that_recreates_the_same_claims_supersedes_nothing():
    """인자가 같은 재실행은 같은 claim_id 를 다시 만든다 - 잃은 것이 없다.

    그런데도 대체로 표시하면 리포트가 자기모순을 낸다: [근거] 로 실린 바로 그
    claim 을 sys 프롬프트가 "인용하지 마라" 고 막는다. claim_id 는 그룹 인자와
    무관하게 만들어지므로(domain/engine.py) 실제로 도달하는 상태다.
    """
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약",
        "findings": [EVIDENCE_FINDING_NEW, EQP_CH_RERUN_SAME_ARGS],
        "final_claims": [], "finalize_status": "no_signal",
        "final_hypothesis": None, "final_confidence": 0.2})
    assert "[대체됨]" not in out["report"]


# ---------------------------------------------------------------- 대조 분모 주입
# 파이프라인이 확정한 그룹으로만 축이 돌아야 한다. LLM 이 group_ids 를 정할 수 있던
# 동안에는 리포트 머리말("분석 대상")과 다른 분모로 계산된 후보가 결론이 될 수 있었고,
# 게이트는 claim_id 조회만 하므로 그 어긋남을 볼 방법이 없었다.
_PIPELINE_TARGET = ["W2406_02", "W2406_04", "W2406_06"]
_PIPELINE_CONTROL = ["W2406_01", "W2406_03", "W2406_05"]
# 타깃과 대조군이 뒤바뀐 값. LLM 이 이런 것을 넘겨도 실행에는 닿으면 안 된다.
_LLM_SUPPLIED_GROUPS = {"group_ids": ["W2406_01"], "control_ids": ["W2406_02"]}


def _pipeline_state(ai, **extra):
    return {"messages": [ai], "loop_count": 1, "findings": [],
            "target_group": _PIPELINE_TARGET, "control_group": _PIPELINE_CONTROL,
            **extra}


def test_hypothesis_tool_runs_on_pipeline_groups_even_if_the_llm_supplies_others():
    """LLM 이 넘긴 그룹은 무시되고 state 의 그룹으로 실행된다.

    결과 전체를 파이프라인 그룹으로 직접 부른 것과 대조한다 - 후보 하나만 보면
    "우연히 같은 후보가 나왔다" 와 구분되지 않는다. 도구는 같은 인자에 결정적이므로
    (순열 시드 고정) 완전 일치가 성립한다.
    """
    from tools.agent_tools import TOOLS_BY_NAME

    ai = AIMessage(content="챔버 대조",
                   tool_calls=[{"name": "hyp_eqp_ch_commonality",
                                "args": {**_LLM_SUPPLIED_GROUPS, "reason": "테스트"},
                                "id": "call_1"}])
    out = nodes.tools_node(_pipeline_state(ai))

    expected = TOOLS_BY_NAME["hyp_eqp_ch_commonality"].invoke(
        {"group_ids": _PIPELINE_TARGET, "control_ids": _PIPELINE_CONTROL})
    assert out["findings"][0]["result"] == expected


def test_hypothesis_tool_runs_when_the_llm_supplies_no_groups_at_all():
    """운영의 실제 모양 - 스키마에 없으니 LLM 은 그룹을 아예 안 보낸다.

    위 테스트(LLM 이 보낸 경우)만 있으면 '덮어쓰기' 는 잠기지만 '없을 때 채우기' 는
    안 잠긴다. 분기 양쪽을 다 넣는다.
    """
    from tools.agent_tools import TOOLS_BY_NAME

    ai = AIMessage(content="챔버 대조",
                   tool_calls=[{"name": "hyp_eqp_ch_commonality",
                                "args": {"reason": "테스트"}, "id": "call_1"}])
    out = nodes.tools_node(_pipeline_state(ai))

    expected = TOOLS_BY_NAME["hyp_eqp_ch_commonality"].invoke(
        {"group_ids": _PIPELINE_TARGET, "control_ids": _PIPELINE_CONTROL})
    assert out["findings"][0]["result"] == expected
    assert "오류" not in str(out["messages"][0].content)


def test_audit_records_the_groups_that_actually_ran():
    """감사 기록의 args 는 **실행된** 분모여야 한다.

    findings 는 리포트 LLM 에게 그대로 넘어가고 운영 프롬프트가 그 수치를 "그대로
    인용하라" 고 지시한다. LLM 이 보낸 값을 그대로 적어 두면 감사 기록이 실행과
    다른 분모를 가리키고, 그것이 리포트의 근거 문장이 된다.
    """
    ai = AIMessage(content="챔버 대조",
                   tool_calls=[{"name": "hyp_eqp_ch_commonality",
                                "args": {**_LLM_SUPPLIED_GROUPS, "reason": "테스트"},
                                "id": "call_1"}])
    args = nodes.tools_node(_pipeline_state(ai))["findings"][0]["args"]
    assert args["group_ids"] == _PIPELINE_TARGET
    assert args["control_ids"] == _PIPELINE_CONTROL
    assert args["reason"] == "테스트"          # LLM 이 정하는 인자는 그대로 남는다


def test_sensor_tool_also_runs_on_pipeline_groups():
    """2단 센서 도구도 같은 분모를 쓴다.

    한쪽만 고치면 1단(경로)과 2단(센서)이 다른 그룹을 보고 "왜" 를 답하게 된다.
    step_seq 는 LLM 이 정하는 인자이므로 건드리지 않는다.
    """
    from data.generate_dummy import SENSOR_STEP
    from tools.agent_tools import TOOLS_BY_NAME

    ai = AIMessage(content="센서 분포",
                   tool_calls=[{"name": "compare_sensor_distribution",
                                "args": {"step_seq": SENSOR_STEP, **_LLM_SUPPLIED_GROUPS},
                                "id": "call_1"}])
    out = nodes.tools_node(_pipeline_state(ai))

    expected = TOOLS_BY_NAME["compare_sensor_distribution"].invoke(
        {"step_seq": SENSOR_STEP, "group_ids": _PIPELINE_TARGET,
         "control_ids": _PIPELINE_CONTROL})
    assert out["findings"][0]["result"] == expected
    assert out["findings"][0]["args"]["step_seq"] == SENSOR_STEP


def test_tools_that_do_not_take_groups_are_left_alone():
    """그룹 인자가 없는 도구에 그룹을 밀어 넣으면 안 된다.

    주입을 도구 이름이 아니라 **선언된 인자**로 판정하는지 잠근다. 무조건 넣으면
    get_wafer 가 인자 스키마 위반으로 죽고, 그 실패는 "인자를 확인하고 다시 호출하라"
    로 돌아와 루프만 태운다.
    """
    ai = AIMessage(content="wafer 조회",
                   tool_calls=[{"name": "get_wafer",
                                "args": {"wafer_id": "W2406_02"}, "id": "call_1"}])
    out = nodes.tools_node(_pipeline_state(ai))
    assert out["findings"][0]["args"] == {"wafer_id": "W2406_02"}
    assert out["findings"][0]["result"]["wafer_id"] == "W2406_02"


# ------------------------------------------------- 도구 실패 안내 · 주입 누락
def _boom(*_a, **_k):
    raise RuntimeError("DB 연결 끊김")


def test_tool_failure_does_not_tell_the_llm_to_fix_arguments_it_cannot_see():
    """바꿀 인자가 없는 도구에 "인자를 확인하고 다시 호출하라" 고 하면 루프만 탄다.

    분모(group_ids/control_ids)는 스키마에서 빠져 LLM 이 못 본다. hyp_* 에 남은
    LLM 인자는 reason 뿐이고 reason 은 계산에 안 쓰인다 - 주입된 분모 쪽에서 실패가
    나면 모델이 바꿀 수 있는 것이 없어 사실상 같은 호출을 MAX_LOOPS 까지 반복하고
    inconclusive 로 떨어진다. `agent_tools` 가 쓸 수 없는 도구를 아예 등록하지 않는
    이유와 같은 실패 유형이다.
    """
    from domain import engine

    original = engine.evaluate
    engine.evaluate = _boom
    try:
        ai = AIMessage(content="", tool_calls=[
            {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"}])
        out = nodes.tools_node(_pipeline_state(ai))
    finally:
        engine.evaluate = original

    msg = str(out["messages"][0].content)
    assert "RuntimeError" in msg and "DB 연결 끊김" in msg   # 무엇이 터졌는지는 남긴다
    assert "인자를 확인" not in msg                          # 못 바꾸는 것을 시키지 않는다
    assert "다른 축" in msg                                  # 대신 할 수 있는 것을 준다


def test_tool_failure_still_names_the_arguments_the_llm_can_change():
    """분기 반대쪽 - 바꿀 인자가 남아 있으면 재호출 안내가 옳다.

    한쪽만 넣으면 "재호출하지 마라" 를 전 도구에 발라도 테스트가 안 잡는다.
    센서 도구는 step_seq 가 LLM 인자이므로 다른 스텝으로 다시 부르는 것이 유효하다.
    """
    from data.generate_dummy import SENSOR_STEP
    from tools import sensor_compare as sc

    original = sc.compare_sensor_distribution
    sc.compare_sensor_distribution = _boom
    try:
        ai = AIMessage(content="", tool_calls=[
            {"name": "compare_sensor_distribution",
             "args": {"step_seq": SENSOR_STEP, "reason": "센서"}, "id": "c1"}])
        out = nodes.tools_node(_pipeline_state(ai))
    finally:
        sc.compare_sensor_distribution = original

    msg = str(out["messages"][0].content)
    assert "RuntimeError" in msg
    assert "step_seq" in msg          # 무엇을 바꿔 다시 부를지 지목한다
    assert "다른 축" not in msg


def test_missing_pipeline_group_in_state_is_not_an_empty_denominator():
    """주입을 빠뜨리면 조용히 빈 분모로 도는 대신 터져야 한다.

    `test_group_arguments_are_still_required_at_invoke_time` 이 지키려던 계약이
    주입 단계에서는 안 지켜지고 있었다 - `state.get(key) or []` 가 키 누락을 빈
    리스트로 바꿔 주므로 도구는 인자를 받은 셈이 되어 예외가 안 난다.

    특히 대조군만 빠지면 결과가 `no_paired_stratum` 이고, 그 사유는 "타깃과 같은
    root_lot 에 속한 대조군 wafer 가 없다" 로 나간다(실측). 엔지니어는 대조군
    선정을 다시 하러 가고, 진짜 원인(파이프라인이 분모를 안 넣었다)은 아무 데도
    안 남는다. 조용한 오답보다 크게 죽는 편이 낫다.
    """
    import pytest

    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"}])

    # 예외 타입을 RuntimeError 로 잡는 것이 이 테스트의 절반이다. KeyError 로 두면
    # 가드를 지워도 `state[key]` 조회가 같은 KeyError 를 내므로 **가드 유무를 구분하지
    # 못한다**(축별 비대칭 훼손이 실제로 안 잡혔다). 진짜 키 누락 버그와도 안 헷갈린다.
    with pytest.raises(RuntimeError, match="target_group"):      # 둘 다 없음
        nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": []})

    with pytest.raises(RuntimeError, match="control_group"):     # 대조군만 없음
        nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": [],
                          "target_group": _PIPELINE_TARGET})     # 이력 결측 위장 쪽

    with pytest.raises(RuntimeError, match="control_group"):     # 키는 있고 값이 None
        nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": [],
                          "target_group": _PIPELINE_TARGET, "control_group": None})


def test_a_pipeline_group_that_is_present_but_empty_is_still_injected():
    """분기 반대쪽 - 빈 리스트는 '주입 누락' 이 아니라 파이프라인이 정한 값이다.

    누락과 같이 취급해 터뜨리면 대조군 부족 경로(status_node 가 이미 판정해서
    리포트로 보내는)와 겹쳐 진단이 두 곳으로 갈린다. 여기서는 그대로 넣는다.
    """
    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"}])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": [],
                            "target_group": _PIPELINE_TARGET, "control_group": []})

    assert out["findings"][0]["args"]["control_ids"] == []
    assert "오류" not in str(out["messages"][0].content)


def test_a_bad_llm_argument_is_fixable_even_when_the_tool_has_nothing_else_to_change():
    """인자 스키마 위반은 LLM 이 보낸 값이 원인이므로 재호출로 고칠 수 있다.

    "바꿀 인자가 남았는가" 만으로 안내를 가르면, hyp_* 는 reason 이 계산에 안 쓰인다는
    이유로 `_INERT_ARGS` 에 있어 **reason 형식 오류까지** "네가 바꿀 수 없다" 로 답한다.
    메시지 본문이 "reason 은 문자열이어야 한다" 를 인용하면서 고칠 수 없다고 말하는
    꼴이고, LLM 이 한 번 헛디디면 멀쩡한 축을 영구히 버린다. 원인 인자로 가른다.
    """
    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": ["문장이 아님"]},
         "id": "c1"}])
    msg = str(nodes.tools_node(_pipeline_state(ai))["messages"][0].content)

    assert "reason" in msg and "다시 호출" in msg
    assert "다른 축" not in msg          # 멀쩡한 축을 버리게 하지 않는다


def test_a_bad_injected_denominator_is_not_blamed_on_the_llm():
    """분기 반대쪽 - 같은 ValidationError 라도 주입 인자가 원인이면 LLM 소관이 아니다.

    **바꿀 인자가 남은 도구까지 봐야 한다.** hyp_* 만 잠그면 우연히 통과한다 -
    tool.args 가 {reason} 뿐이라 원인을 안 봐도 마지막 안내로 떨어지기 때문이다.
    센서 도구는 step_seq 가 남아 있어, 원인을 안 보면 "step_seq 를 고쳐 다시 부르라"
    가 나가고 LLM 은 매번 같은 자리에서 죽는 재호출을 MAX_LOOPS 까지 한다.
    """
    from data.generate_dummy import SENSOR_STEP

    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"},
        {"name": "compare_sensor_distribution",
         "args": {"step_seq": SENSOR_STEP, "reason": "센서"}, "id": "c2"},
        # 원인이 주입 인자와 LLM 인자에 걸쳐 있어도 LLM 소관이 아니다 - reason 만
        # 고쳐 다시 불러도 group_ids 에서 또 죽는다.
        {"name": "compare_sensor_distribution",
         "args": {"step_seq": SENSOR_STEP, "reason": ["문장이 아님"]}, "id": "c3"},
    ])
    out = nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": [],
                            "target_group": [None], "control_group": _PIPELINE_CONTROL})

    for tm in out["messages"]:
        msg = str(tm.content)
        assert "ValidationError" in msg
        assert "다른 축" in msg          # 네가 못 고치는 것을 고치라고 하지 않는다
        assert "다시 호출하라" not in msg
        assert "step_seq" not in msg.split(").")[-1]   # 안내에는 안 나온다


# ------------------------------------------- 실패 축: '안 돌린 축' 과 구분한다
def _crashed(tool):
    """도구가 실행 중 터졌을 때 tools_node 가 남기는 감사 기록."""
    return {"loop": 1, "tool": tool, "args": {"reason": "r"},
            "result": f"오류: {tool} 실행 실패 (RuntimeError: DB 연결 끊김). ",
            "failed": True, "thought": "r"}


_ALL_CRASHED = [_crashed(t) for t in
                ["hyp_eqp_ch_commonality", "hyp_ppid_commonality",
                 "hyp_step_passage_commonality", "hyp_metro_commonality"]]


def test_tools_node_marks_a_crashed_tool_in_the_audit_record():
    """실패 표시는 실행 자리에서 붙어야 한다 - 오류 문자열 모양으로 넘겨짚지 않는다.

    `build_bundle` 은 findings 만 본다. 표시가 없으면 실패와 "분석 종료로 생략"
    같은 다른 문자열 결과를 가를 방법이 없다.
    """
    from domain import engine

    original = engine.evaluate
    engine.evaluate = _boom
    try:
        ai = AIMessage(content="", tool_calls=[
            {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"}])
        out = nodes.tools_node(_pipeline_state(ai))
    finally:
        engine.evaluate = original

    assert out["findings"][0]["failed"] is True


def test_a_successful_tool_carries_no_failure_mark():
    """분기 반대쪽 - 성공한 실행에 표시가 붙으면 멀쩡한 축이 장애로 보고된다."""
    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"}])
    out = nodes.tools_node(_pipeline_state(ai))
    assert "failed" not in out["findings"][0]


def test_coverage_counts_crashed_axes_apart_from_the_ones_never_tried():
    """실패 축이 unrun 에 섞이면 커버리지가 '아직 안 봤다' 로 거짓말한다.

    조치가 다르다: unrun 은 "더 볼 수 있다", 실패는 "인프라를 확인하라".
    """
    bundle = nodes.evidence.build_bundle(
        [_crashed("hyp_metro_commonality"), _ALL_NO_PAIR[0]])
    coverage = nodes._coverage(bundle)
    assert coverage["failed"] == ["hyp_metro_commonality"]
    assert "hyp_metro_commonality" not in coverage["unrun"]
    assert "hyp_ppid_commonality" in coverage["unrun"]      # 진짜 안 돌린 축은 남는다
    phrase = nodes._coverage_phrase(coverage)
    assert "도구 실패" in phrase
    # 분모는 등록 축 전부다 - 실패 축을 빼면 "3개 중 1개" 가 되어 장애가 사라진다.
    assert "등록 축 4개 중 1개 대조" in phrase


def test_gate_does_not_order_the_llm_to_call_back_the_tools_that_just_crashed():
    """안내와 게이트가 모순되면 안 된다 - 방금 터진 도구 이름을 다시 대면 라이브락이다.

    도구 실패 안내(`_tool_error_message`)는 "다른 축이나 finalize" 라고 하는데,
    그것을 따른 LLM 이 게이트에서 반려되면서 **같은 도구를 부르라**는 목록을 받았다.
    실패 축이 `unrun` 에 남아 있던 것이 원인이다.
    """
    ai = _ai_finalize(0.9, claim_id="지어낸_ID")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": list(_ALL_CRASHED)})
    msg = out["messages"][0].content
    assert "finalize_accepted" not in out
    assert "가설 도구로 두 그룹을 먼저 대조하라" not in msg   # 부를 것이 없다
    assert "claim_id 를 비우" in msg                          # 물러설 길은 열려 있다


def test_gate_declares_tool_failure_when_every_axis_crashed():
    """전 축이 터지면 종료 사유는 '도구 실패' 다 - 루프 한계까지 왕복시키지 않는다.

    `no_comparable_data`("적재 범위를 확인하라")로 내보내면 **틀린 조치**다.
    진실은 조회가 실패한 것(인프라)이지 볼 데이터가 없는 것이 아니다.
    """
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1,
                            "findings": list(_ALL_CRASHED)})
    assert out["finalize_accepted"] is True
    assert out["finalize_status"] == "tool_failure"
    assert out["coverage"]["failed"] == sorted(f["tool"] for f in _ALL_CRASHED)


def test_gate_calls_a_partial_crash_a_crash_not_missing_data():
    """일부만 터지고 나머지가 계산 불가여도 사유는 '도구 실패' 다.

    두 사실이 다 참이지만 조치가 갈린다 - 축을 다 보지 못한 채 "적재 범위를
    확인하라" 를 내보내면 엔지니어는 멀쩡한 적재를 뒤진다. 막고 있는 것이 먼저다.
    """
    findings = [_crashed("hyp_eqp_ch_commonality"), _crashed("hyp_ppid_commonality"),
                _ALL_NO_PAIR[2], _ALL_NO_PAIR[3]]
    _assert_covers_every_hypothesis(findings)
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1, "findings": findings})
    assert out["finalize_status"] == "tool_failure"


def test_gate_does_not_declare_tool_failure_while_axes_remain_unrun():
    """반대쪽 경계 - 아직 안 돌린 축이 있으면 도구 실패로 끝내지 않는다.

    한 축이 터졌다고 물러서면 데이터가 있는 축을 한 번도 안 건드린 채 인프라
    점검을 시킨다. (3)번이 전축을 요구하는 것과 같은 이유다.
    """
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1,
                            "findings": [_crashed("hyp_metro_commonality")]})
    assert "finalize_accepted" not in out


def test_gate_does_not_read_a_named_claim_as_stepping_back_on_tool_failure():
    """(2)·(3)에 붙인 하한과 대칭 - 지목을 제출한 것은 물러선 것이 아니다."""
    ai = _ai_finalize(0.95, claim_id="eqp_ch_commonality:chamber:CC002000:NOPE")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1,
                            "findings": list(_ALL_CRASHED)})
    assert "finalize_accepted" not in out


def test_gate_still_declares_no_comparable_data_when_nothing_crashed():
    """실패 축이 하나도 없으면 (3)은 그대로 열린다 - 새 분기가 옛 판정을 먹으면 안 된다."""
    _assert_covers_every_hypothesis(_ALL_NO_PAIR)
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 1,
                            "findings": list(_ALL_NO_PAIR)})
    assert out["finalize_status"] == "no_comparable_data"


def test_report_node_reports_the_crashed_axes_even_though_nothing_ran():
    """전 축이 터지면 `ran` 이 비지만, 그때야말로 커버리지 줄이 필요하다.

    "셀 것이 없는 보고서에는 붙이지 않는다" 는 규칙을 `ran` 만으로 판정하면
    장애 보고에서 커버리지가 통째로 사라진다.
    """
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "auto",
        "target_group": ["W2406_02"], "status_summary": "불량 3장",
        "findings": list(_ALL_CRASHED), "finalize_status": "tool_failure",
    })
    assert "[커버리지]" in out["report"]
    assert "도구 실패" in out["report"]


def test_report_node_marks_tool_failure_conclusion():
    """도구 실패 종료의 결론은 '적재 범위' 가 아니라 '인프라' 를 가리켜야 한다.

    `no_comparable_data`("볼 데이터가 없다 -> 적재/추출 범위 확인")와 조치가 다르다.
    문구가 같으면 엔지니어가 멀쩡한 적재를 뒤진다.
    """
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약",
        "findings": list(_ALL_CRASHED), "final_hypothesis": "", "final_confidence": 0.2,
        "finalize_status": "tool_failure",
    })
    assert "분석 미수행" in out["report"]
    assert "적재 범위" not in out["report"]
    assert "미확정" not in out["report"]


def test_gate_does_not_claim_every_axis_ran_when_some_of_them_crashed():
    """반려 안내의 "등록 가설을 다 돌렸다" 는 실패 축이 있으면 거짓이다.

    돌아간 축이 계산은 됐지만 약한 후보만 냈고 나머지가 터진 상태 - (3b)는 안
    열린다(계산이 성립한 축이 있다). 그래도 안내는 사실이어야 하고, 방금 터진
    도구를 다시 부르라고 이름을 대서도 안 된다.
    """
    # status 는 no_signal 이 아니라 ok 다 - no_signal 이면 (2)가 열려 승인으로 빠져
    # 나가고, 이 테스트는 반려 안내를 한 글자도 못 본 채 초록이 된다.
    # 후보 score 도 이 테스트 안에서 아랫선(RESIDUAL_MIN_SCORE) 아래로 덮어쓴다
    # (원본 `_WEAK_IN_SILENCE` 는 다른 테스트가 쓰므로 건드리지 않는다) - 원본 점수
    # 0.4 그대로면 (2a)가 열려 반려 경로 자체를 안 타 이 테스트가 잠그려는 "실패
    # 축을 안 돌렸다고 거짓말하지 않는다" 를 시험할 수 없게 된다.
    weak_ok = {**_WEAK_IN_SILENCE,
               "result": {**_WEAK_IN_SILENCE["result"], "status": "ok",
                          "candidates": [{**_WEAK_IN_SILENCE["result"]["candidates"][0],
                                          "score": 0.2, "reject_reason": "분리 점수 0.2 < 0.5",
                                          "control_pass": 4}]}}
    findings = [weak_ok, _crashed("hyp_ppid_commonality"),
                _crashed("hyp_step_passage_commonality"),
                _crashed("hyp_metro_commonality")]
    _assert_covers_every_hypothesis(findings)
    ai = _ai_finalize(0.9, claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": findings})
    assert "finalize_accepted" not in out          # 반려 경로를 실제로 탔는지 못박는다
    msg = out["messages"][0].content
    assert "등록 가설을 다 돌렸으나" not in msg
    assert "도구 실패로 미수행" in msg
    assert "아직 안 돌린 가설 도구" not in msg    # 부를 수 있는 축은 없다


# --------------------------------------- 재리뷰: 복구 가능한 인자 오류는 실패가 아니다
def test_a_recoverable_argument_error_does_not_burn_the_axis():
    """LLM 이 고칠 수 있는 인자 오류를 '도구 실패' 로 굳히면 멀쩡한 축을 영구히 버린다.

    `_tool_error_message` 는 이미 "LLM 이 아직 바꿀 수 있는 인자가 있는가" 를 갈라
    reason 형식 오류에는 "고쳐서 다시 호출하라" 고 답한다. 그런데 감사 기록에는
    실패로 찍혀 축이 `failed` 에 끈적하게 남으면, 안내는 재호출을 시키고 게이트는
    "부를 축이 없다" 로 끝내는 **거울상 모순**이 된다 - 이 커밋이 없애려던 바로 그것.
    """
    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": 123}, "id": "c1"}])
    out = nodes.tools_node(_pipeline_state(ai))
    assert "고쳐서 다시 호출하라" in str(out["messages"][0].content)
    assert "failed" not in out["findings"][0]


def test_an_argument_error_the_llm_cannot_fix_is_still_a_failure():
    """분기 반대쪽 - 원인이 주입 인자면 LLM 이 고칠 수 없으니 실패가 맞다.

    한쪽만 넣으면 "인자 오류는 실패가 아니다" 를 전 경로에 발라도 안 잡힌다.
    """
    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": "챔버"}, "id": "c1"}])
    out = nodes.tools_node(_pipeline_state(ai, target_group=[123]))   # 분모가 깨졌다
    assert "다른 축" in str(out["messages"][0].content)   # 재호출을 안 시킨다
    assert out["findings"][0]["failed"] is True


def test_a_recoverable_argument_error_does_not_end_the_analysis():
    """같은 사실의 판정 쪽 - reason 한 번 헛디딘 것이 tool_failure 종료가 되면 안 된다."""
    ai = AIMessage(content="", tool_calls=[
        {"name": "hyp_eqp_ch_commonality", "args": {"reason": 123}, "id": "c1"}])
    bad = nodes.tools_node(_pipeline_state(ai))["findings"][0]
    fin = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [fin], "loop_count": 3,
                            "findings": _ALL_NO_PAIR[1:] + [bad]})
    assert out.get("finalize_status") != "tool_failure"


# ------------------------------- 재리뷰: unrun 에 매달려 있던 유보가 꺼지면 안 된다
def test_partial_coverage_hedge_survives_when_the_axes_crashed():
    """실패 축을 unrun 에서 빼면서 '돌린 축에 한한다' 유보가 조용히 꺼졌다.

    4축 중 3축이 DB 장애로 못 돈 상태인데 게이트가 전축을 본 것처럼
    "lot 내부 대조로는 원인을 좁힐 수 없다" 는 확정 톤 문장을 냈다. 이 문자열은
    findings 로 리포트 LLM 에 그대로 넘어가고 프롬프트는 "그대로 인용하라" 고 한다.
    """
    metro_silent = {"loop": 2, "tool": "hyp_metro_commonality", "args": {},
                    "result": {"hypothesis_id": "metro_commonality",
                               "status": "no_signal", "candidates": []},
                    "thought": "신호 없음"}
    findings = [_crashed("hyp_eqp_ch_commonality"), _crashed("hyp_ppid_commonality"),
                _crashed("hyp_step_passage_commonality"), metro_silent]
    _assert_covers_every_hypothesis(findings)
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": findings})
    assert out["finalize_status"] == "no_signal"
    msg = out["messages"][0].content
    assert "결론은 돌린 축에 한한" in msg
    assert "lot 내부 대조로는" not in msg          # 전축을 본 것처럼 말하지 않는다


def test_coverage_does_not_count_a_non_hypothesis_tool_as_a_failed_axis():
    """센서 등 축이 아닌 도구의 실패가 커버리지·판정을 흔들면 안 된다.

    `_coverage` 의 `registered &` 가드가 지키는 것이다 - 없으면 센서 하나가 터진 것이
    (3)을 막고 (3b)를 열어 종료 사유가 뒤집히고 분모까지 5로 늘어난다.
    """
    findings = list(_ALL_NO_PAIR) + [_crashed("compare_sensor_distribution")]
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": findings})
    assert out["coverage"]["failed"] == []
    assert out["finalize_status"] == "no_comparable_data"
    assert "등록 축 4개" in nodes._coverage_phrase(out["coverage"])


def test_full_coverage_no_signal_does_not_hedge_a_conclusion_it_earned():
    """분기 반대쪽 - 정말로 전축을 봤으면 유보를 달지 않는다.

    유보 조건을 넓히다가 항상 켜지게 만들면, 4축을 다 대조하고 얻은 결론까지
    "돌린 축에 한한다" 로 낮춰 엔지니어가 근거를 저평가한다. 이 분기는 저장소에
    테스트가 한 건도 없어 훼손이 그대로 살아남던 자리다.
    """
    silent = [{"loop": 2, "tool": t, "args": {},
               "result": {"hypothesis_id": h, "status": "no_signal", "candidates": []},
               "thought": "신호 없음"}
              for t, h in [("hyp_eqp_ch_commonality", "eqp_ch_commonality"),
                           ("hyp_ppid_commonality", "ppid_commonality"),
                           ("hyp_step_passage_commonality", "step_passage_commonality"),
                           ("hyp_metro_commonality", "metro_commonality")]]
    _assert_covers_every_hypothesis(silent)
    ai = _ai_finalize(0.2, hypothesis="", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": silent})
    assert out["finalize_status"] == "no_signal"
    msg = out["messages"][0].content
    assert "분리되는 후보 없음" in msg
    assert "결론은 돌린 축에 한한" not in msg


def _rank_cand(claim_id, key, step, score, p, floor, wafer):
    return {"claim_id": claim_id, "level": "chamber", "step_seq": step, "key": key,
            "passes": True, "reject_reason": None, "score": score,
            "target_pass": 2, "target_total": 6,
            "control_pass": 0, "control_total": 6,
            "p_permutation": p, "p_min_possible": floor,
            "target_wafers": [wafer], "control_wafers": []}


def _rank_finding(tool, hypothesis_id, cands, loop=1):
    return {"loop": loop, "tool": tool, "args": {}, "thought": "t",
            "result": {"hypothesis_id": hypothesis_id, "status": "ok",
                       "candidates": cands}}


def test_gate_approves_any_member_of_the_first_layer():
    """1등 층 안이면 정렬상 맨 앞이 아니어도 승인한다.

    예전 계약은 `groups[0]` 과 우열 키가 같은지를 물었다. 새 규칙에서는 등수가
    같아도 키가 다를 수 있다 - 바닥이 다른 두 후보는 p 가 달라도 동점이다. 키로
    물으면 동점이라고 리포트에 적어 놓고 게이트는 반려하는 모순이 난다.
    """
    findings = [
        _rank_finding("hyp_a", "a",
                      [_rank_cand("a:1", "TINY_P", "CC001000", 0.55, 0.002, 0.003, "W1")]),
        _rank_finding("hyp_b", "b",
                      [_rank_cand("b:1", "AT_FLOOR", "CC002000", 1.0, 0.111, 0.111, "W2")],
                      loop=2),
    ]
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "b:1", "hypothesis": "바닥에 걸린 쪽", "confidence": 0.9},
        1, update, findings)
    assert update.get("finalize_status") == "confirmed", verdict
    assert any(c.get("picked_by_llm") for c in update["final_claims"])


def test_gate_rejection_names_the_candidate_that_actually_beat_it():
    """반려는 **실제로 이긴 근거**를 대야 한다 - 정렬상 1등이 아니라.

    `a:1` 은 p 가 가장 작아 목록 맨 앞이지만 지목(`b:lo`)을 **이기지 못한다** -
    공통 해상도 0.111 에서 둘 다 그 이하로 내려가 갈리지 않고, 축이 달라 점수로도
    못 가른다. 실제로 이긴 것은 같은 축에서 분리 점수가 더 높은 `b:hi` 다.
    맨 앞을 그냥 집어 대면 LLM 은 자기가 왜 졌는지 못 읽고, 이기지도 않은 후보로
    지목을 옮겼다가 다시 반려당한다. 바닥도 함께 인용해야 두 숫자를 같이 읽는다.
    """
    findings = [
        _rank_finding("hyp_a", "a",
                      [_rank_cand("a:1", "TINY_P", "CC001000", 0.55, 0.002, 0.003, "W1")]),
        _rank_finding("hyp_b", "b", [
            _rank_cand("b:hi", "AT_FLOOR_HI", "CC002000", 0.9, 0.111, 0.111, "W2"),
            _rank_cand("b:lo", "AT_FLOOR_LO", "CC003000", 0.6, 0.111, 0.111, "W3"),
        ], loop=2),
    ]
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "b:lo", "hypothesis": "같은 축에서 진 쪽", "confidence": 0.9},
        1, update, findings)
    assert "finalize_status" not in update           # 반려는 종료가 아니다
    assert "b:hi" in verdict and "바닥" in verdict
    assert "a:1" not in verdict                      # 맨 앞은 이 후보를 이기지 않았다


def test_gate_does_not_tell_a_first_layer_pick_that_it_lost():
    """1등 층 후보가 확신도로 반려될 때 "졌다" 고 말하면 안 된다.

    `b:1` 은 정렬상 맨 앞이 아니지만 등수는 1등이다 - 공통 해상도에서 `a:1` 과
    갈리지 않는다. 옛 계약처럼 맨 앞과 키가 같은지로 물으면 여기서 순위 반려가
    나가고, LLM 은 **이기지도 않은 후보로 지목을 옮긴 뒤 같은 이유로 또 반려**
    당한다. 부족한 것이 순위가 아니라 확신도일 때는 그렇게 말해야 고칠 수 있다.
    """
    findings = [
        _rank_finding("hyp_a", "a",
                      [_rank_cand("a:1", "TINY_P", "CC001000", 0.55, 0.002, 0.003, "W1")]),
        _rank_finding("hyp_b", "b",
                      [_rank_cand("b:1", "AT_FLOOR", "CC002000", 1.0, 0.111, 0.111, "W2")],
                      loop=2),
    ]
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "b:1", "hypothesis": "바닥에 걸린 쪽", "confidence": 0.5},
        1, update, findings)
    assert "finalize_status" not in update           # 확신도 미달이라 승인은 아니다
    assert "확신도" in verdict, verdict
    assert "졌다" not in verdict, verdict            # 순위로 반려한 것이 아니다


# ---------------------------------------------------------------------------
# 센서는 근거로는 실리되 승인 지목 대상이 아니다 (Task 4)
# ---------------------------------------------------------------------------

def test_gate_does_not_confirm_on_a_sensor_claim():
    """센서는 인용 가능하되 지목 불가다.

    다중비교 보정을 일부러 안 한 도구(스텝당 센서 수백 개)를 단독 승인 근거로 열면
    1단이 빈손일 때 효과크기 하나로 confirmed 가 나가는 거짓 양성 기계가 된다.
    """
    update = {}
    nodes._finalize_gate(
        {"claim_id": "sensor:CC002000:TEMP_1", "hypothesis": "온도", "confidence": 0.95},
        loop=2, update=update, findings=[EQP_CH_SILENT, SENSOR_FINDING])
    assert update.get("finalize_accepted") is None
    assert update.get("finalize_status") != "confirmed"


def test_sensor_only_state_can_still_step_back():
    """**라이브락 방지.** 센서만 통과하면 승인은 막히는데 물러섬까지 막히면 LLM 은
    할 일이 없어 루프 한계까지 왕복하다 inconclusive 로 끝난다 - 근거를 살리려던
    변경이 종료 경로를 막는 것이다.
    """
    update = {}
    nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "센서로도 못 좁혔다", "confidence": 0.4},
        loop=2, update=update, findings=[EQP_CH_SILENT, SENSOR_FINDING])
    assert update["finalize_status"] == "no_signal"
    assert update["finalize_accepted"] is True


def test_sensor_evidence_rides_along_in_final_claims():
    """물러서도 센서 근거는 리포트에 실린다 - 그것이 이번 변경의 목적이다."""
    update = {}
    nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.4},
        loop=2, update=update, findings=[EQP_CH_SILENT, SENSOR_FINDING])
    ids = [c["claim_id"] for c in update["final_claims"]]
    assert "sensor:CC002000:TEMP_1" in ids


def test_statistical_claim_outranks_a_sensor():
    """**통계 등급** 후보가 있으면 센서는 2등 이하다 (2026-09-01 확정한 등급 계약).

    픽스처로 `EVIDENCE_FINDING_NEW`(2x2 만 있고 순열 통계가 없다)를 쓰면 이 계약을
    못 잠근다 - `_is_statistical` 이 False 라 센서와 **같은 비통계 등급**이 되고,
    그러면 `dominates` 의 센서 하한에 걸려 둘이 동점으로 나온다. 센서를 밀어내는
    것은 '1단이라는 사실' 이 아니라 **순열 근거를 냈다는 사실**이다.
    """
    findings = [
        _rank_finding("hyp_a", "a",
                      [_rank_cand("a:1", "ETCH9_B", "CC002000", 0.55, 0.002, 0.003, "W1")]),
        SENSOR_FINDING,
    ]
    update = {}
    nodes._finalize_gate(
        {"claim_id": "a:1", "hypothesis": "h", "confidence": 0.9},
        loop=2, update=update, findings=findings)
    assert update["finalize_status"] == "confirmed"
    ranks = {c["claim_id"]: c["rank"] for c in update["final_claims"]}
    assert ranks["a:1"] == 1
    assert ranks["sensor:CC002000:TEMP_1"] > 1


def test_gate_rejects_a_picked_sensor_by_name_not_by_confidence():
    """센서를 지목하면 **그 이유로** 반려해야 한다.

    게이트 (1) 에 kind 하한만 걸고 반려 쪽에 분기를 안 두면, 통과한 1등 센서를
    지목한 제출이 아래 확신도 줄까지 굴러떨어져 "확신도 0.95 < 0.8" 이라는 거짓말이
    나간다. 판정 (2)·(3)·(3b)는 전부 `not claim_id` 를 요구하므로 종료도 안 열리고,
    LLM 은 고칠 것이 없는 반려를 받아 루프 한계까지 왕복하다 inconclusive 로 끝난다 -
    `statistical_passing()` 이 막으려던 라이브락이 claim_id 를 **낸** 경로로 되살아난다.

    **(2a) 는 예외이므로 픽스처가 잔차를 안 남긴다.** 하한이 "정직한 제출" 로
    넓어진 뒤로는, 통과 후보가 없고 아랫선을 넘은 잔차가 있으면 센서 지목이
    `(2a) weak_signal` 로 먼저 받아져 이 반려 분기에 **도달조차 하지 않는다**.
    `EQP_CH_SILENT` 는 candidates 가 비어 있어 `residuals()` 가 0건이고, 그래서
    이 테스트가 겨누는 반려 경로가 실제로 돈다. 픽스처를 잔차 있는 것으로 바꾸면
    이 테스트는 겨누던 자리를 잃는다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "sensor:CC002000:TEMP_1", "hypothesis": "온도", "confidence": 0.95},
        loop=2, update=update, findings=[EQP_CH_SILENT, SENSOR_FINDING])
    assert "확신도" not in verdict, verdict          # 확신도는 0.95 다 - 모자란 적이 없다
    assert "센서" in verdict, verdict
    assert "claim_id 를 비우고" in verdict, verdict  # 물러설 길을 안내한다


def test_a_failing_sensor_is_also_rejected_as_unpickable_not_as_below_the_line():
    """**분기를 `not claim.passes` 보다 앞에 둔다** (계획서는 뒤라고 적었다).

    미통과 센서에 "판별선을 넘지 못했다 (효과크기 0.4 < 0.8). 통과한 후보를
    지목하라" 를 돌려주면 둘 다 사실이지만 **넘었으면 지목할 수 있다**는 거짓을
    함께 말한다 - 센서를 다시 돌려 큰 d 를 찾아오면 된다고 읽히고, 그러면 같은
    반려를 한 바퀴 더 받는다. 지목 불가는 판별선보다 앞선 사실이다.
    """
    failing = {**SENSOR_FINDING, "result": {
        **SENSOR_FINDING["result"],
        "candidates": [{**SENSOR_FINDING["result"]["candidates"][0],
                        "passes": False, "effect_size": 0.4,
                        "reject_reason": "효과크기 0.4 < 0.8"}]}}
    verdict = nodes._finalize_gate(
        {"claim_id": "sensor:CC002000:TEMP_1", "hypothesis": "h", "confidence": 0.9},
        loop=2, update={}, findings=[EQP_CH_SILENT, failing])
    assert "2단 센서" in verdict, verdict
    assert "판별선" not in verdict, verdict
    assert "통과한 후보를 지목하라" not in verdict, verdict


def test_rejection_of_a_picked_sensor_names_the_statistical_candidates():
    """1단 통과 후보가 있으면 그것을 대야 한다.

    순위 반려 문구로 흘려보내면 센서가 내지도 않은 'p None' 을 인용하고, 효과크기
    2.31 을 분리 점수 0.55 와 나란히 "점수" 로 놓아 **센서가 더 센데 규칙 때문에
    졌다**로 읽힌다 - LLM 은 같은 지목을 다시 낸다.
    """
    findings = [
        _rank_finding("hyp_a", "a",
                      [_rank_cand("a:1", "ETCH9_B", "CC002000", 0.55, 0.002, 0.003, "W1")]),
        SENSOR_FINDING,
    ]
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "sensor:CC002000:TEMP_1", "hypothesis": "h", "confidence": 0.9},
        loop=2, update=update, findings=findings)
    assert "a:1" in verdict, verdict
    assert "p None" not in verdict, verdict
    assert "졌다" not in verdict, verdict


def test_gate_does_not_offer_sensors_as_pickable_candidates():
    """지목 불가한 것을 '통과 후보' 로 안내하면 LLM 이 골라 제출하고 또 반려당한다."""
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "지어낸:claim:id", "hypothesis": "h", "confidence": 0.9},
        loop=2, update=update, findings=[EQP_CH_SILENT, SENSOR_FINDING])
    assert "sensor:CC002000:TEMP_1" not in verdict


# 1단이 후보를 냈으나 판별선을 못 넘은 상태. status 는 ok 다 - no_signal 로 두면
# 게이트 (2)가 열려 반려가 아니라 종료를 시험하게 된다.
EQP_CH_BELOW_LINE = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
    "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
         "key": "ETCH9_B", "level": "chamber", "passes": False,
         "reject_reason": "분리 점수 0.4 < 0.5", "score": 0.4,
         "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5},
    ]},
    "thought": "약한 후보",
}

# 같은 축(같은 tool 실행)이 통과 후보와 잔차 자격을 갖춘 미통과 후보를 함께 낸 상태.
# (2a)의 첫 조건 `not bundle.statistical_passing()` 을 시험하려면 통과 후보가
# **실재해야** 한다 - 없으면 그 조건이 참이든 거짓이든 결과가 같아 무엇을 잠그는지
# 알 수 없다.
EQP_CH_PASSING_AND_RESIDUAL = {
    "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
    "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
         "key": "ETCH9_B", "level": "chamber", "passes": True,
         "reject_reason": None, "score": 1.0,
         "target_pass": 3, "target_total": 3, "control_pass": 0, "control_total": 3},
        {"claim_id": "eqp_ch_commonality:chamber:CD004000:PHOTO1_A", "step_seq": "CD004000",
         "key": "PHOTO1_A", "level": "chamber", "passes": False,
         "reject_reason": "분리 점수 0.4 < 0.5", "score": 0.4,
         "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5},
    ]},
    "thought": "챔버 편중 + 약한 후보",
}


def _weak_finding(tool, hyp, claim_id, loop, score):
    """status 는 ok 이고 **점수는 호출자가 정하는** 후보 하나짜리 실행.

    `status: "ok" if candidates else "no_signal"`(tools/commonality.py) 이므로
    ok 는 곧 "후보가 났다" 이다. **점수는 호출자가 정한다** - 아랫선(0.25) 아래면
    잔차 자격이 없고, 위면 잔차가 된다(`PPID_BELOW_LINE` 이 후자를 일부러 쓴다).
    """
    return {
        "loop": loop, "tool": tool, "args": {},
        "result": {"hypothesis_id": hyp, "status": "ok", "candidates": [
            {"claim_id": claim_id, "step_seq": "CC002000", "key": "K",
             "level": "chamber", "passes": False,
             "reject_reason": f"분리 점수 {score} < 0.5", "score": score,
             "target_pass": 4, "target_total": 4,
             "control_pass": 3, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }


# 전축을 다 돌렸는데 후보가 전부 아랫선 미만인 상태 (M4). 최고 점수는 0.18 이다 -
# 하나만 다른 값을 주어야 판정문이 '최고' 를 실제로 고르는지 잠글 수 있다.
ALL_WEAK = [
    _weak_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                  "eqp_ch_commonality:chamber:CC002000:ETCH9_B", 2, 0.18),
    _weak_finding("hyp_ppid_commonality", "ppid_commonality",
                  "ppid_commonality:ppid:CC002000:P1", 3, 0.10),
    _weak_finding("hyp_step_passage_commonality", "step_passage_commonality",
                  "step_passage_commonality:step:CC002000:S1", 4, 0.10),
    _weak_finding("hyp_metro_commonality", "metro_commonality",
                  "metro_commonality:item:CC002000:M1", 5, 0.10),
]


def _thin_finding(tool, hyp, claim_id, loop):
    """status 는 ok · 분리 점수 1.0(완전 분리)인데 타깃 표본이 1장뿐이라 미통과인
    후보 하나짜리 실행.

    `domain/engine.py:_passes` 가 실제로 이 모양을 낸다 - `target_pass < min_target`
    (`COMMONALITY_PASS_MIN_TARGET`, 기본 2)이면 점수와 무관하게 반려하고
    `reject_reason` 에 "타깃 표본 N < 2" 를 남긴다. 점수가 잔차 아랫선(0.25)을
    한참 넘기므로 `bundle.residuals()` 는 이 후보를 담지 못한다(그 함수가
    `target_pass >= COMMONALITY_PASS_MIN_TARGET` 도 함께 요구하기 때문) - 그래서
    "잔차가 없다" 를 "안 갈렸다" 의 증거로 쓰면 거짓이 된다(M4 재리뷰 Critical).
    """
    return {
        "loop": loop, "tool": tool, "args": {},
        "result": {"hypothesis_id": hyp, "status": "ok", "candidates": [
            {"claim_id": claim_id, "step_seq": "CC002000", "key": "K",
             "level": "chamber", "passes": False,
             "reject_reason": "타깃 표본 1 < 2", "score": 1.0,
             "target_pass": 1, "target_total": 1,
             "control_pass": 0, "control_total": 5},
        ]},
        "thought": "완전 분리, 얇은 표본",
    }


# 전축을 다 돌렸고 후보가 완전히 갈렸는데(score 1.0) 표본이 얇아 미통과인 상태.
# `bundle.residuals()` 에도 안 잡히므로 `not bundle.residuals()` 를 "안 갈렸다" 의
# 대용으로 쓰면 이 상태를 M4 로 잘못 받아들인다 - (2b)는 이 상태를 **열면 안 된다**.
ALL_THIN = [
    _thin_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                  "eqp_ch_commonality:chamber:CC002000:ETCH9_B", 2),
    _thin_finding("hyp_ppid_commonality", "ppid_commonality",
                  "ppid_commonality:ppid:CC002000:P1", 3),
    _thin_finding("hyp_step_passage_commonality", "step_passage_commonality",
                  "step_passage_commonality:step:CC002000:S1", 4),
    _thin_finding("hyp_metro_commonality", "metro_commonality",
                  "metro_commonality:item:CC002000:M1", 5),
]


def test_a_below_the_line_pick_is_not_told_to_pick_when_only_a_sensor_passed():
    """미통과 1단을 정직하게 지목했는데 통과한 것이 **센서뿐**인 상태.

    `passing()` 으로 보면 통과 후보가 있으니 "통과한 후보를 지목하라" 가 나가는데,
    통과한 것은 지목할 수 없는 센서뿐이라 실행할 수 없는 지시다 - 게이트 (2)의
    하한을 `statistical_passing()` 으로 옮겨 막은 라이브락이 이 한 문장으로
    되살아난다. 이 자리는 훼손 실험에서 빠져 있어 되돌려도 스위트가 초록이었다.

    잠그는 규칙은 "반려 안내가 거짓말(실행 불가능한 지시)을 하지 않는다" 로 (2a)
    하한 확장과 무관하다. 그런데 공용 픽스처 `EQP_CH_BELOW_LINE` 의 점수(0.4)가
    잔차 자격(>=0.25)을 만족해, 하한이 넓어진 뒤로는 이 지목이 반려를 거치지 않고
    바로 weak_signal 로 빠진다 - 원래 경로를 잠그려면 여기만 점수를 잔차 하한
    아래로 낮춘 사본을 쓴다(공용 픽스처는 그대로 둔다 - 다른 테스트가 잔차 존재를
    전제한다).
    """
    below_line_no_residual = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": False,
             "reject_reason": "분리 점수 0.1 < 0.5", "score": 0.1,
             "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.9},
        loop=2, update={}, findings=[below_line_no_residual, SENSOR_FINDING])
    assert "판별선을 넘지 못했다" in verdict, verdict
    assert "통과한 후보를 지목하라" not in verdict, verdict
    assert "아직 안 돌린 가설 도구" in verdict, verdict      # 다음 행동을 안내한다


def test_a_missing_claim_id_is_not_offered_a_sensor_either():
    """claim_id 미제출 반려도 지목 불가한 것을 목록에 넣으면 안 된다.

    지어낸 claim_id 쪽(`test_gate_does_not_offer_sensors_as_pickable_candidates`)만
    잠그면 문구가 거의 같은 이 자리가 조용히 되돌아가도 안 보인다.
    """
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.9},
        loop=2, update={}, findings=[EQP_CH_BELOW_LINE, SENSOR_FINDING])
    assert "sensor:CC002000:TEMP_1" not in verdict, verdict
    assert "claim_id 를 제출하지 않았다" not in verdict, verdict   # 지목할 것이 없다


def test_a_weak_only_state_ends_as_weak_signal():
    """약한 신호와 무신호가 같은 출력이던 것을 가른다.

    지금은 (2)(3)(3b) 어느 것도 안 열려 루프 한계까지 왕복하다 inconclusive 로 끝나고
    final_claims 는 빈 목록이다 - '봤고 후보도 났는데 약하다' 가 통째로 소각된다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=2, update=update, findings=[EQP_CH_BELOW_LINE])
    assert update["finalize_status"] == "weak_signal"
    assert update["finalize_accepted"] is True
    ids = [c["claim_id"] for c in update["final_claims"]]
    assert ids == ["eqp_ch_commonality:chamber:CC002000:ETCH9_B"]
    assert "잔차" in verdict
    # 건수 자체를 잠근다 - "잔차" 라는 단어만 있고 몇 건인지는 안 세면, 개수를
    # 지워도(예: "아랫선을 넘은 잔차를 근거로 싣는다") 스위트가 초록이다.
    assert "잔차 1건" in verdict, verdict
    # 커버리지 고백도 잠근다 - 안 붙이면 "어디까지 봤는가" 가 이 종료 경로에서만
    # 조용히 빠져도 스위트가 초록이다.
    assert "hyp_metro_commonality" in update["coverage"]["unrun"]
    assert "안 돌린 축 3개" in verdict


def test_a_named_residual_still_ends_as_weak_signal():
    """지목했다는 이유만으로 잔차를 태우지 않는다.

    (2a)의 하한이 `not claim_id` 이던 동안에는, LLM 이 약한 후보를 지목하는 순간
    이 문이 닫혀 (5) 반려로 갔다. 반려를 되풀이하면 루프 한계에서 inconclusive +
    final_claims=[] 로 끝나 잔차가 소각된다 - 이 기능이 없애려던 바로 그 상태다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "ETCH9_B 편중", "confidence": 0.9},
        loop=2, update=update, findings=[EQP_CH_BELOW_LINE])
    assert update["finalize_status"] == "weak_signal"
    assert update["finalize_accepted"] is True
    ids = [c["claim_id"] for c in update["final_claims"]]
    assert ids == ["eqp_ch_commonality:chamber:CC002000:ETCH9_B"]
    # 지목을 받아준 것이지 원인으로 확정한 것이 아니다 - 판정문이 그렇게 말해야
    # LLM 이 서술에서 그 후보를 단정하지 않는다.
    assert "원인으로 확정하지 않았다" in verdict, verdict
    # 이 갈래(미통과)만의 문구를 잠근다 - "원인으로 확정하지 않았다" 는 센서
    # 갈래에도 그대로 나오므로, 그것만 걸면 이 갈래가 "판별선을 넘어" 로 뒤집혀도
    # (통과했다는 거짓말) 스위트가 초록이다.
    assert "판별선을 넘지 못해" in verdict, verdict
    # 확정하지 않기로 했으므로 picked 표시를 안 붙인다.
    assert not any(c.get("picked_by_llm") for c in update["final_claims"])


# 잔차 자격을 갖춘 후보를 내는 두 번째 축 - eqp 축이 대체되어도 잔차가 남아 있어야
# `(2a)` 의 `residuals` 조건이 살아 있다. 이것이 없으면 대체와 동시에 잔차가 사라져
# 무엇이 문을 닫았는지 가려지지 않는다.
PPID_BELOW_LINE = _weak_finding("hyp_ppid_commonality", "ppid_commonality",
                                "ppid_commonality:ppid:CC002000:P1", 3, 0.40)


def test_a_superseded_claim_id_opens_weak_signal():
    """대체된 앞 실행의 후보를 지목한 것은 **환각이 아니다** - 하한이 그것도 받는다.

    `tools_node` 가 도구 결과를 ToolMessage 로 대화에 실으므로, 축을 다시 돌린 뒤에도
    LLM 은 앞 실행의 claim_id 를 자기 문맥에서 그대로 보고 제출한다. `bundle.claims`
    는 대체된 후보를 안 담아서, 옛 하한(`claim is not None`)은 그 제출을 환각과 **같이**
    반려했다. 손해가 왕복 1회로 끝나지 않는 자리가 있다 - 루프 한계에 닿으면 같은
    증거가 제출 형태만 다르다는 이유로 사유가 달라진다(아래 루프 한계 시험).
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "ETCH9_B 편중", "confidence": 0.9},
        loop=2, update=update,
        findings=[EQP_CH_BELOW_LINE, PPID_BELOW_LINE, EQP_CH_RERUN_SILENT])
    assert update["finalize_status"] == "weak_signal"
    assert update["finalize_accepted"] is True
    # 대체 갈래는 **따로** 말해야 한다 - 대체된 후보는 통과했던 것일 수도 있어
    # (M3 의 EVIDENCE_FINDING_NEW 가 그 모양이다) "판별선을 넘지 못해" 로 뭉개면
    # 거짓이 된다. 무엇이 대체했는지 이름도 댄다(`dropped_claims` 가 들고 있다).
    assert ("네가 지목한 eqp_ch_commonality:chamber:CC002000:ETCH9_B 는 "
            "hyp_eqp_ch_commonality 를 다시 돌려 대체된 앞 실행의 후보라 원인으로 "
            "확정하지 않았다.") in verdict, verdict
    assert "판별선을 넘지 못해" not in verdict, verdict
    # 확정하지 않기로 했으므로 picked 표시는 여전히 안 붙는다.
    assert not any(c.get("picked_by_llm") for c in update["final_claims"])


def test_a_named_passing_sensor_ends_as_weak_signal():
    """지목할 수 있는 것이 하나도 없는 상태에서 반려는 왕복만 만든다.

    1단이 아무것도 못 갈랐고 2단 센서만 통과한 상태다. 여기서 "센서는 지목 대상이
    아니다" 를 돌려줘도 LLM 이 대신 고를 것이 없다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "sensor:CC002000:TEMP_1",
         "hypothesis": "TEMP_1 이상", "confidence": 0.9},
        loop=2, update=update, findings=[EQP_CH_BELOW_LINE, SENSOR_FINDING])
    assert update["finalize_status"] == "weak_signal"
    # 센서는 판별선을 **넘었다** - "판별선을 넘지 못해" 라고 쓰면 거짓말이다.
    assert "2단 센서라 원인으로 확정하지 않았다" in verdict, verdict
    ids = [c["claim_id"] for c in update["final_claims"]]
    assert "sensor:CC002000:TEMP_1" in ids
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in ids
    # 확정하지 않기로 했으므로 여기서도 picked 표시를 안 붙인다.
    #
    # 이 단언이 실제로 잠그는 것: (2a)가 `_record_evidence` 에 넘기는 `picked`
    # 자리에, **지목한 claim_id 를 그 호출이 쓰는 목록(`bundle.ranked_groups(
    # bundle.passing() + residuals)`)에서 다시 찾아** 넘기게 바꾸는 훼손이다.
    # 그렇게 바꾸면 잔차 지목 쪽(`test_a_named_residual_still_ends_as_weak_signal`)
    # 과 이 센서 지목 쪽 둘 다 이 단언이 잡는다(실측 확인됨).
    #
    # 잠그지 못하는 것: 표에 적힌 문자 그대로("None 대신 picked 전달" - 여기서
    # `picked` 는 함수 맨 위, **인자 없는** `bundle.ranked_groups()` 호출이 만든
    # 객체)는 다르다. `groups_to_dicts` 가 `group is picked` 로 식별하는데
    # (`evidence.py:520`), (2a)가 넘기는 목록은 `bundle.ranked_groups(bundle.
    # passing() + residuals)` 라는 **별도** 호출이 매번 새로 만든 객체들이라
    # (`ranked_groups()` 는 호출마다 새 `ClaimGroup` 을 만든다 - `find_group`
    # 자체 docstring 의 경고), 그 stale `picked` 를 그대로 넘겨도 `is` 비교가
    # 항상 거짓이라 아무 claim 에도 `picked_by_llm` 이 안 붙는다. 표 문자
    # 그대로의 훼손은 이 저장소 어떤 테스트로도 관측할 수 없다(직접 재현해
    # 확인됨) - 다만 이는 그 정확한 형태에만 해당하고, 위의 "다시 찾아 넘기는"
    # 형태(같은 위험을 더 정확히 대표한다)는 이 단언이 잡는다.
    assert not any(c.get("picked_by_llm") for c in update["final_claims"])


def test_a_made_up_claim_id_is_still_rejected_not_absorbed():
    """지어낸 이름은 '이 표본으로는 갈리지 않았다' 와 다른 사실이다.

    문을 claim_id 무관하게 열면 환각이 weak_signal 로 조용히 흡수돼, 엔지니어도
    모르고 다음에 모델을 바꿀 때 품질 저하를 못 본다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:NOPE",
         "hypothesis": "지어낸 것", "confidence": 0.9},
        loop=2, update=update, findings=[EQP_CH_BELOW_LINE])
    assert "finalize_status" not in update
    assert "finalize_accepted" not in update
    assert "도구 결과에 없다" in verdict, verdict
    # 지어낸 이름을 되풀이 제출하는 것이 설계 §9 가 남긴 잔여다 - 물러설 길 안내가
    # 그 왕복을 끊는 유일한 자리이고, 이 상태에서는 (2a)만 그 안내를 연다.
    assert "claim_id 를 비우고" in verdict, verdict


def test_weak_signal_wins_over_no_signal():
    """한 축은 침묵하고 다른 축은 약한 후보를 낸 상태에서 두 조건이 동시에 참이다.

    '봤고 후보도 났는데 약하다' 가 더 많은 정보를 담은 사실이므로 그쪽이 이겨야 한다.
    뒤에 두면 같은 상태가 no_signal 로 먼저 빠져나가 잔차가 또 소각된다.
    """
    update = {}
    nodes._finalize_gate({"claim_id": "", "hypothesis": "h", "confidence": 0.3},
                         loop=2, update=update,
                         findings=[EQP_CH_BELOW_LINE, PPID_SILENT])
    assert update["finalize_status"] == "weak_signal"


def test_weak_signal_does_not_drop_a_passing_sensor():
    """(2a)의 하한은 statistical_passing() 이라 **센서만 통과한 상태에서도 열린다.**

    그때 잔차만 실으면 판별선을 넘은 센서 근거가 리포트에서 사라진다 - 잔차는 근거를
    밀어내는 것이 아니라 더하는 것이다.
    """
    update = {}
    nodes._finalize_gate({"claim_id": "", "hypothesis": "h", "confidence": 0.3},
                         loop=3, update=update,
                         findings=[EQP_CH_BELOW_LINE, SENSOR_FINDING])
    assert update["finalize_status"] == "weak_signal"
    ids = {c["claim_id"] for c in update["final_claims"]}
    assert "sensor:CC002000:TEMP_1" in ids
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in ids


def test_a_hallucinated_claim_id_does_not_open_weak_signal():
    """REWRITTEN(규칙이 뒤집혔다): 하한은 "지목했는가" 가 아니라 "실재하는가" 다.

    옛 이름(`test_a_submitted_claim_id_does_not_open_weak_signal`)과 독스트링은
    "지목을 제출한 것은 물러선 것이 아니다" 를 단언했는데, 그것이 이 브랜치가
    `(2a)` 에서 뒤집은 규칙이다 - 잔차를 지목한 제출은 이제 곧장 열린다
    (`test_a_named_residual_still_ends_as_weak_signal`). 이 테스트가 초록이던
    이유는 하한이 좁아서가 아니라 claim_id 가 **환각**이라서였다.

    지금 잠그는 것: 하한(`_honest_pick`)의 출처 항들이 살아 있어 **지어낸** 이름은
    `(2a)` 를 못 연다(대체된 이름은 이제 연다 - 그것은 지어낸 것이 아니다.
    `test_a_superseded_claim_id_opens_weak_signal`). 없으면 '확신도 0.9 로 없는 근거를 지목한'
    제출이 곧바로 종료로 빠져나가 환각이 물러섬으로 둔갑한다.
    위 `test_a_made_up_claim_id_is_still_rejected_not_absorbed` 는 같은 상태에서
    **반려 문구**를 잠근다 - 이쪽은 `(2a)` 문이 안 열린다는 사실만 본다.
    """
    update = {}
    nodes._finalize_gate(
        {"claim_id": "지어낸:claim:id", "hypothesis": "h", "confidence": 0.9},
        loop=2, update=update, findings=[EQP_CH_BELOW_LINE])
    assert update.get("finalize_status") != "weak_signal"
    assert "finalize_accepted" not in update    # 반려 경로를 실제로 탔다


def test_a_passing_candidate_does_not_open_weak_signal():
    """(2a)의 첫 조건은 `not bundle.statistical_passing()` 이다 - 통과 후보가 있으면
    잔차만 있어도 (2a)는 안 열려야 한다.

    이 조건이 없으면, 판별선을 넘은 후보(score 1.0)가 실재하는데도 claim_id 를 안 낸
    제출이 '약한 신호' 로 조용히 종료돼 "판별선을 넘은 원인 후보는 없고" 라는 거짓
    문장을 내보내고, final_claims 에는 그 통과 후보가 `[근거 1]` 로 실린다. #8·#9 는
    이 3항 조건의 나머지 두 항(순서·`not claim_id`)만 잠갔고 이 항은 훼손 실험에서
    빠져 있어 되돌려도 스위트가 초록이었다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=2, update=update, findings=[EQP_CH_PASSING_AND_RESIDUAL])
    assert update.get("finalize_status") != "weak_signal"
    assert "finalize_accepted" not in update
    assert "claim_id 를 제출하지 않았다" in verdict, verdict


def test_a_weak_only_pick_is_not_told_to_empty_its_claim_id():
    """REWRITTEN(규칙이 뒤집혔다): 잔차를 지목하면 이제 곧장 weak_signal 로 물러선다.

    (2a) 하한이 `not claim_id` 이던 동안에는 이 지목이 반려로 갔고, 반려 문구가
    "claim_id 를 비우고 finalize 하라" 고 안내해야 라이브락을 피할 수 있었다.
    하한이 "정직한 제출" 로 넓어진 지금은 **실재하는** 잔차를 지목하면 그것이 곧장
    (2a) 를 여니, 이 상태에서 비우라는 안내가 나가면 오히려 이미 받아준 지목을
    취소하라는 모순된 지시가 된다.

    안내 자체가 없어진 것은 아니다 - **환각**을 지목하면 `(2a)` 가 안 열려 반려로
    가고(대체된 이름은 이제 열린다 - `test_a_superseded_claim_id_opens_weak_signal`), 위
    `test_a_made_up_claim_id_is_still_rejected_not_absorbed` 가 그 상태에서
    "claim_id 를 비우고" 가 **나온다**고 단언한다. 두 테스트는 같은 문구의
    나가는 상태와 안 나가는 상태를 각각 잠근다.
    """
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.9},
        loop=2, update={}, findings=[EQP_CH_BELOW_LINE])
    assert "약한 신호" in verdict, verdict
    assert "claim_id 를 비우고" not in verdict, verdict


def test_evidence_groups_adds_residuals_when_nothing_passes():
    """지목 가능한 통과 후보가 없으면 잔차를 더한 목록을 돌려준다."""
    from graph import evidence

    bundle = evidence.build_bundle([EQP_CH_BELOW_LINE, SENSOR_FINDING])
    passing = bundle.ranked_groups()
    out = nodes._evidence_groups(bundle, passing)
    ids = {c.claim_id for g in out for c in g.claims}
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in ids   # 잔차
    assert "sensor:CC002000:TEMP_1" in ids                        # 통과 센서도 남는다


def test_evidence_groups_keeps_passing_only_when_a_statistical_claim_passed():
    """통과 후보가 있으면 잔차를 안 더한다 - 접기 계약(_fold_key)의 전제다.

    같은 목록에 통과 claim 과 잔차가 섞이면 p 가 작은 잔차가 lead 를 뺏어
    통과 근거가 `passes` 키도 없는 `confounded_with` 로 강등되고 묶음 전체가
    `[잔차]` 로 찍힌다. 그리고 **같은 객체**를 돌려줘야 호출부의 `picked` 가
    `is` 로 맞는다 - 새로 만들면 아무 claim 에도 picked_by_llm 이 안 붙는다.
    """
    from graph import evidence

    bundle = evidence.build_bundle([EQP_CH_PASSING_AND_RESIDUAL])
    passing = bundle.ranked_groups()
    out = nodes._evidence_groups(bundle, passing)
    assert out is passing
    ids = {c.claim_id for g in out for c in g.claims}
    assert "eqp_ch_commonality:chamber:CD004000:PHOTO1_A" not in ids


def test_loop_limit_still_carries_residuals():
    """루프 한계로 끝나도 아랫선을 넘은 잔차는 리포트에 남아야 한다.

    실측(2026-09-08): 잔차 2건이 있는데 환각 지목을 되풀이해 loop 7 에 닿으면
    `inconclusive` · `final_claims=0` 으로 끝나 증거가 통째로 소각됐다.
    이 경로는 `(2a)` 가 환각을 안 받아 주기 때문에 열린다 - 프롬프트로는 못 막는다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:NOPE",
         "hypothesis": "지어낸 것", "confidence": 0.9},
        loop=ya_config.MAX_LOOPS, update=update, findings=[EQP_CH_BELOW_LINE])
    assert update["finalize_status"] == "inconclusive"
    ids = [c["claim_id"] for c in update["final_claims"]]
    assert ids == ["eqp_ch_commonality:chamber:CC002000:ETCH9_B"]
    # 판정문이 "확정 근거 없이" 라고 말하면 잔차를 싣고도 거짓이다.
    assert "확정 근거 없이" not in verdict, verdict
    assert "잔차 1건" in verdict, verdict


def test_loop_limit_without_residuals_keeps_the_old_sentence():
    """잔차가 없으면 옛 판정문 그대로다 - 없는 잔차를 말하면 안 된다."""
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=ya_config.MAX_LOOPS, update=update, findings=[EQP_CH_SILENT])
    assert update["finalize_status"] == "no_signal"       # (2)가 먼저 받는다
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "지어낸:claim:id", "hypothesis": "h", "confidence": 0.9},
        loop=ya_config.MAX_LOOPS, update=update, findings=[EQP_CH_SILENT])
    assert update["finalize_status"] == "inconclusive"
    assert "확정 근거 없이" in verdict, verdict
    assert "잔차" not in verdict, verdict


def test_loop_limit_with_a_passing_candidate_does_not_deny_the_evidence_it_carries():
    """통과 후보를 실어 놓고 "확정 근거 없이" 라고 말하면 안 된다.

    `EQP_CH_PASSING_AND_RESIDUAL` 에는 판별선을 넘은 후보가 실재한다. 그것을
    확신도 0.3(문턱 0.8 아래)으로 지목하면 (1)이 안 걸리고, `statistical_passing()`
    이 참이라 (2a)·(2)도 안 걸리고, uncomputable 도 아니라 (3)·(3b)도 안 걸려
    루프 한계 (4)로 떨어진다. 이때 `carried is groups`(잔차를 안 더함)라 옛 문장이
    나가는데, `_record_evidence` 는 이미 그 통과 묶음을 `final_claims` 에 실었다 -
    근거를 실어 놓고 없다고 말하면 리포트 LLM 이 "확정 근거 없이" 를 그대로
    인용해 거짓 리포트가 나간다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.3},
        loop=ya_config.MAX_LOOPS, update=update,
        findings=[EQP_CH_PASSING_AND_RESIDUAL])
    assert update["finalize_status"] == "inconclusive"
    assert update["final_claims"]
    assert "확정 근거 없이" not in verdict, verdict
    assert f"{len(update['final_claims'])}건" in verdict, verdict


def test_weak_signal_verdict_does_not_claim_residuals_the_cap_dropped(monkeypatch):
    """(2a) 판정문이 말하는 잔차 건수는 실제로 실린 건수여야 한다.

    `_record_evidence` 는 상한(`REPORT_MAX_EVIDENCE`)을 넘으면 통과 근거를 전부
    먼저 예약하고 남는 자리만 잔차로 채운다 - 통과 근거가 상한을 채우면 잔차는
    한 건도 안 실린다. 그런데 절단 **전** 수인 `len(residuals)` 를 그대로 찍으면
    "아랫선을 넘은 잔차 1건을 근거로 싣는다" 처럼, 리포트에는 없는 [잔차] 줄을
    가리키는 판정문이 나간다(Task 6 리뷰 I-2, 실측: 통과 센서 9 + 잔차 1 ->
    final_claims=8, [잔차] 줄 0개인데 판정문은 "잔차 1건"). 상한을 1로 낮춰 같은
    조건을 통과 센서 1 + 잔차 1 로 재현한다.
    """
    monkeypatch.setattr(ya_config, "REPORT_MAX_EVIDENCE", 1)
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "sensor:CC002000:TEMP_1", "hypothesis": "TEMP_1 이상", "confidence": 0.9},
        loop=2, update=update, findings=[EQP_CH_BELOW_LINE, SENSOR_FINDING])
    assert update["finalize_status"] == "weak_signal"
    assert not any(not c.get("passes", True) for c in update["final_claims"]), \
        update["final_claims"]
    assert "잔차 1건" not in verdict, verdict
    # 부정 단언만으로는 문장을 통째로 지워도 초록이다 - 0건 문구가 실제로
    # 나가는 것을 잠근다.
    assert ("아랫선을 넘은 잔차가 있었으나 통과 근거가 상한을 채워 리포트에는 "
            "실리지 않는다") in verdict, verdict
    report = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual", "target_group": ["W1"],
        "status_summary": "s", "findings": [], "final_hypothesis": "h",
        "final_confidence": 0.9, "finalize_status": "weak_signal",
        "final_claims": update["final_claims"],
    })["report"]
    assert "[잔차" not in report, report


def test_loop_limit_verdict_does_not_claim_residuals_the_cap_dropped(monkeypatch):
    """(4) 판정문도 (2a)와 같은 결함을 갖고 있었다 - 같은 방식으로 재현한다.

    `carried is not groups`(잔차가 더해진) 분기로 들어가되, 상한이 통과 근거로
    다 차 잔차가 0건 실리는 상태를 만든다. claim_id 를 실재하지 않는 이름으로
    줘 (2a) 를 비켜가게 한다 - `claim is None` 이면 (2a) 의 "정직한 제출" 하한이
    안 열린다.
    """
    monkeypatch.setattr(ya_config, "REPORT_MAX_EVIDENCE", 1)
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "지어낸:claim:id", "hypothesis": "지어낸 것", "confidence": 0.9},
        loop=ya_config.MAX_LOOPS, update=update,
        findings=[EQP_CH_BELOW_LINE, SENSOR_FINDING])
    assert update["finalize_status"] == "inconclusive"
    assert not any(not c.get("passes", True) for c in update["final_claims"]), \
        update["final_claims"]
    assert "잔차 1건" not in verdict, verdict
    assert "확정 근거 없이" not in verdict, verdict   # 통과 센서는 실제로 실렸다
    # 부정 단언만으로는 문장을 통째로 지워도 초록이다 - 0건 문구가 실제로
    # 나가는 것을 잠근다.
    assert ("아랫선을 넘은 잔차가 있었으나 통과 근거가 상한을 채워 리포트에는 "
            "실리지 않는다") in verdict, verdict
    report = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual", "target_group": ["W1"],
        "status_summary": "s", "findings": [], "final_hypothesis": "h",
        "final_confidence": 0.9, "finalize_status": "inconclusive",
        "final_claims": update["final_claims"],
    })["report"]
    assert "[잔차" not in report, report


def test_all_axes_run_but_nothing_separates_ends_as_no_separation():
    """전축을 다 봤는데 아무것도 안 갈리면 출구가 루프 한계뿐이던 것을 고친다 (M4).

    실측(2026-09-08): 전축 ok · 통과 0 · 잔차 0 이면 (2)(3)(3b) 어느 것도 안 열려
    loop 7 까지 왕복하다 inconclusive 로 끝났다 - 엔지니어는 "미확정(루프 한계
    도달)" 을 보는데 실제로 일어난 일은 "다 봤고 아무것도 안 갈렸다" 다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=2, update=update, findings=ALL_WEAK)
    assert update["finalize_status"] == "no_separation"
    assert update["finalize_accepted"] is True
    assert "갈리는 항목 없음" in verdict, verdict
    # 최고 점수를 수치로 싣는다 - "아깝게 몰랐다" 와 "흔적도 없다" 를 엔지니어가
    # 스스로 가르는 재료다. 건수만 세면 지워도 스위트가 초록이다.
    assert "최고 분리 점수 0.18" in verdict, verdict
    assert "잔차 아랫선(0.25)" in verdict, verdict
    assert "등록 축 4개 중 4개 대조" in verdict, verdict
    assert "lot 밖 대조군" in verdict, verdict
    # 최종 리뷰 I-1: 센서가 안 실린 상태에서는 원래 대조 문장 그대로다 - 센서
    # 단서 문구가 섞여 들어가면 안 된다(단서는 센서가 실렸을 때만 참이다).
    assert ("계산된 가설 도구(hyp_*) 축에서는 타깃과 대조군을 가르는 항목이 "
            "없다. 최고 분리 점수 0.18") in verdict, verdict
    assert "2단 센서는 판별선을 넘은 근거가 함께 실렸다" not in verdict, verdict
    # 최종 리뷰 I-3: no_data 축이 없으면 원래 조건문 그대로다.
    assert "분석이 안 돌은 것도 근거가 약한 것도 아니라" in verdict, verdict
    assert "계산 불가 축" not in verdict, verdict


def test_no_separation_wins_over_no_signal():
    """한 축은 침묵하고 다른 축은 약한 후보를 낸 상태에서 둘 다 참이다.

    (2) 뒤에 두면 **빈손 제출은 no_signal, 지목한 제출은 no_separation** 으로
    같은 증거가 제출 형태에 따라 다른 판정을 받는다. (2a)를 (2) 앞에 둔 것과
    같은 원칙 - 정보가 더 많고 조건이 더 좁은 쪽이 이긴다.
    """
    update = {}
    nodes._finalize_gate({"claim_id": "", "hypothesis": "h", "confidence": 0.3},
                         loop=2, update=update,
                         findings=[ALL_WEAK[0], PPID_SILENT,
                                   STEP_PASSAGE_SILENT, METRO_SILENT])
    assert update["finalize_status"] == "no_separation"


def test_all_silent_is_still_no_signal():
    """후보가 하나도 안 난 상태는 M4 가 아니다 - '갈리지 않았다' 가 아니라
    '볼 것이 안 났다' 이고, 그것을 말하는 판정은 이미 (2)다."""
    update = {}
    nodes._finalize_gate({"claim_id": "", "hypothesis": "h", "confidence": 0.3},
                         loop=2, update=update, findings=ALL_SILENT)
    assert update["finalize_status"] == "no_signal"


def test_no_separation_requires_every_axis():
    """부분 커버리지로 열면 근거 0건짜리 리포트로 조기 종료한다.

    '더 볼 것이 없었다' 는 (3)과 같은 성격의 **주장**이라 전축을 봐야 참이다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=2, update=update, findings=[ALL_WEAK[0]])
    assert "finalize_status" not in update
    assert "반려" in verdict, verdict


def test_no_separation_accepts_an_honest_pick():
    """약한 후보를 지목했다고 문을 닫으면 반려를 되풀이하다 루프 한계로 빠져
    이번에 고치는 결함이 그대로 재발한다((2a)와 같은 규칙).

    `SENSOR_FINDING`(통과한 2단 센서)을 섞는다 - 안 섞으면 `final_claims` 가
    빈 목록이라 "picked_by_llm 이 없다" 단언이 공허하게 참이 된다(지워도
    스위트가 초록이다, M4 재리뷰 Important 3). 섞은 김에 `top`(최고 분리 점수)이
    센서의 효과크기(2.31)가 아니라 비센서 최고 점수(0.18)를 고르는지도 함께
    잠근다. 판정문이 지목한 claim_id 를 실제로 부르는지도 잠근다(M4 재리뷰
    Important 4) - (2a)와 하한이 같은데 이름을 안 부르면 정직하게 지목한 LLM 이
    자기 제출이 무시된 승인을 받는다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "ETCH9_B 편중", "confidence": 0.9},
        loop=2, update=update, findings=ALL_WEAK + [SENSOR_FINDING])
    assert update["finalize_status"] == "no_separation"
    assert update["final_claims"]      # 통과 센서가 근거로 실려 있다
    # 받아준 것이지 원인으로 확정한 것이 아니다.
    assert not any(c.get("picked_by_llm") for c in update["final_claims"])
    assert "최고 분리 점수 0.18" in verdict, verdict   # 센서 효과크기(2.31)가 아니다
    assert "네가 지목한 eqp_ch_commonality:chamber:CC002000:ETCH9_B" in verdict, verdict
    # 최종 리뷰 I-1(재현 케이스, 실측): 통과한 2단 센서가 근거로 실린 상태에서
    # "가르는 항목이 없다" 를 축 전체로 넓히면 거짓이다 - 가설 도구(hyp_*) 축에
    # 한정하고 센서 단서를 붙인다. 문장 전체를 단언해 가운데 한정어가 빠져도
    # 빨개지게 한다.
    assert ("계산된 가설 도구(hyp_*) 축에서는 타깃과 대조군을 가르는 항목이 "
            "없다. 2단 센서는 판별선을 넘은 근거가 함께 실렸다 - 원인 확정 "
            "근거는 아니다. 최고 분리 점수 0.18") in verdict, verdict


def test_a_made_up_claim_id_does_not_open_no_separation():
    """환각은 '갈리지 않았다' 와 다른 사실이라 같은 이름을 주면 안 된다."""
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:NOPE",
         "hypothesis": "지어낸 것", "confidence": 0.9},
        loop=2, update=update, findings=ALL_WEAK)
    assert "finalize_status" not in update
    assert "도구 결과에 없다" in verdict, verdict


def test_a_thin_but_fully_separated_candidate_does_not_open_no_separation():
    """표본이 얇아 미통과인 완전 분리 후보(score 1.0)는 M4 가 아니다.

    `bundle.residuals()` 는 `target_pass >= COMMONALITY_PASS_MIN_TARGET` 도
    요구하므로 이 상태(target_pass 1 < 2)를 못 담아 `not bundle.residuals()`
    가 참이 된다 - 그것을 "안 갈렸다" 의 증거로 쓰면 실제로는 완전히 갈린
    챔버를 "갈리는 항목 없음" 이라 말하는 거짓 판정문이 나간다(M4 재리뷰
    Critical, 2026-09-10). (2b)는 점수를 직접 보므로 이 상태를 열지 않는다 -
    "안 갈렸다" 가 아니라 "갈렸는데 표본이 얇다" 는 다른 사실이고, 그 조치도
    다르다(lot 밖 대조군이 아니라 표본을 더 모으는 것).
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=2, update=update, findings=ALL_THIN)
    assert update.get("finalize_status") != "no_separation", verdict
    assert "갈리는 항목 없음" not in verdict, verdict


def test_a_superseded_claim_id_opens_no_separation():
    """(2b) 하한도 `(2a)` 와 같은 규칙을 쓴다 - 대체 이름은 정직한 제출이다."""
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "ETCH9_B 편중", "confidence": 0.3},
        loop=2, update=update, findings=[*ALL_WEAK, EQP_CH_RERUN_SILENT])
    assert update["finalize_status"] == "no_separation"
    assert ("네가 지목한 eqp_ch_commonality:chamber:CC002000:ETCH9_B 는 "
            "hyp_eqp_ch_commonality 를 다시 돌려 대체된 앞 실행의 후보라 원인으로 "
            "확정하지 않았다.") in verdict, verdict
    # 이 갈래(아랫선 미달) 문구로 뭉개면 안 된다 - 대체된 후보의 점수는 판정 대상이
    # 아니고, 애초에 그 후보가 통과했을 수도 있다.
    assert "에도 못 미쳐 원인으로 확정하지 않았다" not in verdict, verdict


def test_loop_limit_no_longer_relabels_no_separation_for_a_superseded_pick():
    """**이 규칙을 넓히는 실제 이유.** 루프 한계에서는 반려가 가르칠 다음 행동이
    없으므로, 하한이 닫혀 있으면 같은 증거가 제출 형태만 다르다는 이유로 다른
    사유를 받는다.

    실측(고치기 전): 빈손 제출은 `no_separation`("갈리는 항목 없음")인데 대체 이름을
    제출하면 `inconclusive`("미확정 - 루프 한계 도달: 확정 근거 없이 리포팅으로
    진행한다")로 끝났다 - 전축을 다 보고 아무것도 안 갈린 실행인데 엔지니어는
    루프를 다 썼다는 사유를 본다. 이 저장소가 M4 로 없앤 바로 그 문장이다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "ETCH9_B 편중", "confidence": 0.3},
        loop=ya_config.MAX_LOOPS, update=update,
        findings=[*ALL_WEAK, EQP_CH_RERUN_SILENT])
    assert update["finalize_status"] == "no_separation"
    assert "루프 한계" not in verdict, verdict


def test_no_separation_state_offers_the_step_back_path():
    """판정만 만들고 안내를 안 고치면 문이 열려 있는 줄도 모른다.

    이 상태에서 LLM 이 지어낸 이름을 내면 반려를 받는데, 그 반려가 "claim_id 를
    비우고 finalize 하라" 를 안 붙이면 같은 왕복이 루프 한계까지 이어진다 -
    (3)이 실제로 겪었던 라이브락이고, 그때도 원인은 판정과 안내가 다른 것을
    보고 있었기 때문이다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:NOPE",
         "hypothesis": "지어낸 것", "confidence": 0.9},
        loop=2, update=update, findings=ALL_WEAK)
    assert "claim_id 를 비우고" in verdict, verdict
    # 이월 10: 반려 경로에 있다는 사실 자체를 스스로 단언한다.
    assert "finalize_status" not in update


def test_no_separation_state_stays_closed_when_a_candidate_actually_passed(monkeypatch):
    """`not bundle.statistical_passing()` 은 점수 조건이 있어도 따로 남겨 둔
    방어선이다(`_no_separation_state` 독스트링) - `RESIDUAL_MIN_SCORE` 와
    `COMMONALITY_PASS_MIN_SCORE` 는 각각 독립된 환경변수라 코드가 그 대소를
    강제하지 않는다. 설정이 어긋나 `RESIDUAL_MIN_SCORE` 가 통과 점수보다 커지면
    점수 조건(`all(score < RESIDUAL_MIN_SCORE)`) 만으로는 통과 후보를 걸러내지
    못한다 - 그 상태에서 이 조건이 빠지면 실제로 통과한 후보가 있는데도
    '갈리는 항목 없음'(no_separation)이 열려, confirmed 로 나가야 할 결과가
    거짓 판정문으로 바뀐다.
    """
    from graph import evidence
    monkeypatch.setattr(ya_config, "RESIDUAL_MIN_SCORE", 1.5)
    findings = [EVIDENCE_FINDING_NEW, PPID_SILENT, STEP_PASSAGE_SILENT, METRO_SILENT]
    bundle = evidence.build_bundle(findings)
    coverage = nodes._coverage(bundle)
    assert bundle.statistical_passing(), "픽스처가 통과 후보를 안 내면 이 시험은 공허하다"
    assert nodes._no_separation_state(bundle, coverage) is False


def test_no_separation_limits_the_claim_to_computed_axes_when_some_are_no_data():
    """최종 리뷰 I-3(a): 계산 불가(no_data) 축이 섞이면 "다 대조했다" 는 거짓이다.

    약한 ok 축 1개(`ALL_WEAK[0]`) + `no_paired_stratum` 축 3개
    (`_ALL_NO_PAIR[1:]`) - `_no_separation_state` 의 ①(`not unrun and not
    failed`)은 `no_data` 를 안 보므로 이 상태에서도 그대로 열린다(재현, 리뷰어
    사례: 약한 ok 축 1 + no_paired_stratum 축 3 -> "등록 축 4개 중 4개 대조"라고
    말하면서 3개는 계산 불가였다는 사실을 "가르는 항목이 없다" 뒤에서 숨긴다).
    "가르는 항목이 없다" 를 계산된 축에 한정하고, "분석이 안 돌은 것도 아니라"
    를 빼며, 계산 불가 축에 적재 범위 확인 조치를 붙인다.
    """
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "", "hypothesis": "h", "confidence": 0.3},
        loop=2, update=update, findings=[ALL_WEAK[0], *_ALL_NO_PAIR[1:]])
    assert update["finalize_status"] == "no_separation"
    assert update["coverage"]["no_data"] == [
        "hyp_metro_commonality", "hyp_ppid_commonality", "hyp_step_passage_commonality"]
    assert "등록 축 4개 중 4개 대조" in verdict, verdict
    assert ("그중 3개는 계산 불가: hyp_metro_commonality, hyp_ppid_commonality, "
            "hyp_step_passage_commonality") in verdict, verdict
    # "분석이 안 돌은 것도" 는 no_data 가 있으면 거짓이라 뺀다 - 전체 문구를
    # 단언해 부정어 하나만 지우는 훼손도 잡는다.
    assert "분석이 안 돌은 것도" not in verdict, verdict
    assert ("계산된 가설 도구(hyp_*) 축에서는 타깃과 대조군을 가르는 항목이 "
            "없다. 최고 분리 점수 0.18 로 잔차 아랫선(0.25)에도 미달한다. "
            "근거가 약한 것도 아니라 lot 내부 대조로는 갈리지 않는다는 "
            "뜻이다.") in verdict, verdict
    # 계산 불가 축에는 (3)/운영 프롬프트 no_comparable_data 와 같은 조치를 붙인다.
    assert ("계산 불가 축(hyp_metro_commonality, hyp_ppid_commonality, "
            "hyp_step_passage_commonality)은 적재 범위와 추출 조건을 "
            "확인해야 한다.") in verdict, verdict
    assert "lot 밖 대조군 또는 다른 관측축이 필요하다" in verdict, verdict


def test_loop_limit_evidence_count_reflects_the_cap_not_the_carried_total(monkeypatch):
    """최종 리뷰 I-4: (4) `elif carried:` 판정문의 건수는 절단 전 `len(carried)`
    가 아니라 실제로 `final_claims` 에 실린 수여야 한다.

    통과 묶음을 2개(서로 다른 축) 만들고 상한을 1로 낮춘다. `bundle.
    statistical_passing()` 이 참이라 `_evidence_groups` 는 잔차를 안 더하고
    `groups` 를 그대로 돌려주므로(`carried is groups`) `elif carried:` 갈래로
    떨어진다 - `len(carried)` 는 2 인데 `_record_evidence` 의 상한이 걸려
    `final_claims` 는 1건만 남는다(리뷰어 재현: 통과 묶음 11개 · confidence 0.3
    · loop 7 -> final_claims 8건인데 판정문은 "근거 11건").
    """
    monkeypatch.setattr(ya_config, "REPORT_MAX_EVIDENCE", 1)
    second_axis_passing = {
        "loop": 3, "tool": "hyp_ppid_commonality", "args": {},
        "result": {"hypothesis_id": "ppid_commonality", "status": "ok", "candidates": [
            {"claim_id": "ppid_commonality:ppid:CC002000:P1", "step_seq": "CC002000",
             "key": "P1", "level": "ppid", "passes": True, "reject_reason": None,
             "score": 1.0, "target_pass": 3, "target_total": 3,
             "control_pass": 0, "control_total": 3},
        ]},
        "thought": "다른 축 통과",
    }
    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": "지어낸:claim:id", "hypothesis": "h", "confidence": 0.3},
        loop=ya_config.MAX_LOOPS, update=update,
        findings=[EVIDENCE_FINDING_NEW, second_axis_passing])
    assert update["finalize_status"] == "inconclusive"
    assert len(update["final_claims"]) == 1     # 상한 1 로 잘렸다
    assert f"근거 {len(update['final_claims'])}건" in verdict, verdict
    assert "근거 2건" not in verdict, verdict
