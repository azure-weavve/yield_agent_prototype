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


def _sensor_finding(step_seq, cands, status="ok", loop=3):
    # refetch_key 를 실물 모양대로 채운다(tools/sensor_compare.py 의 base 참고) - 특히
    # target_wafers/control_wafers 를 **비워 두지 않는다.** 이 자리가 wafer 목록이
    # 실제로 존재하는 유일한 자리라, 비워 두면 "접기 방지를 위해 후보 dict 대신 여기서
    # wafer 를 읽어 싣자" 는 미래의 훼손이 no-op 인 옛 데이터로는 안 잡힌다.
    return {"loop": loop, "tool": "compare_sensor_distribution",
            "args": {"step_seq": step_seq},
            "result": {"kind": "sensor", "status": status, "candidates": cands,
                       "truncated": 0,
                       "refetch_key": {"step_seq": step_seq,
                                       "target_wafers": ["W001", "W002", "W003"],
                                       "control_wafers": ["W101", "W102", "W103", "W104"],
                                       "sensors": [c.get("sensor_name") for c in cands],
                                       "store_mode": "csv"}},
            "thought": "2단"}


def _sensor_cand(step_seq, name, effect, passes=True):
    return {"claim_id": f"sensor:{step_seq}:{name}", "sensor_name": name,
            "effect_size": effect, "passes": passes,
            "reject_reason": None if passes else f"효과크기 {effect} < 0.8",
            "target_mean": 812.4, "control_mean": 799.1,
            "target_std": 3.0, "control_std": 2.8,
            "n_target": 12, "n_control": 40}


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


def test_sensor_result_needs_its_own_discriminator():
    """센서 결과에도 candidates 키가 있다 - 덕타이핑이면 가설 결과와 섞인다.

    이제 센서도 Claim 이 되지만 **판별자는 여전히 다르다**: 가설은 hypothesis_id,
    센서는 kind 다. kind 가 없는 옛 모양은 어느 쪽으로도 안 들어간다 - 정체를 모르는
    결과를 짐작으로 투영하면 필드가 통째로 어긋난다.
    """
    legacy = {"status": "ok", "candidates": [
        {"sensor_name": "rf_power_steady_avg", "effect_size": 14.99, "passes": True}]}
    b = evidence.build_bundle([{"loop": 1, "tool": "compare_sensor_distribution",
                                "args": {}, "result": legacy, "thought": "t"}])
    assert b.claims == {}
    assert b.ran == set()


def test_sensor_candidate_becomes_a_claim():
    """센서 후보가 claim_id 로 조회된다 - 이것이 이번 변경의 목적이다."""
    b = evidence.build_bundle([_sensor_finding("CC003000",
                                               [_sensor_cand("CC003000", "TEMP_1", 2.31)])])
    c = b.claims["sensor:CC003000:TEMP_1"]
    assert c.kind == "sensor"
    assert (c.step_seq, c.key, c.level) == ("CC003000", "TEMP_1", "sensor")
    assert c.score == 2.31                          # 효과크기가 score 자리에 온다
    assert (c.target_total, c.control_total) == (12, 40)
    assert c.hypothesis_id == ""                    # 등록 가설이 아니다
    assert c.p_permutation is None                  # 설계상 p 를 안 낸다
    assert c.target_wafers == ()                    # 접기 대상이 아니다 (spec §7)
    assert c.extra["target_mean"] == 812.4


def test_sensor_extra_drops_first_class_keeps_distribution():
    """센서 `extra` 축소를 양쪽에서 잠근다.

    1급으로 옮겨 간 넷(effect_size·n_target·n_control·sensor_name)이 extra 에도
    남으면 같은 사실이 두 이름으로 겹쳐 실려, 렌더러가 어느 쪽을 읽을지 정해야
    하고 한쪽만 고치면 조용히 어긋난다. 반대로 분포 넷(target_mean·control_mean·
    target_std·control_std) 은 1급 자리가 없으므로 **남아 있어야** 근거 줄이 읽을
    수 있다 - 통계 후보 쪽의 대칭 단언(`test_axis_specific_fields_survive_in_extra`)
    을 센서에도 그대로 적용한다.
    """
    b = evidence.build_bundle([_sensor_finding("CC003000",
                                               [_sensor_cand("CC003000", "TEMP_1", 2.31)])])
    extra = b.claims["sensor:CC003000:TEMP_1"].extra
    for k in ("effect_size", "n_target", "n_control", "sensor_name"):
        assert k not in extra
    for k in ("target_mean", "control_mean", "target_std", "control_std"):
        assert k in extra


