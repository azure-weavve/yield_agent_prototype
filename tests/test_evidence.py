"""EvidenceBundle — findings 를 게이트가 읽는 구조화된 증거로 투영한다.

판정하지 않는다. 사실만 모은다. 판정은 graph/nodes.py 의 게이트가 한다.
"""

from dataclasses import asdict

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
    # 필드 매핑 자체를 잠근다 — step_seq/key 전치, target/control 뒤섞임을 잡는다
    c = b.claims[CAND_PASS["claim_id"]]
    assert (c.hypothesis_id, c.level, c.step_seq, c.key) == (
        "eqp_ch_commonality", "chamber", "CC002000", "ETCH9_B")
    assert (c.score, c.target_pass, c.target_total, c.control_pass, c.control_total) == (
        1.0, 3, 3, 0, 6)


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
    # 점수가 더 높은 미통과 후보 — passes 필터가 빠지면 이 0.9 가 새어 나온다
    ppid_fail = {**ppid, "claim_id": "ppid_commonality:ppid:CC002000:PPID_Y",
                 "key": "PPID_Y", "passes": False, "score": 0.9,
                 "reject_reason": "분리 점수 미달"}
    decoy = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:CD004000:PHOT2_X",
             "key": "PHOT2_X", "score": 0.75}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS, decoy]),
        _finding("hyp_ppid_commonality", "ppid_commonality", "ok", [ppid, ppid_fail]),
    ])
    assert b.top_score("hyp_eqp_ch_commonality") == 1.0
    assert b.top_score("hyp_ppid_commonality") == 0.6
    assert b.top_score("hyp_nothing_ran") is None


def test_permutation_p_survives_the_bundle():
    """순열 p 가 후보 dict 에서 Claim 까지 살아 간다.

    score 단언이 함께 있는 이유: build_bundle 이 .get() 기본값을 쓰므로 후보에
    키가 늘 때 매핑이 어긋나면 score 가 조용히 0 이 된다. 실데이터에서 게이트가
    통째로 침묵하는 경로라 같이 못 박는다 (설계 §5).
    """
    cand = {**CAND_PASS, "p_permutation": 0.0123}
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [cand])])
    c = b.claims[CAND_PASS["claim_id"]]
    assert c.p_permutation == 0.0123
    assert c.score == 1.0


def test_missing_permutation_p_is_none_not_zero():
    """순열을 껐거나 옛 결과면 p 가 없다. 0.0 으로 뭉개면 안 된다.

    p = 0.0 은 "우연일 리 없다" 로 읽힌다. 없는 것과 아주 유의한 것을 같은 값으로
    적으면 정확히 반대 방향의 오독이 된다.
    """
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [CAND_PASS])])
    assert b.claims[CAND_PASS["claim_id"]].p_permutation is None


def test_evidence_line_carries_p_only_when_present():
    """근거 줄에 p 를 싣되, 없으면 예전 모양 그대로여야 한다."""
    with_p = evidence.build_bundle([_finding(
        "hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok",
        [{**CAND_PASS, "p_permutation": 0.0123}])])
    line = evidence.format_evidence_line(asdict(with_p.claims[CAND_PASS["claim_id"]]))
    assert line.endswith("· 순열 p 0.0123")

    without = evidence.build_bundle([_finding(
        "hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS])])
    line2 = evidence.format_evidence_line(asdict(without.claims[CAND_PASS["claim_id"]]))
    assert "순열 p" not in line2
    assert line2.endswith("대조군 0/6 통과")


def test_p_floor_survives_the_bundle():
    """바닥값도 Claim 까지 살아 가야 근거 줄이 p 를 옳게 렌더링한다."""
    cand = {**CAND_PASS, "p_permutation": 0.05, "p_min_possible": 0.05}
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [cand])])
    c = b.claims[CAND_PASS["claim_id"]]
    assert c.p_min_possible == 0.05
    assert c.score == 1.0          # 키가 늘 때 매핑이 밀리지 않았는지 함께 잠근다


def test_evidence_line_marks_a_p_that_sits_at_the_floor():
    """바닥값에 닿은 p 는 약한 신호가 아니라 이 표본이 낼 수 있는 최강 결과다.

    2대2 한 lot 이면 섞는 방법이 6가지뿐이라 완전 분리여도 p 가 0.1667 이다.
    같은 0.1667 이 1000회 순열에서 나왔다면 뜻이 정반대다. 표시가 없으면 리포트를
    읽는 엔지니어가 "유의하지 않다" 로 읽어 진짜 원인을 버린다.
    """
    at_floor = {**CAND_PASS, "p_permutation": 0.1667, "p_min_possible": 0.1667}
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [at_floor])])
    line = evidence.format_evidence_line(asdict(b.claims[CAND_PASS["claim_id"]]))
    assert line.endswith("· 순열 p 0.1667 (이 표본의 최소값)")

    above = {**CAND_PASS, "p_permutation": 0.1667, "p_min_possible": 0.001}
    b2 = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                         "ok", [above])])
    line2 = evidence.format_evidence_line(asdict(b2.claims[CAND_PASS["claim_id"]]))
    assert line2.endswith("· 순열 p 0.1667")     # 같은 p 인데 바닥이 아니면 표시 없음
    assert "최소값" not in line2
