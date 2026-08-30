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


# ---------------------------------------------------------------- 접기와 순위

def _cand(claim_id, key, score, p, wafers, level="chamber", step="CC002000"):
    return {"claim_id": claim_id, "level": level, "step_seq": step, "key": key,
            "passes": True, "reject_reason": None, "score": score,
            "target_pass": len(wafers), "target_total": 6,
            "control_pass": 0, "control_total": 6,
            "p_permutation": p, "target_wafers": list(wafers), "control_wafers": []}


def test_ranking_puts_permutation_p_ahead_of_the_raw_score():
    """p 가 점수를 이긴다 - 점수는 축마다 다르게 부풀기 때문이다.

    분할점을 탐색하는 축(계측)은 무신호 데이터에서도 후보의 절반 가까이가 판별선을
    넘는다. 그 축의 0.9 와 경로 축의 0.9 는 같은 뜻이 아니다. p 는 그 탐색까지
    포함해 잰 값이라 축을 가로질러 비교할 수 있는 유일한 자다.
    """
    b = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("a:1", "HIGH_SCORE", 0.95, 0.40, ["W1", "W2"])]),
        _finding("hyp_b", "b", "ok", [_cand("b:1", "LOW_P", 0.55, 0.01, ["W3", "W4"])]),
    ])
    groups = b.ranked_groups()
    assert [g.lead.key for g in groups] == ["LOW_P", "HIGH_SCORE"]


def test_missing_permutation_p_ranks_last():
    """순열을 안 돌린 후보를 좋은 것으로 읽으면 안 된다 - 없는 것은 최하위다."""
    b = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("a:1", "NO_P", 1.0, None, ["W1", "W2"])]),
        _finding("hyp_b", "b", "ok", [_cand("b:1", "HAS_P", 0.6, 0.5, ["W3", "W4"])]),
    ])
    assert [g.lead.key for g in b.ranked_groups()] == ["HAS_P", "NO_P"]


def test_identical_wafer_sets_fold_across_axes():
    """축이 달라도 같은 wafer 를 가리키면 한 근거다 (교락)."""
    b = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("a:1", "CH_B", 0.8, 0.02, ["W1", "W2", "W3"])]),
        _finding("hyp_b", "b", "ok", [_cand("b:1", "PPID_X", 0.8, 0.02, ["W3", "W1", "W2"],
                                            level="ppid")]),
    ])
    groups = b.ranked_groups()
    assert len(groups) == 1
    assert groups[0].confounded
    assert {c.key for c in groups[0].claims} == {"CH_B", "PPID_X"}


def test_partial_overlap_does_not_fold():
    """부분 겹침은 접지 않는다 - 안 겹치는 wafer 가 두 가설을 가르는 정보다."""
    b = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("a:1", "CH_B", 0.8, 0.02, ["W1", "W2", "W3"])]),
        _finding("hyp_b", "b", "ok", [_cand("b:1", "PPID_X", 0.8, 0.02, ["W2", "W3", "W4"],
                                            level="ppid")]),
    ])
    groups = b.ranked_groups()
    assert len(groups) == 2
    assert not any(g.confounded for g in groups)


def test_claims_without_wafer_sets_are_never_folded_together():
    """wafer 목록이 없으면 각자 홀로 선다 - 빈 집합끼리 같다고 묶으면 안 된다.

    센서처럼 목록을 안 싣는 결과나, 아직 이 필드를 안 채우는 축이 섞여 들어와도
    서로 무관한 후보가 한 덩어리가 되어서는 안 된다.
    """
    a = _cand("a:1", "A", 0.8, 0.02, [])
    c = _cand("b:1", "B", 0.7, 0.03, [])
    b = evidence.build_bundle([_finding("hyp_a", "a", "ok", [a]),
                               _finding("hyp_b", "b", "ok", [c])])
    groups = b.ranked_groups()
    assert len(groups) == 2
    assert not any(g.confounded for g in groups)