def test_failing_sensor_candidate_is_kept_but_does_not_pass():
    """미통과 센서도 번들에는 남는다 - 게이트가 claim_id 로 조회할 수 있어야 한다.

    두 훼손을 같이 잡는다: (1) `passes` 를 하드코딩하면(예: 항상 True) Task 1 의
    판별선(`SENSOR_PASS_MIN_EFFECT`)이 투영 경계에서 무효화된다. (2) 미통과 후보를
    아예 claims 에서 빼면(예: `if not passes: continue`), LLM 이 미통과 센서를
    정직하게 지목했을 때 게이트가 "claim_id 는 도구 결과에 없다" 는 거짓 반려를
    낸다 - M3 에서 이미 비싸게 배운 실패 모드다.
    """
    b = evidence.build_bundle([_sensor_finding(
        "CC003000", [_sensor_cand("CC003000", "TEMP_1", 0.05, passes=False)])])
    c = b.claims["sensor:CC003000:TEMP_1"]
    assert c.passes is False
    assert c.reject_reason == "효과크기 0.05 < 0.8"
    assert b.passing() == []


def test_sensor_does_not_enter_coverage_vocabulary():
    """센서 status 는 ran/statuses 에 들어오지 않는다.

    들어오면 게이트 (3)의 `ran_statuses <= NO_DATA_STATUSES` 가 센서의 'ok' 때문에
    영영 False 가 되어 no_comparable_data 가 안 열리고, 센서의 no_signal 이 1단의
    것으로 둔갑해 축을 하나도 안 돌리고 "대조한 축에서는 못 찾았다" 로 끝난다.
    ran/statuses 는 '등록 축 커버리지' 전용 어휘다.
    """
    b = evidence.build_bundle([
        _sensor_finding("CC003000", [], status="no_signal")])
    assert b.ran == set()
    assert b.statuses == {}

    # 후보 0건 경로만으로는 부족하다 - `ran.add`/`statuses[...] =` 를 후보 루프
    # **안**에 넣는 훼손은 후보가 있어야만 실행돼 위 단언을 빠져나간다.
    b2 = evidence.build_bundle([
        _sensor_finding("CC003000", [_sensor_cand("CC003000", "TEMP_1", 2.3)])])
    assert b2.ran == set()
    assert b2.statuses == {}


def test_second_sensor_call_on_another_step_keeps_the_first():
    """다른 스텝의 센서 호출은 재실행이 아니라 다른 질문이다.

    tool 이름으로 앞 후보를 버리는 폐기 규칙의 근거는 '그룹이 바뀌어 분모가 달라졌다'
    인데, 센서는 group/control 이 주입이라 항상 같고 step_seq 만 다르다. tool 키로
    묶으면 스텝 B 호출이 스텝 A 근거를 조용히 지운다.
    """
    b = evidence.build_bundle([
        _sensor_finding("CC003000", [_sensor_cand("CC003000", "TEMP_1", 2.3)], loop=3),
        _sensor_finding("CD004000", [_sensor_cand("CD004000", "RF_2", 1.9)], loop=4)])
    assert set(b.claims) == {"sensor:CC003000:TEMP_1", "sensor:CD004000:RF_2"}
    assert b.superseded == frozenset()
    assert b.dropped_claims == {}


def test_statistical_passing_excludes_sensors():
    """지목 가능한 후보와 근거로 실리는 후보를 가르는 자리."""
    b = evidence.build_bundle([
        _finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok", [CAND_PASS]),
        _sensor_finding("CC003000", [_sensor_cand("CC003000", "TEMP_1", 2.3)])])
    assert len(b.passing()) == 2                        # 근거로는 둘 다
    assert [c.claim_id for c in b.statistical_passing()] == [CAND_PASS["claim_id"]]


def test_sensor_candidates_do_not_fold_into_one_group():
    """한 호출의 top-K 는 전부 같은 wafer 집합이라, 목록을 실으면 열 개가 한 덩어리로
    접혀 '같은 사실의 열 가지 이름' 이 된다. 온도와 파티클은 다른 설명이다."""
    b = evidence.build_bundle([_sensor_finding("CC003000", [
        _sensor_cand("CC003000", "TEMP_1", 2.3),
        _sensor_cand("CC003000", "RF_2", 1.9)])])
    groups = b.ranked_groups()
    assert len(groups) == 2

    # 효과크기로 우열을 매기면 안 된다 - `dominates` 가 점수로 가르면 이 둘은
    # 1등/2등으로 갈리고, 도구 자신의 note("연동된 센서는 함께 움직이므로 순위만으로
    # 원인을 가릴 수 없다")가 투영 경계에서 정확히 뒤집힌다. 등수가 같고 `tied=True`
    # 여야 한다. 표시 순서(sort_key)는 여전히 -score 라 TEMP_1 이 위에 오지만, 그건
    # 화면 순서일 뿐 등수가 아니다.
    ranks = evidence.layer_ranks(groups)
    assert ranks[0] == ranks[1]
    dicts = evidence.groups_to_dicts(groups)
    assert all(d["tied"] for d in dicts)
    # 센서는 p 를 안 내므로 `_is_statistical` 이 항상 False 다. 그렇다고 사유가
    # "귀무 표본이 없다"(no_statistics, 표본을 모으면 풀린다는 뜻으로 읽힌다)면
    # 안 된다 - 이 둘이 안 갈리는 것은 `dominates` 의 센서 하한이 **의도적으로**
    # 거부하는 것이라 표본을 아무리 늘려도 영원히 안 갈린다. 사유는
    # `sensor_correlated` 여야 한다.
    assert all(d["tie_reason"] == "sensor_correlated" for d in dicts)
    # 사유 이름만 잠그면 실제로 나가는 문장은 무방비다 - 도구 note 그대로
    # "연동된 센서는 함께 움직여" 가 리포트 문장에 실제로 찍히는지 확인한다.
    line = evidence.format_group_line(dicts[0])
    assert "연동된 센서는 함께 움직여" in line
    assert "통계적 근거가 없어" not in line


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


