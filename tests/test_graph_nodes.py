"""노드 단위 검증 — 특히 tools 노드의 finalize 게이트(승인/반려)와 감사 기록."""

import os
import subprocess
import sys

from langchain_core.messages import AIMessage, ToolMessage

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

# no_signal 종료는 **등록 가설을 전부 돌린 뒤에만** 판정된다. 그래서 이 시험에는
# hypotheses.yaml 의 가설 수만큼 침묵 finding 이 필요하다 — 가설을 추가하면 여기도
# 늘려야 하고, 안 늘리면 게이트가 "아직 안 돌린 가설이 있다" 로 반려한다.
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
ALL_SILENT = [EQP_CH_SILENT, PPID_SILENT, STEP_PASSAGE_SILENT]


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


def test_gate_rejects_claim_that_did_not_pass():
    """미통과 후보를 지목하면 도구가 낸 reject_reason 을 그대로 돌려준다."""
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CD004000:PHOTO1_A")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING_NEW]})
    assert "finalize_accepted" not in out
    assert "분리 없음" in out["messages"][0].content


def test_gate_rejects_claim_that_did_not_pass_even_when_score_ties_the_top():
    """실패 후보의 점수가 통과 후보의 최고 점수와 같거나 높아도 여전히 반려돼야 한다.

    top_score 는 통과 후보만 대상으로 하므로, 점수 비교만으로는 passes=False 를
    걸러내지 못한다 — 표본 부족(target_pass 미달)처럼 점수는 높은데 판별선을
    못 넘는 후보가 있을 수 있다.
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
             "reject_reason": "타깃 표본 1 < 3",
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
             "score": 0.75, "target_pass": 4, "target_total": 4,
             "control_pass": 1, "control_total": 5},
        ]},
        "thought": "미끼 포함",
    }
    ai = _ai_finalize(0.9, claim_id="eqp_ch_commonality:chamber:CD004000:PHOT2_X")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3, "findings": [decoy]})
    assert "finalize_accepted" not in out
    assert "eqp_ch_commonality:chamber:CC002000:ETCH2_B" in out["messages"][0].content


def test_gate_accepts_tied_top_score():
    """설비 롤업과 챔버가 동점이면 더 구체적인 쪽을 지목해도 승인한다.

    타깃 전원이 거친 설비를 대조군이 아무도 안 거치면 두 레벨이 같은 점수가 되고,
    정렬은 문자열순이라 덜 구체적인 설비 롤업이 앞선다. 동점을 막으면 챔버 지목이 반려된다.
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


def test_gate_records_the_approved_claim():
    """승인 시 근거 수치가 상태에 남는다 - 리포트가 LLM 문장에 의존하지 않게."""
    out = nodes.tools_node({"messages": [_ai_finalize(0.9)], "loop_count": 4,
                            "findings": [EVIDENCE_FINDING]})
    assert out["finalize_status"] == "confirmed"
    assert out["final_claim"]["claim_id"] == "eqp_ch_commonality:chamber:Etch:ETCH-9"
    assert out["final_claim"]["score"] == 1.0
    assert (out["final_claim"]["target_pass"], out["final_claim"]["control_pass"]) == (3, 0)


def test_gate_asks_for_the_unrun_hypothesis_before_declaring_no_signal():
    """EQP_CH 하나가 조용하다고 신호가 없다고 선언하지 않는다."""
    ai = _ai_finalize(0.2, hypothesis="분리되는 후보가 없다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 2,
                            "findings": [EQP_CH_SILENT]})
    assert "finalize_accepted" not in out
    assert "hyp_ppid_commonality" in out["messages"][0].content


def test_gate_declares_no_signal_after_all_hypotheses_are_silent():
    """등록 가설을 다 돌렸는데 통과 후보가 없으면 no_signal 로 종료한다.

    확신도는 보지 않는다 - 물러섬 선언에 높은 확신도를 요구하면 모순이다.
    루프 한계보다 먼저 걸려야 한다(loop 2 에서 종료).
    """
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
    """한 가설에 통과 후보가 있으면, 다른 가설이 no_signal 이어도 전체를 신호 없음으로 뭉개면 안 된다."""
    ai = _ai_finalize(0.2, hypothesis="아직 claim_id 를 못 골랐다", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [EVIDENCE_FINDING, PPID_SILENT]})
    assert "finalize_accepted" not in out