def test_tied_groups_share_a_rank_and_say_so():
    """동점은 같은 등수를 받고, 그 사실이 근거 줄에 적힌다.

    번호만 매기면 앞선 것이 더 강해 보인다. 우열을 못 가린다는 것 자체가 다음에
    무엇을 볼지 정하는 입력이라, 조용히 순서로 뭉개면 안 된다.
    """
    b = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("a:1", "A", 0.7, 0.03, ["W1", "W2"])]),
        _finding("hyp_b", "b", "ok", [_cand("b:1", "B", 0.7, 0.03, ["W3", "W4"])]),
    ])
    dicts = evidence.groups_to_dicts(b.ranked_groups())
    assert [d["rank"] for d in dicts] == [1, 1]
    assert all(d["tied"] for d in dicts)
    assert "정할 수 없다" in evidence.format_group_line(dicts[0])


def test_distinct_ranks_are_not_marked_tied():
    b = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("a:1", "A", 0.7, 0.01, ["W1", "W2"])]),
        _finding("hyp_b", "b", "ok", [_cand("b:1", "B", 0.7, 0.30, ["W3", "W4"])]),
    ])
    dicts = evidence.groups_to_dicts(b.ranked_groups())
    assert [d["rank"] for d in dicts] == [1, 2]
    assert not any(d["tied"] for d in dicts)
    assert "정할 수 없다" not in evidence.format_group_line(dicts[0])


def test_axis_specific_fields_survive_in_extra():
    """축마다 있고 없는 값이 Bundle 경계에서 잘리지 않는다.

    coverage_* 와 metro 의 split_value 가 여기서 사라져 **LLM 은 보는데 코드
    게이트는 못 보는** 값이 됐었다. 1급 필드로 하나씩 늘리는 대신 한 자리에 모은다.
    """
    cand = _cand("m:1", "THK >= 129.0", 0.9, 0.02, ["W1", "W2"], level="metro")
    cand.update({"coverage_target": 1.0, "coverage_control": 0.1,
                 "item": "THK", "split_value": 129.0, "split_direction": "ge"})
    b = evidence.build_bundle([_finding("hyp_metro", "metro_commonality", "ok", [cand])])
    claim = b.claims["m:1"]
    assert claim.extra["split_value"] == 129.0
    assert claim.extra["split_direction"] == "ge"
    assert claim.extra["coverage_target"] == 1.0
    # 1급 필드는 extra 로 중복되지 않는다
    assert "score" not in claim.extra and "target_wafers" not in claim.extra


def test_same_targets_but_different_counterexamples_do_not_fold():
    """반례가 다르면 접지 않는다 - 2x2 가 실제로 가르는 차이다.

    타깃만 보고 접으면 "타깃 3장 · 대조군 반례 0건" 과 "타깃 3장 · 반례 3건" 이
    한 근거가 되고, 리포트가 **"구분되지 않는다" 고 말하면서 바로 옆에 구분되는
    수치를 찍는다.** 접기의 뜻은 "같은 사실의 두 이름" 인데 이건 다른 사실이다.
    """
    a = _cand("a:1", "CH_B", 1.0, 0.02, ["W1", "W2", "W3"])
    b = _cand("b:1", "PPID_X", 0.5, 0.40, ["W1", "W2", "W3"], level="ppid")
    b["control_wafers"] = ["C1", "C2", "C3"]      # 반례 3건
    b["control_pass"] = 3

    groups = evidence.build_bundle([_finding("hyp_a", "a", "ok", [a]),
                                    _finding("hyp_b", "b", "ok", [b])]).ranked_groups()
    assert len(groups) == 2
    assert not any(g.confounded for g in groups)
    # 반례 없는 쪽이 앞선다 (p 가 작다)
    assert groups[0].lead.key == "CH_B"