def test_sensor_evidence_line_replaces_the_fake_2x2():
    """센서에는 2x2 가 없다. 그대로 태우면 '타깃 0/12 통과 · 대조군 0/40 통과' 가
    찍히는데(target_total 자리에 n_target 이 온다 - 0/0 이 아니다), 그것은 숫자가
    없는 것이 아니라 **그럴듯한 틀린 숫자**다 - 엔지니어는 대조가 실패한 줄로 읽는다.

    부분 문자열만 따로 보면 타깃/대조군 전치나 claim_id 누락도 통과한다 - 숫자가
    **어디에 붙는지**까지 잠그기 위해 줄 전체를 등가 비교한다.
    """
    b = evidence.build_bundle([_sensor_finding("CC003000",
                                               [_sensor_cand("CC003000", "TEMP_1", 2.31)])])
    line = evidence.format_evidence_line(asdict(b.claims["sensor:CC003000:TEMP_1"]))
    assert line == ("sensor:CC003000:TEMP_1 · 효과크기 2.31 · "
                     "타깃 n=12 평균 812.4 · 대조군 n=40 평균 799.1")
    assert "통과" not in line
    assert "분리 점수" not in line


def test_statistical_evidence_line_is_unchanged():
    """센서 분기를 넣다가 1단 줄을 건드리면 안 된다 (리포트가 이 문장을 그대로 쓴다).

    등가 비교인 이유는 위와 같다 - 부분 문자열만 보면 구분자(` · `)를 바꾸는 훼손도
    통과한다.
    """
    b = evidence.build_bundle([_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality",
                                        "ok", [CAND_PASS])])
    line = evidence.format_evidence_line(asdict(b.claims[CAND_PASS["claim_id"]]))
    assert line == ("eqp_ch_commonality:chamber:CC002000:ETCH9_B · 분리 점수 1.0 · "
                     "타깃 3/3 통과 · 대조군 0/6 통과")


# ---------------------------------------------------------------- 접기와 순위

def _cand(claim_id, key, score, p, wafers, level="chamber", step="CC002000",
          floor=0.001):
    return {"claim_id": claim_id, "level": level, "step_seq": step, "key": key,
            "passes": True, "reject_reason": None, "score": score,
            "target_pass": len(wafers), "target_total": 6,
            "control_pass": 0, "control_total": 6,
            "p_permutation": p, "p_min_possible": floor,
            "target_wafers": list(wafers), "control_wafers": []}


def _groups(*cands):
    """후보마다 축을 하나씩 줘서 묶음 목록을 만든다 (접히지 않게 wafer 를 가른다)."""
    return evidence.build_bundle([
        _finding(f"hyp_{i}", f"h{i}", "ok", [c])
        for i, c in enumerate(cands)]).ranked_groups()


def _by_key(groups, key):
    return next(g for g in groups if g.lead.key == key)


