"""다축 독립 신호 케이스 — 근거가 둘인데 계약이 하나만 담는다.

기존 케이스는 전부 한 축만 통과 후보를 낸다. 유일한 2축 케이스인 RECENT_LOT 은
ETCH9_B 와 PPID_X 가 **같은 wafer 를 가리켜**(Jaccard 1.0) 독립 근거가 아니라 한
사실의 두 이름이다. 그래서 "서로 다른 wafer 를 가리키는 근거가 둘 이상"인 무대가
없었고, 게이트가 근거 하나를 버리는 것을 데이터로 재현할 수가 없었다.

M2423 이 그 무대다. 여기서 고정하는 것은 두 가지다:
  (1) fixture 가 설계대로 생겼는가 — 접어야 하는 쌍과 접으면 안 되는 쌍이 다 있는가
  (2) **현재 계약이 근거를 버린다** — 통과 후보 3개가 나오는데 게이트는 1개만 승인한다

(2) 는 지금 red 가 아니라 green 이다. 고쳐야 할 동작을 **현재 모습 그대로 박제**해
두는 것이 목적이다. 다축 집계가 들어오면 이 테스트가 깨지고, 깨지는 것이 정답이다.
"""

import itertools
import sqlite3

import ya_config
from data.generate_dummy import (MULTI_CH_STEP, MULTI_CONTROLS, MULTI_PPID_STEP,
                                 MULTI_ROOT_LOT, MULTI_TARGETS, MULTI_TRUTH_CH,
                                 MULTI_TRUTH_CH_WAFERS, MULTI_TRUTH_EQP,
                                 MULTI_TRUTH_PPID, MULTI_TRUTH_PPID_WAFERS)
from domain import engine, registry


def _passing_candidates():
    """전 축을 돌려 통과 후보만 모은다. 후보마다 어느 가설에서 나왔는지 붙인다."""
    out = []
    for spec in registry.load_hypotheses():
        res = engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS)
        for c in res["candidates"]:
            if c["passes"]:
                out.append({**c, "_hypothesis_id": spec["id"]})
    return out


def _target_wafers_from_db(cand):
    """후보가 가리키는 타깃 wafer 를 step_history 에서 **독립적으로** 되짚는다.

    도구가 싣어 보내는 `target_wafers` 를 그대로 믿고 검사하면 동어반복이 된다.
    여기서는 원천 테이블에서 따로 세어, 도구가 실은 값과 대조하는 데 쓴다.
    """
    ph = ",".join("?" * len(MULTI_TARGETS))
    with sqlite3.connect(ya_config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT wafer_id, eqp_id, ch_id, ppid FROM step_history "
            f"WHERE step_seq = ? AND wafer_id IN ({ph})",
            [cand["step_seq"], *MULTI_TARGETS]).fetchall()
    level, key = cand["level"], cand["key"]
    hit = {
        "equipment": lambda r: r["eqp_id"] == key,
        "chamber": lambda r: f"{r['eqp_id']}_{r['ch_id']}" == key,
        "ppid": lambda r: r["ppid"] == key,
    }[level]
    return {r["wafer_id"] for r in rows if hit(r)}


def test_lot_average_yield_stays_above_threshold():
    """자동 대상 선정에 안 걸려야 한다 — 데모 흐름을 흔들지 않는다는 기존 관례."""
    with sqlite3.connect(ya_config.DB_PATH) as conn:
        ys = [r[0] for r in conn.execute(
            "SELECT yield FROM yield WHERE root_lot_id = ?", (MULTI_ROOT_LOT,))]
    assert len(ys) == len(MULTI_TARGETS) + len(MULTI_CONTROLS)
    assert sum(ys) / len(ys) >= ya_config.YIELD_THRESHOLD


def test_two_axes_produce_passing_candidates():
    """설비/챔버 축과 PPID 축이 **각각** 통과 후보를 낸다.

    두 신호를 다른 스텝에 심었기 때문에 서로를 누르지 않는다. 스텝 통과 축은
    타깃·대조군이 같은 경로라 0 점으로 눌리고, metro 는 이 lot 에 계측이 없다.
    """
    by_axis = {}
    for spec in registry.load_hypotheses():
        res = engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS)
        by_axis[spec["id"]] = [c for c in res["candidates"] if c["passes"]]

    assert len(by_axis["eqp_ch_commonality"]) == 2       # 설비 롤업 + 챔버
    assert len(by_axis["ppid_commonality"]) == 1
    assert by_axis["step_passage_commonality"] == []
    assert by_axis["metro_commonality"] == []

    eqp_keys = {c["key"] for c in by_axis["eqp_ch_commonality"]}
    assert eqp_keys == {MULTI_TRUTH_EQP, f"{MULTI_TRUTH_EQP}_{MULTI_TRUTH_CH}"}
    assert by_axis["ppid_commonality"][0]["key"] == MULTI_TRUTH_PPID

    for c in by_axis["eqp_ch_commonality"]:
        assert c["step_seq"] == MULTI_CH_STEP
    assert by_axis["ppid_commonality"][0]["step_seq"] == MULTI_PPID_STEP


def test_the_two_signals_are_statistically_indistinguishable():
    """어느 쪽이 더 유력한지 데이터가 답하지 못한다 — 재현하려는 상태 자체다.

    둘 다 4/6 대 0/6 이라 분리 점수도 순열 p 도 같다. 순위를 매길 근거가 없다는
    것이 사실이고, 정밀분석을 의뢰하는 엔지니어가 알아야 하는 것도 그 사실이다.
    지금 게이트는 이 동점을 표현할 자리가 없어 임의로 하나만 남긴다.
    """
    cands = _passing_candidates()
    assert len({c["score"] for c in cands}) == 1
    assert len({c["p_permutation"] for c in cands}) == 1
    for c in cands:
        assert (c["target_pass"], c["target_total"]) == (4, 6)
        assert (c["control_pass"], c["control_total"]) == (0, 6)