def test_same_targets_and_same_counterexamples_still_fold():
    """반례까지 같으면 접는다 - 교락의 정의 그대로다 (설비 롤업 ~ 챔버)."""
    a = _cand("a:1", "ETCH9", 0.8, 0.02, ["W1", "W2", "W3"], level="equipment")
    b = _cand("b:1", "ETCH9_B", 0.8, 0.02, ["W1", "W2", "W3"])
    for c in (a, b):
        c["control_wafers"] = ["C1"]
        c["control_pass"] = 1

    groups = evidence.build_bundle([_finding("hyp_a", "a", "ok", [a]),
                                    _finding("hyp_b", "b", "ok", [b])]).ranked_groups()
    assert len(groups) == 1 and groups[0].confounded


def test_evidence_list_is_capped_and_says_how_many_were_hidden(monkeypatch):
    """근거 목록에 상한이 있고, 잘린 수를 숨기지 않는다.

    후보는 도구마다 `COMMONALITY_TOP_K` 만큼 나올 수 있고 계측 축은 무신호에서도
    절반 가까이가 판별선을 넘는다. 상한이 없으면 근거를 살리려던 변경이 리포트와
    운영 LLM 프롬프트를 수십 블록으로 채워 오히려 못 읽게 만든다.
    """
    import ya_config
    from graph import nodes

    monkeypatch.setattr(ya_config, "REPORT_MAX_EVIDENCE", 2)
    findings = [
        _finding(f"hyp_{i}", f"h{i}", "ok",
                 [_cand(f"{i}:1", f"K{i}", 0.9 - i / 100, 0.01 + i / 100, [f"W{i}"])])
        for i in range(5)
    ]
    bundle = evidence.build_bundle(findings)
    update = {}
    nodes._record_evidence(update, bundle.ranked_groups(), None)

    assert len(update["final_claims"]) == 2
    assert update["final_claims"][-1]["more_below"] == 3
    # 잘렸다는 사실이 리포트에 나온다
    report = nodes.report_node({
        "target_wafers": ["W0"], "target_source": "manual", "target_group": ["W0"],
        "status_summary": "s", "findings": [], "final_hypothesis": "h",
        "final_confidence": 0.9, "finalize_status": "confirmed",
        "final_claims": update["final_claims"],
    })["report"]
    assert "순위 밖 3건은 생략" in report


def test_the_picked_group_is_never_truncated_away(monkeypatch):
    """상한을 넘겨도 **LLM 이 지목한 묶음**은 남는다.

    1등이 동점으로 여럿일 때 LLM 이 정렬상 뒤쪽을 지목하면 상한 밖으로 밀려날 수
    있다. 그러면 리포트에 서술의 축이 없어지고, 승인 문구가 참조할 대상도 사라져
    게이트가 StopIteration 으로 죽는다(상한을 넣으면서 실제로 그렇게 됐다).
    """
    import ya_config
    from graph import nodes

    monkeypatch.setattr(ya_config, "REPORT_MAX_EVIDENCE", 2)
    findings = [
        _finding(f"hyp_{i}", f"h{i}", "ok",
                 [_cand(f"z{i}:1", f"K{i}", 0.9, 0.01, [f"W{i}"])])   # 전부 동점
        for i in range(5)
    ]
    groups = evidence.build_bundle(findings).ranked_groups()
    assert len({g.rank_key for g in groups}) == 1, "이 fixture 는 전부 동점이어야 한다"

    last = groups[-1]                       # 정렬상 맨 뒤 = 상한 밖
    update = {}
    nodes._record_evidence(update, groups, last)

    claims = update["final_claims"]
    assert len(claims) == 2
    assert sum(1 for c in claims if c["picked_by_llm"]) == 1
    assert claims[-1]["claim_id"] == last.lead.claim_id
    assert claims[-1]["more_below"] == 3