def test_candidates_at_their_floor_do_not_lose_to_a_smaller_p():
    """바닥에 걸린 후보는 더 작은 p 에게 지지 않는다.

    X 는 참조가 8회뿐이라 완전 분리인데도 p 0.111 에서 멈춘다. Y 는 참조가 300회라
    더 내려갈 수 있었는데 0.05 에서 멈췄다. 공통 해상도는 거친 쪽인 0.111 이고,
    거기서는 둘 다 "그 이하" 라 갈리지 않는다. 예전 규칙은 Y 가 이겼다고 봤다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1", "W2"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W3", "W4"], floor=0.003))
    gx, gy = _by_key(groups, "AT_FLOOR"), _by_key(groups, "SMALL_P")
    assert not evidence.dominates(gx, gy)
    assert not evidence.dominates(gy, gx)


def test_a_candidate_that_wins_at_the_shared_resolution_dominates():
    """공통 해상도에서 실제로 갈리면 이긴다. 규칙이 전부를 동점으로 만들면 안 된다."""
    groups = _groups(
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W3", "W4"], floor=0.003),
        _cand("z:1", "TINY_P", 0.55, 0.002, ["W5", "W6"], floor=0.003))
    gy, gz = _by_key(groups, "SMALL_P"), _by_key(groups, "TINY_P")
    assert evidence.dominates(gz, gy)
    assert not evidence.dominates(gy, gz)


def test_statistical_evidence_beats_evidence_without_statistics():
    """p 없는 증거는 통계 등급 아래다 - 등급이 다르면 값을 안 본다.

    분리 점수 0.99 짜리 무통계 증거가 p 0.40 짜리 통계 증거를 못 이긴다.
    """
    groups = _groups(
        _cand("s:1", "WITH_P", 0.55, 0.40, ["W1", "W2"], floor=0.01),
        _cand("b:1", "NO_P", 0.99, None, ["W3", "W4"], floor=None))
    gs, gb = _by_key(groups, "WITH_P"), _by_key(groups, "NO_P")
    assert evidence.dominates(gs, gb)
    assert not evidence.dominates(gb, gs)


def test_a_floor_of_one_means_no_statistics_at_all():
    """참조 0회(바닥 1.0)는 "우연이다" 가 아니라 "비교할 표본이 없었다" 다.

    통계가 실제로 없으므로 p 를 안 내는 증거와 같은 등급으로 내린다. 분리 점수가
    1.0 이어도 마찬가지다 - 그 숫자를 근거로 설비를 세우면 안 된다.
    """
    groups = _groups(
        _cand("e:1", "NO_REFERENCE", 1.0, 1.0, ["W1", "W2"], floor=1.0),
        _cand("w:1", "WEAK", 0.55, 0.40, ["W3", "W4"], floor=0.01))
    ge, gw = _by_key(groups, "NO_REFERENCE"), _by_key(groups, "WEAK")
    assert evidence.dominates(gw, ge)
    assert not evidence.dominates(ge, gw)


def test_score_breaks_ties_only_inside_one_axis():
    """분리 점수는 축을 가로지르면 안 되는 자다.

    점수는 탐색 폭에 따라 부풀고 그 정도가 축마다 다르다(계측 축은 무신호에서도
    후보의 48.7%가 판별선을 넘는다). p 가 같을 때 축을 넘어 점수로 가르면 탐색이
    넓은 축이 늘 이긴다 - p 를 1순위로 둔 이유가 사라진다.
    """
    same_axis = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [
            _cand("a:1", "HIGH", 0.90, 0.02, ["W1", "W2"]),
            _cand("a:2", "LOW", 0.60, 0.02, ["W3", "W4"])])]).ranked_groups()
    assert evidence.dominates(_by_key(same_axis, "HIGH"),
                              _by_key(same_axis, "LOW"))

    cross = _groups(_cand("a:1", "HIGH", 0.90, 0.02, ["W1", "W2"]),
                    _cand("b:1", "LOW", 0.60, 0.02, ["W3", "W4"]))
    hi, lo = _by_key(cross, "HIGH"), _by_key(cross, "LOW")
    assert not evidence.dominates(hi, lo)      # 축이 다르면 점수로 못 가른다
    assert not evidence.dominates(lo, hi)


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


def test_layers_handle_intransitive_incomparability():
    """비교 불가는 이행적이지 않다 - 그래서 정렬이 아니라 층위여야 한다.

    X~Y, X~Z 인데 Z>Y 다. 비교자로 정렬하면 입력 순서에 따라 답이 달라진다.
    Z 는 아무에게도 안 지므로 1등, X 도 아무에게도 안 지므로 1등, Y 는 Z 에게
    졌으므로 2등이다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W2"], floor=0.003),
        _cand("z:1", "TINY_P", 0.55, 0.002, ["W3"], floor=0.003))
    ranks = dict(zip((g.lead.key for g in groups), evidence.layer_ranks(groups)))
    assert ranks == {"AT_FLOOR": 1, "TINY_P": 1, "SMALL_P": 2}


def test_evidence_without_statistics_leads_when_nothing_else_ran():
    """통계 후보가 0건이면 p 없는 증거가 1등 층으로 올라온다.

    등급은 절대 순서가 아니라 상대 순서다 - 위가 비면 아래가 1등이다. 이것이
    A 작업(센서·잔차를 claim 으로 승격)에서 그 증거가 리포트에 도달하는 경로다.
    """
    groups = _groups(_cand("b:1", "NO_P", 0.9, None, ["W1"], floor=None),
                     _cand("c:1", "ALSO_NO_P", 0.7, None, ["W2"], floor=None))
    assert evidence.layer_ranks(groups) == [1, 1]


def test_layer_ranks_terminates_when_domination_cycles(monkeypatch):
    """지배가 순환하면 한 층으로 내고 끝낸다 - 안전판이 없으면 무한 루프다.

    설계 문서 §2.1 이 지배 관계의 이행성을 증명하지만 그 증명은 등급·축내 점수
    조건이 섞이지 않은 경우를 다룬다. 증명이 닿지 않는 자리에서 순환이 나면 분석
    전체가 멎으므로, 안전판 자체를 잠근다.

    **안전판이 사라져도 행(hang)이 아니다.** 루프가 묶음 수로 묶여 있어 등수가 0으로
    남고, 그것을 아래에서 잡는다. 실패가 스위트를 멈추면 훼손 파일이 다음 실행의
    기준선이 되는 사고가 난다(2026-08-28). 이 보장은 `layer_ranks` 의 루프 경계에
    있으므로 `dominates` 를 어떻게 부르든(메모이제이션·인라인) 그대로 유지된다.
    """
    # **묶음을 먼저 만들고 그다음에 훼손한다.** `_groups` 안의 `ranked_groups()` 가
    # 이미 `layer_ranks` 를 부르므로, 순서를 뒤집으면 픽스처부터 어긋난다.
    groups = _groups(_cand("a:1", "A", 0.9, 0.01, ["W1"]),
                     _cand("b:1", "B", 0.8, 0.02, ["W2"]))
    monkeypatch.setattr(evidence, "dominates", lambda a, b: True)   # 전원이 서로를 이긴다
    assert evidence.layer_ranks(groups) == [1, 1]