def test_gate_does_not_declare_no_signal_when_candidates_only_missed_the_line():
    """가설이 후보를 냈지만 문턱을 못 넘은 것(status ok)은 no_signal 이 아니라 반려다.

    no_signal 은 도구가 후보 자체를 못 낸(status no_signal) 구조적 부재를 뜻한다.
    후보는 있는데 판별선만 못 넘은 경우는 조치가 다르므로(더 좁힐 여지가 있다)
    같은 취급을 하면 안 된다.
    """
    weak_eqp_ch = {
        "loop": 2, "tool": "hyp_eqp_ch_commonality", "args": {},
        "result": {"hypothesis_id": "eqp_ch_commonality", "status": "ok", "candidates": [
            {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "step_seq": "CC002000",
             "key": "ETCH9_B", "level": "chamber", "passes": False,
             "reject_reason": "분리 점수 0.3 < 0.6",
             "score": 0.3, "target_pass": 4, "target_total": 4,
             "control_pass": 3, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    weak_ppid = {
        "loop": 3, "tool": "hyp_ppid_commonality", "args": {},
        "result": {"hypothesis_id": "ppid_commonality", "status": "ok", "candidates": [
            {"claim_id": "ppid_commonality:ppid:PPID001:P1", "step_seq": "PPID001",
             "key": "P1", "level": "ppid", "passes": False,
             "reject_reason": "분리 점수 0.2 < 0.6",
             "score": 0.2, "target_pass": 4, "target_total": 4,
             "control_pass": 3, "control_total": 5},
        ]},
        "thought": "약한 후보",
    }
    ai = _ai_finalize(0.2, hypothesis="약한 후보뿐", claim_id="")
    out = nodes.tools_node({"messages": [ai], "loop_count": 3,
                            "findings": [weak_eqp_ch, weak_ppid]})
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
            {"name": "hyp_eqp_ch_commonality",
             "args": {"group_ids": ["W2406_02", "W2406_04", "W2406_06"],
                      "control_ids": ["W2406_01", "W2406_03", "W2406_05"]},
             "id": "call_c"},
            {"name": "finalize",
             "args": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                      "hypothesis": "Etch ETCH9_B 챔버 편중이 원인", "confidence": 0.9},
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
        "final_claim": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                        "score": 1.0, "target_pass": 3, "target_total": 3,
                        "control_pass": 0, "control_total": 6},
    })
    assert "[근거]" in out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]
    assert "분리 점수 1.0" in out["report"]
    assert "타깃 3/3" in out["report"] and "대조군 0/6" in out["report"]
    assert out["report"].count("[근거]") == 1   # 클라이언트가 또 붙이면 중복된다


def test_report_node_has_no_evidence_line_without_claim():
    """확정되지 않은 분석에 근거 줄을 만들어 붙이지 않는다."""
    out = nodes.report_node({
        "target_wafers": ["W1"], "target_source": "manual",
        "target_group": ["W1"], "status_summary": "s", "findings": [],
        "final_hypothesis": None, "final_confidence": None,
    })
    assert "[근거]" not in out["report"]


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
            "final_claim": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B",
                            "score": 1.0, "target_pass": 3, "target_total": 3,
                            "control_pass": 0, "control_total": 6},
        })
    finally:
        nodes._llm = original
    assert "[근거]" in out["report"]
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]


def test_report_node_passes_the_approved_claim_to_the_report():
    out = nodes.report_node({
        "target_wafers": ["W2406_02"], "target_source": "manual",
        "target_group": ["W2406_02"], "status_summary": "요약", "findings": [],
        "final_hypothesis": "ETCH9_B 편중", "final_confidence": 0.9,
        "finalize_status": "confirmed",
        "final_claim": {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "score": 1.0,
                        "target_pass": 3, "target_total": 3,
                        "control_pass": 0, "control_total": 6},
    })
    assert "eqp_ch_commonality:chamber:CC002000:ETCH9_B" in out["report"]