def test_bundle_reports_which_findings_the_rerun_superseded():
    """버린 사실을 밖으로 내보낸다 - 안 내보내면 감사 기록만 그 후보를 계속 들고 있다.

    폐기 자체는 옳다: group_ids/control_ids 중 하나라도 바뀌면 앞 후보는 분모가
    다른 값이라 거짓이고, 인자가 같으면 같은 후보가 다시 만들어져 손실이 없다.
    문제는 **폐기가 한쪽에만 적용된다**는 것이다. findings 는 그대로 리포트 LLM 에
    넘어가고 운영 프롬프트는 그 수치를 "그대로 인용하라" 고 지시하므로, 무엇이
    대체됐는지 말하지 않으면 게이트가 버린 후보를 리포트가 근거로 인용한다.
    """
    stale = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:CC002000:ETCH1_A",
             "key": "ETCH1_A"}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [stale]),
        _finding("hyp_ppid_commonality", "ppid_commonality", "no_signal", []),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "no_signal", []),
    ])
    # 0번만 대체됐다. 1번은 다른 축이므로 대체가 아니다 - 축을 안 보고 세면
    # 앞선 축의 근거가 통째로 "대체됨" 으로 지워진다.
    assert b.superseded == frozenset({0})
    assert b.claims == {}


def test_a_failed_rerun_does_not_supersede_the_previous_run():
    """인자 오류로 실패한 재실행은 앞 결과를 안 버린다 - 그러니 대체도 아니다.

    폐기와 대체 표시는 같은 사건의 두 얼굴이라 한쪽만 움직이면 어긋난다. 실패한
    재실행에서 표시만 붙으면 살아 있는 근거에 "대체됨" 이 찍힌다.
    """
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
        _finding("hyp_eqp_ch_commonality", None, None, None,
                 result="오류: 실행 실패 (KeyError: 'legend')"),
    ])
    assert b.superseded == frozenset()
    assert set(b.claims) == {CAND_PASS["claim_id"]}


def test_a_single_run_supersedes_nothing():
    """한 번만 돈 축은 대체가 없다 - 기본값이 비어 있어야 한다."""
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [CAND_PASS])])
    assert b.superseded == frozenset()


def test_an_empty_rerun_supersedes_nothing_it_did_not_drop():
    """후보를 하나도 안 낸 실행은 버릴 것이 없으니 대체도 아니다.

    `superseded` 는 "claims 에서 빠진 실행" 이다. 후보 0건인 실행까지 담으면
    리포트에 "그 실행의 후보는 근거가 아니다" 라는 **없는 후보에 대한 문장**이
    붙고, 아무 것도 안 버린 재실행마다 한 줄씩 쌓여 보고서를 못 읽게 만든다.
    """
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "no_signal", []),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "no_signal", []),
    ])
    assert b.superseded == frozenset()


def test_every_superseded_run_is_reported_not_just_the_first():
    """대체가 2건 이상이면 2건 다 나와야 한다 - 1건짜리 입력만 넣으면 못 잡는다."""
    first = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:S1:A", "key": "A"}
    second = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:S1:B", "key": "B"}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [first]),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [second]),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "no_signal", []),
    ])
    assert b.superseded == frozenset({0, 1})


def test_bundle_names_the_claims_a_rerun_dropped():
    """어떤 claim_id 가 대체됐는지 이름으로 답할 수 있어야 한다.

    LLM 은 재실행 뒤에도 앞 실행의 claim_id 를 대화 문맥에서 그대로 보고 있다
    (tools_node 가 도구 결과를 ToolMessage 로 싣는다). 그것을 제출했을 때 게이트가
    "도구 결과에 없다" 고 답하면 **거짓**이다 - 있었고, 뒤 실행이 대체했다.
    """
    stale = {**CAND_PASS, "claim_id": "eqp_ch_commonality:chamber:S1:OLD", "key": "OLD"}
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [stale]),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "no_signal", []),
    ])
    assert b.dropped_claims == {"eqp_ch_commonality:chamber:S1:OLD": "hyp_eqp_ch_commonality"}