def test_display_order_follows_the_layer_not_the_raw_p():
    """표시 순서가 등수와 어긋나면 리포트에서 [근거 2] 가 [근거 1] 위에 찍힌다.

    바닥에 걸린 AT_FLOOR 는 p 가 0.111 로 커서 전순서 키로는 맨 뒤인데 등수는
    1등이다. `ranked_groups` 는 등수를 먼저 보고 정렬해야 한다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W2"], floor=0.003),
        _cand("z:1", "TINY_P", 0.55, 0.002, ["W3"], floor=0.003))
    assert [g.lead.key for g in groups][-1] == "SMALL_P"   # 2등이 맨 뒤
    assert evidence.layer_ranks(groups) == [1, 1, 2]


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


def test_tie_line_explains_resolution_not_equal_numbers():
    """동점 문장이 이유를 옛 규칙으로 설명하면 안 된다.

    새 규칙에서는 p 가 0.111 과 0.050 으로 **달라도** 동점이다. "순열 p 와 분리
    점수가 같아" 라고 적으면 바로 옆에 다른 숫자를 찍어 놓고 같다고 말하는 꼴이다.

    **동점 문장 고유의 구절로 단언한다.** 그냥 "해상도" 만 찾으면 같은 함수의
    롤업 분기("굵은 해상도로는 ...")가 대신 맞아 줘서, 동점 문장이 통째로
    사라져도 통과한다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 1.0, 0.111, ["W1"], floor=0.111),
        _cand("y:1", "SMALL_P", 0.55, 0.050, ["W2"], floor=0.003))
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["resolution", "resolution"]
    line = evidence.format_group_line(dicts[0])
    assert "이 표본들이 낼 수 있는 해상도에서는 갈리지 않아" in line
    assert "순열 p 와 분리 점수가 같아" not in line


def test_a_p_pinned_to_its_floor_is_a_resolution_tie_even_when_the_numbers_match():
    """p 숫자가 같아도 **한쪽이 자기 바닥에 걸려 있으면** 해상도 문제다.

    바닥에 걸린 값은 "그 이하" 라는 뜻이라, 우연히 상대와 같은 숫자로 찍혔을 뿐
    진짜 우열은 모른다. 참조 회차를 늘리면 바닥이 내려가 실제로 갈린다. 이것을
    `cross_axis` 로 부르면 **"더 모아도 소용없다" 는 정반대 안내**가 나간다 -
    바로 같은 줄이 "(이 표본의 최소값)" 을 찍고 있는데도.

    "원 p 가 서로 다른가" 로 물으면 이 경우를 놓친다. 물어야 할 것은 **clamp 가
    우열을 덮었는가**다.
    """
    groups = _groups(
        _cand("x:1", "AT_FLOOR", 0.9, 0.1111, ["W1"], floor=0.1111),   # 참조 8회
        _cand("y:1", "MEASURED", 0.3, 0.1111, ["W2"], floor=0.0556))   # 참조 17회
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["resolution", "resolution"]
    assert "해상도에서는 갈리지 않아" in evidence.format_group_line(dicts[0])


def test_a_cross_axis_tie_does_not_blame_the_resolution():
    """축이 달라 못 가르는 것을 "해상도" 탓으로 적으면 엔지니어가 헛수고를 한다.

    p 가 정확히 같고 점수가 0.95 대 0.30 이면 표본 해상도는 둘 다 충분하다. 안
    갈리는 이유는 **분리 점수를 축 너머로는 쓰지 않기로 한 규칙** 이다. 해상도
    탓으로 적으면 wafer 를 더 모으는데, 그래도 영원히 안 갈린다. 갈라야 할 것은
    두 축을 직접 가르는 대조다.
    """
    groups = _groups(
        _cand("x:1", "BIG_SCORE", 0.95, 0.03, ["W1"], floor=0.003),
        _cand("y:1", "SMALL_SCORE", 0.30, 0.03, ["W2"], floor=0.003))
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["cross_axis", "cross_axis"]
    line = evidence.format_group_line(dicts[0])
    assert "축이 달라 분리 점수로는 가르지 않아" in line
    assert "해상도에서는 갈리지 않아" not in line


