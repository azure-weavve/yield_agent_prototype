"""EvidenceBundle — findings 를 게이트가 읽는 구조화된 증거로 투영한다.

판정하지 않는다. 사실만 모은다. 판정은 graph/nodes.py 의 게이트가 한다.
"""

from graph import evidence


def _finding(tool, hypothesis_id, status, candidates, result=None):
    return {"loop": 1, "tool": tool, "args": {},
            "result": result if result is not None else {
                "hypothesis_id": hypothesis_id, "status": status,
                "candidates": candidates},
            "thought": "t"}


CAND_PASS = {"claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH9_B", "level": "chamber",
             "step_seq": "CC002000", "key": "ETCH9_B", "passes": True,
             "reject_reason": None, "score": 1.0,
             "target_pass": 3, "target_total": 3, "control_pass": 0, "control_total": 6}
CAND_FAIL = {"claim_id": "eqp_ch_commonality:chamber:CD004000:PHOT2_X", "level": "chamber",
             "step_seq": "CD004000", "key": "PHOT2_X", "passes": False,
             "reject_reason": "분리 점수 0.3 < 0.5", "score": 0.3,
             "target_pass": 3, "target_total": 4, "control_pass": 2, "control_total": 5}


def test_build_bundle_collects_claims_and_status():
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [CAND_PASS, CAND_FAIL])])
    assert set(b.claims) == {CAND_PASS["claim_id"], CAND_FAIL["claim_id"]}
    assert b.statuses == {"hyp_eqp_ch_commonality": "ok"}
    assert b.ran == {"hyp_eqp_ch_commonality"}
    # 미통과 후보도 담는다 — 게이트가 reject_reason 을 그대로 돌려주려면 조회돼야 한다
    assert b.claims[CAND_FAIL["claim_id"]].reject_reason == "분리 점수 0.3 < 0.5"
    assert [c.claim_id for c in b.passing()] == [CAND_PASS["claim_id"]]


def test_sensor_result_is_not_evidence():
    """센서 결과에도 candidates 키가 있다 — 덕타이핑이면 여기로 딸려 들어온다.

    판별자는 hypothesis_id 의 유무이지 candidates 의 유무가 아니다.
    """
    sensor = {"status": "ok", "candidates": [
        {"sensor_name": "rf_power_steady_avg", "effect_size": 14.99, "passes": True}]}
    b = evidence.build_bundle([{"loop": 1, "tool": "compare_sensor_distribution",
                                "args": {}, "result": sensor, "thought": "t"}])
    assert b.claims == {}
    assert b.ran == set()


def test_tool_error_string_does_not_count_as_ran():
    """'불렀다' 와 '근거를 냈다' 는 다르다 — 인자 오류로 실패한 도구는 ran 이 아니다."""
    b = evidence.build_bundle([_finding("hyp_ppid_commonality", None, None, None,
                                        result="오류: 실행 실패 (KeyError: 'legend')")])
    assert b.ran == set()
    assert b.statuses == {}


def test_no_signal_status_is_recorded_without_candidates():
    b = evidence.build_bundle([_finding("hyp_ppid_commonality", "ppid_commonality",
                                        "no_signal", [])])
    assert b.statuses == {"hyp_ppid_commonality": "no_signal"}
    assert b.ran == {"hyp_ppid_commonality"}
    assert b.passing() == []


def test_rerun_replaces_previous_claims_of_the_same_tool():
    """같은 도구를 다시 돌리면 앞 결과는 버린다 — 그룹이 바뀐 재실행이면 옛 후보는 거짓이다."""
    stale = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH1_A", "key": "ETCH1_A"}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [stale]),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
    ])
    assert set(b.claims) == {CAND_PASS["claim_id"]}


def test_top_score_is_per_tool():
    """legend 가 다른 두 도구의 점수는 비교 대상이 아니다."""
    ppid = {"claim_id": "ppid_commonality:ppid:CC002000:PPID_X", "level": "ppid",
            "step_seq": "CC002000", "key": "PPID_X", "passes": True,
            "reject_reason": None, "score": 0.6,
            "target_pass": 3, "target_total": 3, "control_pass": 2, "control_total": 5}
    decoy = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:CD004000:PHOT2_X",
             "key": "PHOT2_X", "score": 0.75}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS, decoy]),
        _finding("hyp_ppid_commonality", "ppid_commonality", "ok", [ppid]),
    ])
    assert b.top_score("hyp_eqp_ch_commonality") == 1.0
    assert b.top_score("hyp_ppid_commonality") == 0.6
    assert b.top_score("hyp_nothing_ran") is None