def test_a_revived_claim_is_not_listed_as_dropped():
    """되살아난 claim_id 는 '대체된 것' 목록에 없어야 한다.

    게이트에서는 무해하다(claims 에 있으면 `claim is None` 분기를 안 탄다). 그래도
    필드가 거짓을 담고 있으면 다음에 그것을 읽는 자리가 틀린 답을 받는다 -
    `superseded` 를 살아남음 기준으로 좁혀 놓고 이쪽만 안 좁히면 두 필드가 서로
    다른 이야기를 한다.
    """
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
    ])
    assert b.dropped_claims == {}
    assert set(b.claims) == {CAND_PASS["claim_id"]}
    assert b.superseded == frozenset()


# ---------------------------------------------- 크래시한 축은 '안 돌린' 축이 아니다
def _crash(tool):
    """tools_node 가 도구 실패를 적는 모양 - result 는 오류 문자열이고 failed 가 붙는다."""
    return {"loop": 1, "tool": tool, "args": {},
            "result": f"오류: {tool} 실행 실패 (RuntimeError: DB 연결 끊김). ",
            "failed": True, "thought": "t"}


def test_a_crashed_tool_is_separated_from_the_ones_never_tried():
    """실패한 도구를 ran 에서 빼는 것만으로는 부족하다 - 따로 셀 수 있어야 한다.

    실패 축이 '안 돌린 축' 과 구분되지 않으면 게이트는 방금 터진 도구를 다시
    부르라고 이름을 대고, 리포트는 시도조차 안 한 것처럼 적는다. 조치가 다르다
    (인프라 확인 vs 축을 더 보기).
    """
    b = evidence.build_bundle([_crash("hyp_ppid_commonality")])
    assert b.ran == set()
    assert b.failed == {"hyp_ppid_commonality"}


def test_a_crashed_tool_that_later_succeeded_is_not_failed():
    """분기 반대쪽 - 재실행이 결과를 냈으면 그 축은 봤다. 실패로 남기면 거짓이다."""
    b = evidence.build_bundle([
        _crash("hyp_eqp_ch_commonality"),
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
    ])
    assert b.ran == {"hyp_eqp_ch_commonality"}
    assert b.failed == frozenset()


def test_an_error_string_without_the_failed_mark_is_not_counted_as_a_crash():
    """실패 표시는 tools_node 가 붙인다 - 문자열 모양으로 넘겨짚지 않는다.

    'finalize 판정 뒤의 잔여 호출 생략' 같은 문자열 결과도 dict 가 아니다.
    그것까지 실패로 세면 커버리지가 없는 장애를 보고한다.
    """
    b = evidence.build_bundle([_finding("hyp_ppid_commonality", None, None, None,
                                        result="분석 종료로 생략")])
    assert b.failed == frozenset()


def test_a_candidate_with_no_null_reference_is_not_called_the_samples_best():
    """참조 회차가 0이면 p = 바닥 = 1.0 인데, 그것은 '이 표본의 최강' 이 아니다.

    옛 코드에서는 바닥이 `1/(회차+1)` 이라 이 분기가 켜질 수 없었다. 귀무 참조집합을
    표본 크기로 좁히면서 바닥이 1.0 인 후보가 생겼고, 그때 "이 표본의 최소값" 딱지는
    **정반대 뜻**을 붙인다 - 비교 대상이 하나도 없었던 후보가 "낼 수 있는 최강" 으로
    읽힌다. 분리 점수 1.0 과 함께 나가면 엔지니어가 그것을 근거로 설비를 세운다.
    """
    line = evidence.format_evidence_line(
        {**CAND_PASS, "p_permutation": 1.0, "p_min_possible": 1.0})
    assert "이 표본의 최소값" not in line
    assert "비교" in line               # 왜 판단할 수 없는지는 말해 준다