def test_a_tie_with_no_statistics_at_all_says_so():
    """참조 0회끼리의 동점을 "해상도" 로 설명하면 한 줄 안에서 말이 어긋난다.

    바로 윗줄이 "비교 가능한 귀무 표본이 없어 판단 불가" 를 찍어 놓고 다음 줄에서
    "해상도에서 갈리지 않는다" 를 붙이면, 없는 통계의 해상도를 말하는 꼴이다.
    """
    groups = _groups(
        _cand("x:1", "NOREF_A", 1.0, 1.0, ["W1"], floor=1.0),
        _cand("y:1", "NOREF_B", 0.5, 1.0, ["W2"], floor=1.0))
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["no_statistics", "no_statistics"]
    line = evidence.format_group_line(dicts[0])
    assert "어느 쪽도 통계적 근거가 없어" in line
    assert "해상도" not in line


def test_a_tie_between_a_sensor_and_a_zero_reference_candidate_is_no_statistics():
    """센서와 참조 0회 1단 후보의 동점 사유는 `sensor_correlated` 가 아니다.

    둘 다 `_is_statistical` 이 False 라 센서 하한에 걸려 같은 층에 묶이는 것은
    맞다. 그런데 이 쌍은 **표본을 모으면 갈린다** - 참조 회차가 생겨 1단 후보가
    통계 등급이 되는 순간 `dominates` 의 등급 분기(`sx != sy`)가 센서 하한보다
    **먼저** 걸려 1단이 이긴다. `sensor_correlated` 는 "영원히 안 갈린다" 로
    읽히므로 여기서 그 이름을 대면 갈릴 수 있는 것을 포기시킨다 - `_tie_reason`
    docstring 이 경고하는 바로 그 오안내를, 센서 갈래를 넣으면서 저질렀다.

    센서 하한이 **유일한** 이유일 때, 즉 층이 전부 센서일 때만 `sensor_correlated`
    다(그 경우는 위 `test_sensor_candidates_do_not_fold_into_one_group` 이 잠근다).
    """
    b = evidence.build_bundle([
        _finding("hyp_zero_ref", "zero_ref", "ok",
                 [_cand("h:1", "ZERO_REF", 0.99, 1.0, ["W1", "W2"], floor=1.0)]),
        _sensor_finding("CC003000", [_sensor_cand("CC003000", "TEMP_1", 2.3)])])
    groups = b.ranked_groups()
    assert len(groups) == 2                          # 서로 다른 근거라 접히지 않는다
    ranks = evidence.layer_ranks(groups)
    assert ranks[0] == ranks[1]                       # 같은 층으로 묶였다
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["no_statistics", "no_statistics"]


def test_axes_differing_with_equal_scores_is_not_blamed_on_the_axis():
    """축이 달라도 **점수까지 같으면** 축 탓을 하면 안 된다.

    다축 더미(M2423)의 실제 모양이다 - 설비/챔버 축과 레시피 축이 p 0.0303, 점수
    0.667 로 똑같다. 여기서 "축이 달라 분리 점수로는 가르지 않아" 라고 적으면
    점수가 갈랐을 텐데 규칙 때문에 못 갈랐다는 뜻이 되는데, 사실은 같은 축이었어도
    안 갈렸다.
    """
    groups = _groups(
        _cand("x:1", "A", 0.667, 0.0303, ["W1"], floor=0.003),
        _cand("y:1", "B", 0.667, 0.0303, ["W2"], floor=0.003))
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["identical", "identical"]


def test_identical_numbers_are_still_reported_as_identical():
    """같은 축에서 p 도 점수도 같은 동점은 그대로 그렇게 적는다.

    사유를 나눈다고 원래 있던 경우가 다른 이름으로 새면 안 된다.
    """
    groups = evidence.build_bundle([
        _finding("hyp_a", "a", "ok", [_cand("x:1", "A1", 0.7, 0.03, ["W1"]),
                                      _cand("y:1", "A2", 0.7, 0.03, ["W2"])])]).ranked_groups()
    dicts = evidence.groups_to_dicts(groups)
    assert [d["tie_reason"] for d in dicts] == ["identical", "identical"]
    assert "순열 p 도 분리 점수도 같아" in evidence.format_group_line(dicts[0])


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


def test_folded_sensor_branch_omits_the_2x2_and_the_kind_field():
    """`group_to_dict` 의 `folded()` 센서 분기는 지금 도달 불가다 - 센서는
    target_wafers 가 비어 있어 `ranked_groups()` 가 늘 혼자만의 묶음을 만들고,
    그래서 `group.claims[1:]` 가 항상 비어 `folded()` 가 센서로 호출되지 않는다.
    브리프가 시킨 것은 접기 규칙이 바뀌는 날의 방어선이라, 잠금이 없으면 조용히
    썩는다 - 센서 두 개짜리 `ClaimGroup` 을 직접 만들어 호출한다.
    """
    lead = evidence.Claim(
        claim_id="sensor:CC003000:TEMP_1", tool="compare_sensor_distribution",
        hypothesis_id="", step_seq="CC003000", key="TEMP_1", level="sensor",
        passes=True, reject_reason=None, score=2.31, kind="sensor",
        target_pass=0, target_total=12, control_pass=0, control_total=40)
    other = evidence.Claim(
        claim_id="sensor:CC003000:RF_2", tool="compare_sensor_distribution",
        hypothesis_id="", step_seq="CC003000", key="RF_2", level="sensor",
        passes=True, reject_reason=None, score=1.9, kind="sensor",
        target_pass=0, target_total=12, control_pass=0, control_total=40)
    d = evidence.group_to_dict(evidence.ClaimGroup(claims=(lead, other)))
    assert len(d["confounded_with"]) == 1
    folded = d["confounded_with"][0]
    for missing in ("target_pass", "target_total", "control_pass", "control_total",
                    "kind"):
        assert missing not in folded


