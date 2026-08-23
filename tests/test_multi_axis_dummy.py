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


def _bundle():
    from graph import evidence

    findings = [{"loop": 1, "tool": f"hyp_{spec['id']}", "args": {},
                 "result": engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS),
                 "thought": ""}
                for spec in registry.load_hypotheses()]
    return evidence.build_bundle(findings)


def test_rollup_and_chamber_fold_into_one_group():
    """설비 롤업과 챔버는 **한 근거로 접힌다** - 같은 wafer 의 두 이름이다.

    안 접으면 리포트에 근거가 둘로 보이고, 읽는 사람은 독립된 두 증거로 읽는다.
    확신도가 부풀고 정밀분석 의뢰가 둘로 늘어난다.
    """
    groups = _bundle().ranked_groups()
    folded = [g for g in groups if g.confounded]

    assert len(folded) == 1
    keys = {c.key for c in folded[0].claims}
    assert keys == {MULTI_TRUTH_EQP, f"{MULTI_TRUTH_EQP}_{MULTI_TRUTH_CH}"}
    assert set(folded[0].lead.target_wafers) == set(MULTI_TRUTH_CH_WAFERS)


def test_the_two_real_signals_do_not_fold():
    """부분 겹침은 접지 않는다 - 겹치지 않는 wafer 가 두 가설을 가르는 정보다.

    두 신호는 {03,04} 만 공유한다(Jaccard 0.33). 접기 기준을 "충분히 겹치면" 으로
    두면 이런 쌍이 임계값에 따라 합쳐졌다 갈라졌다 하고, 합쳐지는 순간 **무엇이
    다른지가 사라진다.** 그래서 기준은 임의 임계가 아니라 집합 동일이다.
    """
    groups = _bundle().ranked_groups()

    assert len(groups) == 2, "교락 쌍은 접히고 서로 다른 두 신호는 남아야 한다"
    wafer_sets = [frozenset(g.lead.target_wafers) for g in groups]
    assert wafer_sets[0] != wafer_sets[1]
    assert set(map(frozenset, wafer_sets)) == {
        frozenset(MULTI_TRUTH_CH_WAFERS), frozenset(MULTI_TRUTH_PPID_WAFERS)}


def test_both_axes_survive_the_gate_and_reach_the_report():
    """**고친 동작.** 근거가 둘이면 둘 다 상태와 리포트에 남는다.

    예전 계약은 도구 안 최고 점수 하나만 승인해서, 축이 여럿일 때 LLM 이 고르지
    않은 축의 근거가 여기서 사라졌다. 이 테스트가 그 유실을 막는다.
    """
    from dataclasses import asdict

    from graph import evidence, nodes

    bundle = _bundle()
    groups = bundle.ranked_groups()
    lead_claim = groups[0].lead

    update = {}
    verdict = nodes._finalize_gate(
        {"claim_id": lead_claim.claim_id, "hypothesis": "다축", "confidence": 0.9},
        loop=3, update=update,
        findings=[{"loop": 1, "tool": f"hyp_{spec['id']}", "args": {},
                   "result": engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS),
                   "thought": ""}
                  for spec in registry.load_hypotheses()])

    assert update["finalize_status"] == "confirmed"
    assert "승인" in verdict
    claims = update["final_claims"]
    assert len(claims) == 2, "두 축의 근거가 모두 실려야 한다"
    assert sum(1 for c in claims if c["picked_by_llm"]) == 1

    report = nodes.report_node({
        "target_wafers": MULTI_TARGETS, "target_source": "manual",
        "target_group": MULTI_TARGETS, "status_summary": "요약", "findings": [],
        "final_hypothesis": "다축", "final_confidence": 0.9,
        "finalize_status": "confirmed", "final_claims": claims,
    })["report"]

    assert "[근거 1]" in report and "[근거 2]" in report
    # 두 축의 이름이 모두 리포트에 남는다
    assert f"{MULTI_TRUTH_EQP}_{MULTI_TRUTH_CH}" in report
    assert MULTI_TRUTH_PPID in report
    # 교락은 "같은 사실" 로 명시된다 - 근거를 둘로 세지 않는다
    assert "교락" in report and "구분되지 않는다" in report


def test_every_tied_group_is_accepted_not_just_the_first():
    """동점 1등이 여럿이면 **그중 무엇을 지목해도** 승인돼야 한다.

    처음에는 `groups[0].lead` 만 넣어 시험해서 통과했는데, 게이트가 우열 비교에
    표시 순서용 claim_id 까지 넣고 있어 **두 번째 동점 묶음은 반려**됐다. 리포트는
    "등수 1, 동점" 이라 하면서 게이트는 "더 앞선 근거가 있다" 고 반려하는, 서로
    모순되는 상태였다. LLM 은 문자열 정렬 순서를 알 길이 없으니 반려를 받아도
    고칠 수가 없고 루프 한계까지 왕복하다 inconclusive 로 끝난다.

    그래서 하나가 아니라 **동점 전부**를 넣어 본다.
    """
    from graph import evidence, nodes

    findings = [{"loop": 1, "tool": f"hyp_{spec['id']}", "args": {},
                 "result": engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS),
                 "thought": ""}
                for spec in registry.load_hypotheses()]
    groups = evidence.build_bundle(findings).ranked_groups()
    dicts = evidence.groups_to_dicts(groups)

    tied = [g for g, d in zip(groups, dicts) if d["rank"] == 1]
    assert len(tied) == 2, "이 fixture 는 1등이 둘이어야 한다"

    for group in tied:
        update = {}
        nodes._finalize_gate(
            {"claim_id": group.lead.claim_id, "hypothesis": "h", "confidence": 0.9},
            loop=3, update=update, findings=findings)
        assert update.get("finalize_status") == "confirmed", (
            f"{group.lead.claim_id} 를 지목했더니 반려됐다 - 등수가 같은데 반려하면 "
            f"LLM 이 고칠 방법이 없다")
        assert len(update["final_claims"]) == 2


def test_rank_key_carries_no_display_tiebreak():
    """우열을 묻는 값에 표시 순서용 tie-break 가 섞이면 안 된다.

    이 둘을 한 튜플로 겸하게 두어 위 결함이 생겼다. 등수를 계산하는 쪽과 게이트가
    같은 값을 봐야 "동점이라 보고하고 반려" 같은 모순이 안 생긴다.
    """
    from graph import evidence

    groups = evidence.build_bundle([
        {"loop": 1, "tool": f"hyp_{spec['id']}", "args": {},
         "result": engine.evaluate(spec, MULTI_TARGETS, MULTI_CONTROLS), "thought": ""}
        for spec in registry.load_hypotheses()]).ranked_groups()

    assert groups[0].rank_key == groups[1].rank_key      # 우열은 같다
    assert groups[0].sort_key != groups[1].sort_key      # 표시 순서만 다르다
    assert len(groups[0].rank_key) == 2                  # (p, -score) 뿐이다


def test_ranking_is_deterministic_when_the_evidence_ties():
    """동점이어도 순서가 흔들리지 않는다 - 리포트가 실행마다 바뀌면 안 된다.

    이 lot 은 두 근거의 p 도 점수도 같다. 우열을 못 가리는 것이 사실이지만,
    그 사실을 **매번 같은 순서로** 보여야 사람이 리포트를 비교할 수 있다.
    """
    orders = [tuple(g.lead.claim_id for g in _bundle().ranked_groups())
              for _ in range(3)]
    assert len(set(orders)) == 1

    groups = _bundle().ranked_groups()
    assert groups[0].rank_key == groups[1].rank_key   # p·점수가 동점이다
