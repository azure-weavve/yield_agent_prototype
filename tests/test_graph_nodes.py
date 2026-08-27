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

    안내 대상을 통과 후보로 좁힌 대가로, 이 상태에서 문구가 "통과한 후보가 없다" 로
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
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": False,
             "reject_reason": "분리 점수 0.4 < 0.5", "score": 0.4,
             "target_pass": 4, "target_total": 4, "control_pass": 3, "control_total": 5},
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
    """가설이 후보를 냈지만 문턱을 못 넘은 것(status ok)은 no_signal 이 아니라 반려다.

    no_signal 은 도구가 후보 자체를 못 낸(status no_signal) 구조적 부재를 뜻한다.
    후보는 있는데 판별선만 못 넘은 경우는 조치가 다르므로(더 좁힐 여지가 있다)
    같은 취급을 하면 안 된다.

    등록 가설을 **전부 status ok 로** 채운다. 하나라도 no_signal 로 채우면 statuses
    에 no_signal 이 섞여 (2)번이 열려 버려 다른 케이스(혼합 상태)를 시험하게 된다.
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
    assert "finalize_accepted" not in out


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

    "최신 실행 결과에서 골라라" 뒤에 "통과한 후보가 없다" 가 붙으면 한 문장 안에서
    자기모순이고, H1 이 막으려던 "LLM 이 같은 문맥을 다시 읽는" 행동이 약한 형태로
    되살아난다. 사실(대체됐다)과 다음 행동(무엇을 하라)은 분리한다.
    """
    verdict = nodes._finalize_gate(
        {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
         "hypothesis": "h", "confidence": 0.9},
        loop=3, update={}, findings=[EVIDENCE_FINDING_NEW, EQP_CH_RERUN_SILENT])
    assert "대체" in verdict
    assert "골라라" not in verdict          # 고를 것이 없다
    assert "통과한 후보가 없다" in verdict   # 다음 행동은 이쪽이 안내한다


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

    특히 대조군만 빠지면 결과가 `no_paired_stratum`("이력 결측")이다. 엔지니어는
    적재·추출 범위를 뒤지러 가고, 진짜 원인(파이프라인이 분모를 안 넣었다)은
    아무 데도 안 남는다. 조용한 오답보다 크게 죽는 편이 낫다.
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