def test_sensor_lead_does_not_ship_a_pass_count_to_the_report():
    """**실제로 나가는 길은 `folded()` 가 아니라 대표 dict 다.**

    센서는 wafer 목록이 없어 늘 홀로 서므로 바로 위 분기에는 닿지 않고,
    `asdict(group.lead)` 가 그대로 `final_claims` 에 실린다. 그리고 `llm/client.py`
    는 그 목록을 JSON 으로 덤프해 "수치를 그대로 인용하라" 와 함께 리포트 LLM 에
    넘긴다 - 투영이 채워 둔 통과 카운트 0 이 분모와 나란히 실리면 "타깃 0/12 ·
    대조군 0/40" 이라는 **일어나지도 않은 대조 실패**가 리포트 산문에 찍힌다.
    근거 줄(`format_evidence_line`)만 고쳐서는 못 막는 자리다.

    분모(n)는 남긴다 - 효과크기는 표본 수와 함께 읽어야 하고 근거 줄이 그 값을 쓴다.
    """
    b = evidence.build_bundle([_sensor_finding("CC003000",
                                               [_sensor_cand("CC003000", "TEMP_1", 2.31)])])
    d = evidence.groups_to_dicts(b.ranked_groups())[0]
    assert "target_pass" not in d and "control_pass" not in d
    assert (d["target_total"], d["control_total"]) == (12, 40)
    assert "타깃 n=12" in evidence.format_group_line(d)
    # 반대쪽도 잠근다 - kind 를 안 보고 전부 빼면 1단 근거에서 2x2 가 사라진다.
    stat = evidence.groups_to_dicts(evidence.build_bundle(
        [_finding("hyp_eqp_ch_commonality", "eqp_ch_commonality", "ok",
                  [CAND_PASS])]).ranked_groups())[0]
    assert (stat["target_pass"], stat["control_pass"]) == (3, 0)


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
    assert set(evidence.layer_ranks(groups)) == {1}, "이 fixture 는 전부 동점이어야 한다"

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


def test_the_same_equipment_at_another_step_is_not_a_roll_up():
    """스텝이 다르면 같은 설비여도 같은 설명이 아니다.

    `level_columns` 에는 legend 컬럼만 들어 있고 **step_seq 는 없다**(eqp_ch 의 컬럼은
    eqp_id·ch_id 뿐이다). 그런데 후보 키는 (level, step, key) 라 같은 설비가 스텝마다
    별개 후보로 나온다. 스텝을 안 보면 'CC001000 의 PHOT7' 과 'CC003000 의 PHOT7_B' 가
    한 설명의 두 해상도로 판정돼 **진짜 교락이 리포트에서 사라진다.** 근거 줄에는
    step_seq 가 안 찍히므로 읽는 사람이 알아챌 방법도 없다. 같은 설비를 여러 레이어에서
    쓰거나 재작업 스텝에서 다시 타는 경우라 실데이터에서 흔한 모양이다.
    """
    coarse = _cand("h:equipment:CC001000:PHOT7", "PHOT7", 0.8, 0.02, ["W1", "W2"],
                   level="equipment", step="CC001000")
    fine = _cand("h:chamber:CC003000:PHOT7_B", "PHOT7_B", 0.8, 0.02, ["W1", "W2"],
                 level="chamber", step="CC003000")
    coarse["level_columns"] = {"eqp_id": "PHOT7"}
    fine["level_columns"] = {"eqp_id": "PHOT7", "ch_id": "B"}

    d = evidence.group_to_dict(evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [coarse, fine])]).ranked_groups()[0])
    assert d["rolled_up_as"] == []
    assert [o["key"] for o in d["confounded_with"]] == ["PHOT7"]