def test_a_real_floor_is_still_marked_as_the_samples_best():
    """분기 반대쪽 - 진짜 바닥에 닿은 후보의 딱지는 그대로 있어야 한다.

    한쪽만 막으면 "1.0 이면 빼기" 대신 "딱지를 아예 없애기" 로 고쳐도 안 잡힌다.
    """
    line = evidence.format_evidence_line(
        {**CAND_PASS, "p_permutation": 0.05, "p_min_possible": 0.05})
    assert "이 표본의 최소값" in line


# --- 포함관계(롤업) vs 진짜 교락 -------------------------------------------
#
# 접힌 두 이름이 **한 설명의 두 해상도**(설비 PHOT7 ⊃ 챔버 PHOT7_B)인지 **다른 두
# 설명**(챔버 vs 레시피)인지는 엔지니어에게 완전히 다른 정보다. 앞의 것은 "현재
# 증거로는 구분되지 않는다" 고 적으면 당연한 소리가 되고, 뒤의 것만이 다음에 무엇을
# 볼지 정하는 진짜 미해결이다. 판별은 legend 컬럼의 포함관계로 한다 - level 이름을
# 알아보거나 key 문자열을 파싱하면 축이 늘 때마다 깨진다(hypotheses.yaml 이 key
# 파싱을 명시적으로 금지한다).


def _nested_pair():
    """같은 가설의 두 해상도. 설비 = 챔버의 롤업."""
    coarse = _cand("h:equipment:PHOT7", "PHOT7", 0.667, 0.03,
                   ["W1", "W2"], level="equipment")
    fine = _cand("h:chamber:PHOT7_B", "PHOT7_B", 0.667, 0.03,
                 ["W1", "W2"], level="chamber")
    coarse["level_columns"] = {"eqp_id": "PHOT7"}
    fine["level_columns"] = {"eqp_id": "PHOT7", "ch_id": "B"}
    return coarse, fine


def test_a_rolled_up_name_is_not_reported_as_confounding():
    """설비 ⊃ 챔버는 교락이 아니다 - 같은 설명을 굵게 부른 것뿐이다."""
    coarse, fine = _nested_pair()
    groups = evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [coarse, fine])]).ranked_groups()

    d = evidence.group_to_dict(groups[0])
    assert [o["key"] for o in d["rolled_up_as"]] == ["PHOT7"]
    assert d["confounded_with"] == []


def test_the_finer_name_leads_a_nested_group():
    """의뢰 대상이 되는 쪽(챔버)이 대표다.

    지금은 p·score 가 같아 claim_id 문자열 순서('c' < 'e')로 우연히 챔버가 앞선다.
    이름이 바뀌면 뒤집히는데, 그때 리포트는 "설비 PHOT7 을 보라(챔버 PHOT7_B 로도
    설명 가능)" 이라고 적어 조사 범위를 쓸데없이 넓힌다.
    """
    coarse, fine = _nested_pair()
    # 문자열 순서를 일부러 뒤집는다 - 지금 챔버가 앞서는 것은 'c' < 'e' 덕분이다
    coarse["claim_id"], fine["claim_id"] = "a:equipment:PHOT7", "z:chamber:PHOT7_B"
    groups = evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [coarse, fine])]).ranked_groups()

    assert groups[0].lead.key == "PHOT7_B"


def test_a_nested_line_says_what_would_separate_the_two_resolutions():
    """접혔다는 사실 자체가 '대조군에 그 설비의 다른 챔버가 없다' 의 증명이다.

    접기 기준이 대조군 집합까지 같을 것이므로, 대조군 중 PHOT7 의 다른 챔버를 지난
    wafer 가 하나라도 있으면 두 후보는 애초에 안 접힌다. 그러니 여기서는 "구분되지
    않는다" 로 끝내지 말고 무엇을 보면 갈리는지를 적어야 한다.
    """
    coarse, fine = _nested_pair()
    groups = evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [coarse, fine])]).ranked_groups()

    line = evidence.format_group_line(evidence.group_to_dict(groups[0]))
    assert "교락" not in line
    # 굵은 이름은 그 이름으로 적힌다 - 'PHOT7' 만 찾으면 대표 'PHOT7_B' 에 걸려
    # 새 문장이 없어도 통과한다(실제로 그렇게 통과했다).
    assert "PHOT7(equipment)" in line
    assert "가를 대조가 없다" in line