def test_fixture_has_both_a_foldable_and_an_unfoldable_pair():
    """접기 규칙의 양쪽 경계를 한 lot 이 다 낸다.

    설비 롤업과 챔버는 같은 wafer 를 가리키므로 **합쳐야 하는 쌍**(교락)이고,
    두 신호는 겹침이 부분적이라 **합치면 안 되는 쌍**이다. 하나만 있으면 "전부
    합치는" 규칙이나 "아무것도 안 합치는" 규칙이 그대로 통과해 버린다.
    """
    cands = _passing_candidates()
    jaccards = []
    for a, b in itertools.combinations(cands, 2):
        wa, wb = _target_wafers_from_db(a), _target_wafers_from_db(b)
        jaccards.append(len(wa & wb) / len(wa | wb))

    assert 1.0 in jaccards, "설비 롤업과 챔버가 같은 wafer 를 가리켜야 한다"
    assert any(j < 0.5 for j in jaccards), "두 신호는 뚜렷이 달라야 한다"

    ch = next(c for c in cands if c["level"] == "chamber")
    ppid = next(c for c in cands if c["level"] == "ppid")
    assert _target_wafers_from_db(ch) == set(MULTI_TRUTH_CH_WAFERS)
    assert _target_wafers_from_db(ppid) == set(MULTI_TRUTH_PPID_WAFERS)


def test_candidates_carry_the_wafer_sets_they_point_at():
    """후보가 **자기가 가리키는 wafer 를 싣고 온다** — 교락을 코드가 잡을 재료다.

    카운트만 있으면 "타깃 4/6" 두 개가 같은 4장인지 다른 4장인지 알 수 없다.
    여기서는 도구가 실은 목록을 step_history 에서 따로 센 것과 대조한다 -
    도구가 준 값끼리만 비교하면 동어반복이라 아무것도 안 지킨다.
    """
    for c in _passing_candidates():
        assert set(c["target_wafers"]) == _target_wafers_from_db(c), c["claim_id"]
        # 길이는 카운트와 정의상 같아야 한다. 어긋나면 집계와 목록이 다른 규칙으로
        # 세어진 것이고, 그 순간 겹침 계산이 조용히 틀어진다.
        assert len(c["target_wafers"]) == c["target_pass"]
        assert len(c["control_wafers"]) == c["control_pass"]
        assert c["control_wafers"] == []          # 이 lot 은 대조군이 안 거친다


def test_wafer_sets_reach_the_gate_layer():
    """게이트가 읽는 Claim 까지 목록이 살아서 간다.

    엔진이 실어도 `graph/evidence.py` 의 Claim 이 안 받으면 코드 게이트는 못 본다 -
    coverage_target 이나 split_value 가 지금 그렇게 잘려 나가고 있다. 축 무관 필드인
    wafer 집합은 1급으로 받아야 접기 규칙을 게이트에서 쓸 수 있다.
    """
    from graph import evidence

    findings = [{"loop": 1, "tool": f"hyp_{spec['id']}", "args": {},
                 "result": engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS),
                 "thought": ""}
                for spec in registry.load_hypotheses()]
    bundle = evidence.build_bundle(findings)

    passing = bundle.passing()
    assert len(passing) == 3
    for claim in passing:
        assert claim.target_wafers, claim.claim_id
        assert len(claim.target_wafers) == claim.target_pass

    by_key = {c.key: c for c in passing}
    assert set(by_key[MULTI_TRUTH_PPID].target_wafers) == set(MULTI_TRUTH_PPID_WAFERS)
    chamber = by_key[f"{MULTI_TRUTH_EQP}_{MULTI_TRUTH_CH}"]
    assert set(chamber.target_wafers) == set(MULTI_TRUTH_CH_WAFERS)

    # 그리고 이것이 요점이다: 게이트가 이제 **교락과 독립 근거를 구분할 수 있다.**
    rollup = by_key[MULTI_TRUTH_EQP]
    assert set(rollup.target_wafers) == set(chamber.target_wafers)          # 교락
    assert set(chamber.target_wafers) != set(by_key[MULTI_TRUTH_PPID].target_wafers)


def test_current_contract_drops_evidence():
    """**고쳐야 할 동작의 박제.** 근거가 3개인데 계약이 담는 것은 1개다.

    게이트는 `claim.score >= bundle.top_score(claim.tool)` 로 도구 안 최고 점수만
    승인하고(`graph/nodes.py`), 상태의 `final_claim` 은 dict 하나다(`graph/state.py`).
    셋이 동점이므로 **어느 것을 골라도 승인**되며, 고르는 순간 나머지 둘은 리포트에서
    사라진다. 다축 집계가 들어오면 이 단언이 깨져야 한다.
    """
    cands = _passing_candidates()
    assert len(cands) == 3
    assert len({c["_hypothesis_id"] for c in cands}) == 2

    # 도구별 최고 점수가 곧 그 도구의 통과 후보 전부다 = 동점이라 우열이 없다.
    for hid in ("eqp_ch_commonality", "ppid_commonality"):
        same_tool = [c for c in cands if c["_hypothesis_id"] == hid]
        assert len({c["score"] for c in same_tool}) == 1

    # 그런데 승인되어 리포트로 나가는 것은 claim_id 하나뿐이다.
    from graph import state
    assert state.AgentState.__annotations__["final_claim"] is dict