def test_a_coarser_lead_still_reports_one_explanation_at_two_resolutions():
    """굵은 쪽이 대표가 돼도 "구분되지 않는다" 로 돌아가면 안 된다.

    챔버 분모는 ch_id 결측 wafer 를 빼므로 설비 분모보다 작다. 대조군에 반례가 있으면
    (설비 2/10 vs 챔버 2/5) **굵은 쪽의 분리 점수가 더 커져** 대표가 된다. 판정을
    대표 한 명하고만 하면 세밀한 쪽이 교락으로 흘러, 이 커밋이 없애려던 문장이 그대로
    돌아온다. 관계는 방향이 있을 뿐 대칭이다.
    """
    coarse = _cand("h:equipment:CC001000:PHOT7", "PHOT7", 0.8, 0.02, ["W1", "W2"],
                   level="equipment")
    fine = _cand("h:chamber:CC001000:PHOT7_B", "PHOT7_B", 0.6, 0.02, ["W1", "W2"])
    coarse["level_columns"] = {"eqp_id": "PHOT7"}
    fine["level_columns"] = {"eqp_id": "PHOT7", "ch_id": "B"}

    d = evidence.group_to_dict(evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [coarse, fine])]).ranked_groups()[0])
    assert d["key"] == "PHOT7"                      # 순위 규칙은 그대로 (별건)
    assert [o["key"] for o in d["rolled_up_as"]] == ["PHOT7_B"]
    assert d["confounded_with"] == []
    line = evidence.format_group_line(d)
    assert "교락" not in line and "세밀한 해상도로는 PHOT7_B(chamber)" in line


def test_a_roll_up_is_not_counted_as_a_third_rival_beside_another_hypothesis():
    """레시피가 1등이면 설비·챔버가 **근거 둘**로 세어져 확신도가 부푼다.

    셋이 같은 wafer 를 가리켜 한 묶음이 될 때, 설비와 챔버는 여전히 한 설명이다.
    대표(레시피)와만 대보면 둘 다 교락 목록에 들어가 리포트가 "서로 다른 설명 셋" 을
    말한다 - 접기가 막으려던 바로 그 부풀림이다.
    """
    eq = _cand("h:equipment:CC001000:PHOT7", "PHOT7", 0.6, 0.05, ["W1", "W2"],
               level="equipment")
    ch = _cand("h:chamber:CC001000:PHOT7_B", "PHOT7_B", 0.6, 0.05, ["W1", "W2"])
    pp = _cand("p:ppid:CC001000:PPID_X", "PPID_X", 0.6, 0.01, ["W1", "W2"], level="ppid")
    eq["level_columns"] = {"eqp_id": "PHOT7"}
    ch["level_columns"] = {"eqp_id": "PHOT7", "ch_id": "B"}
    pp["level_columns"] = {"ppid": "PPID_X"}

    d = evidence.group_to_dict(evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [eq, ch]),
        _finding("hyp_ppid", "ppid_commonality", "ok", [pp])]).ranked_groups()[0])
    assert d["key"] == "PPID_X"
    # 설비는 챔버의 굵은 이름이다 - 레시피와 경합하는 제3의 근거가 아니다
    assert [o["key"] for o in d["rolled_up_as"]] == ["PHOT7"]
    assert [o["key"] for o in d["confounded_with"]] == ["PHOT7_B"]
    # 굵은 이름이 대는 상대는 대표가 아니라 **챔버**다
    assert "'PHOT7 통과 · PHOT7_B 미통과'" in evidence.format_group_line(d)


def test_old_findings_without_level_columns_stay_confounded():
    """`level_columns` 를 안 싣던 옛 감사 기록도 오판정 없이 떨어져야 한다.

    빈 사전은 어떤 사전의 부분집합이라, 가드가 없으면 옛 후보가 같은 가설의 새 후보에게
    **무조건** 롤업으로 붙는다. 모르는 것은 교락으로 두는 쪽이 안전하다.
    """
    old = _cand("h:equipment:CC001000:PHOT7", "PHOT7", 0.8, 0.02, ["W1", "W2"],
                level="equipment")                       # level_columns 없음
    new = _cand("h:chamber:CC001000:PHOT7_B", "PHOT7_B", 0.8, 0.02, ["W1", "W2"])
    new["level_columns"] = {"eqp_id": "PHOT7", "ch_id": "B"}

    d = evidence.group_to_dict(evidence.build_bundle([
        _finding("hyp_eqp_ch", "eqp_ch_commonality", "ok", [old, new])]).ranked_groups()[0])
    assert d["rolled_up_as"] == []
    assert [o["key"] for o in d["confounded_with"]] == ["PHOT7"]


def test_a_folded_name_carries_its_own_numbers_into_the_line():
    """접힌 이름은 **자기 분모**를 달고 나간다 - 이름만 적으면 대표와 같은 무게로 읽힌다.

    같은 wafer 를 가리켜도 몇 장 중 몇 장인지는 이름마다 다르다(챔버 분모는 ch_id 가
    결측인 wafer 를 뺀다). 그 수치가 "어느 이름으로 의뢰할 것인가" 의 재료다.
    """
    a = _cand("a:1", "CH_B", 0.8, 0.02, ["W1", "W2"])
    b = _cand("b:1", "PPID_X", 0.8, 0.02, ["W1", "W2"], level="ppid")
    b["target_total"], b["control_total"] = 4, 3
    line = evidence.format_group_line(evidence.group_to_dict(
        evidence.build_bundle([_finding("hyp_a", "a", "ok", [a]),
                               _finding("hyp_b", "b", "ok", [b])]).ranked_groups()[0]))
    assert "타깃 2/4" in line and "대조군 0/3" in line