def test_two_different_explanations_are_still_confounding():
    """레시피는 설비의 해상도가 아니다 - 컬럼이 겹치지 않으면 진짜 교락이다."""
    ch = _cand("a:1", "ETCH9_B", 0.8, 0.02, ["W1", "W2"], level="chamber")
    ppid = _cand("b:1", "PPID_X", 0.8, 0.02, ["W1", "W2"], level="ppid")
    ch["level_columns"] = {"eqp_id": "ETCH9", "ch_id": "B"}
    ppid["level_columns"] = {"ppid": "PPID_X"}

    groups = evidence.build_bundle([
        _finding("hyp_a", "eqp_ch_commonality", "ok", [ch]),
        _finding("hyp_b", "ppid_commonality", "ok", [ppid])]).ranked_groups()

    d = evidence.group_to_dict(groups[0])
    assert [o["key"] for o in d["confounded_with"]] == ["PPID_X"]
    assert d["rolled_up_as"] == []
    assert "교락" in evidence.format_group_line(d)


def test_a_finer_axis_of_another_hypothesis_is_not_a_roll_up():
    """컬럼이 포함관계여도 가설이 다르면 롤업이 아니다.

    metro 후보는 {step_seq, item} 이고 step 통과 후보는 {step_seq} 라 컬럼만 보면
    포함관계로 읽힌다. 그러나 '그 스텝을 지났다' 와 '그 스텝의 계측값이 높다' 는
    해상도 차이가 아니라 서로 다른 두 설명이다.
    """
    passage = _cand("s:1", "CC002000", 0.8, 0.02, ["W1", "W2"], level="step_passage")
    metro = _cand("m:1", "THK >= 129.0", 0.8, 0.02, ["W1", "W2"], level="metro")
    passage["level_columns"] = {"step_seq": "CC002000"}
    metro["level_columns"] = {"step_seq": "CC002000", "item": "THK"}

    groups = evidence.build_bundle([
        _finding("hyp_s", "step_passage_commonality", "ok", [passage]),
        _finding("hyp_m", "metro_commonality", "ok", [metro])]).ranked_groups()

    d = evidence.group_to_dict(groups[0])
    assert d["rolled_up_as"] == []
    assert len(d["confounded_with"]) == 1


def test_a_different_equipment_at_another_step_is_not_a_roll_up():
    """컬럼 이름이 포함관계여도 **값이 다르면** 같은 설명이 아니다.

    타깃 4장이 스텝 A 에서 PHOT8 을, 스텝 B 에서 PHOT7_B 를 지났으면 두 후보는 같은
    wafer 를 가리켜 접힌다. 컬럼 이름만 보고 롤업으로 판정하면 **진짜 교락이 조용히
    '당연한 소리' 로 강등돼** 리포트에서 사라진다 - 접기가 정보 손실이 되는 자리다.
    """
    coarse = _cand("h:equipment:PHOT8", "PHOT8", 0.8, 0.02, ["W1", "W2"],
                   level="equipment", step="CC001000")
    fine = _cand("h:chamber:PHOT7_B", "PHOT7_B", 0.8, 0.02, ["W1", "W2"],
                 level="chamber", step="CC003000")
    coarse["level_columns"] = {"eqp_id": "PHOT8"}
    fine["level_columns"] = {"eqp_id": "PHOT7", "ch_id": "B"}

    groups = evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [coarse, fine])]).ranked_groups()

    d = evidence.group_to_dict(groups[0])
    assert d["rolled_up_as"] == []
    assert [o["key"] for o in d["confounded_with"]] == ["PHOT8"]
