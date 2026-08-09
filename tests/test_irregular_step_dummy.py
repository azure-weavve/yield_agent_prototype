"""비정규 스텝 케이스 — "그 스텝을 거쳤는가" 자체가 후보가 되는 축.

사내 step_seq 는 비정규 스텝이면 뒤에 `EC` 가 붙는다("CC002000EC"). 지나는 lot 과
안 지나는 lot 이 갈리고 거기서 문제가 생겨 조치한 이력이 있어, **통과 여부 자체가
분석 대상**이다. 설비/PPID 축은 "그 스텝 안에서 무엇을 썼는가" 만 보므로 이 신호를
구조적으로 놓친다 — 그 대비를 여기서 고정한다.
"""

from data.generate_dummy import IRREG_CONTROLS, IRREG_STEP, IRREG_TARGETS, SH_STEPS
from domain import engine, registry


def _run(hypothesis_id):
    spec = next(s for s in registry.load_hypotheses() if s["id"] == hypothesis_id)
    return engine.evaluate(spec, IRREG_TARGETS, IRREG_CONTROLS)


def test_irregular_step_is_caught_only_by_the_passage_axis():
    """설비·PPID 축은 못 잡고 스텝 통과 축만 잡는다 — 이 가설이 존재하는 이유.

    타깃 4장이 비정규 스텝을 거치고 대조군은 아무도 안 거친다. 설비·PPID 축은
    "그 스텝 안에서 무엇을 썼는가" 만 보는데 대조군에 그 스텝 자체가 없으므로
    비교가 성립하지 않는다. 통과 여부로 보면 타깃 4/4 · 대조군 0/4 로 갈린다.
    """
    # 대조군이 비정규 스텝에 아무도 안 갔으므로, 그 스텝의 설비·PPID 후보는
    # 대비할 짝이 없어 계산 단계에서 빠진다. 예전에는 1/4 짜리 후보가 12개
    # 나왔다가 판별선에서 걸렸다 (분모 교정 전 동작).
    for hid in ("eqp_ch_commonality", "ppid_commonality"):
        res = _run(hid)
        assert res["status"] == "no_signal", f"{hid} 가 후보를 내면 안 된다"
        assert res["candidates"] == []

    res = _run("step_passage_commonality")
    passing = [c for c in res["candidates"] if c["passes"]]
    assert len(passing) == 1
    c = passing[0]
    assert c["step_seq"] == IRREG_STEP
    assert c["claim_id"] == f"step_passage_commonality:step_passage:{IRREG_STEP}:{IRREG_STEP}"
    assert (c["target_pass"], c["target_total"]) == (4, 4)
    assert (c["control_pass"], c["control_total"]) == (0, 4)
    assert c["score"] == 1.0


def test_normal_steps_do_not_become_candidates_on_the_passage_axis():
    """전원이 거치는 정상 스텝은 후보 자체가 되지 않는다.

    이 축이 쓸 만한 이유의 절반이다 — 타깃·대조군 커버리지가 같으면 분리 점수가 0 이라
    commonality 가 걸러낸다. 안 걸러지면 wafer 당 스텝 수(실데이터는 ~1000)만큼 후보가
    쏟아져 top-k 가 무의미해지고, 게이트의 '같은 도구 안 최고 점수' 도 흔들린다.
    """
    res = _run("step_passage_commonality")
    steps = {c["step_seq"] for c in res["candidates"]}
    assert steps == {IRREG_STEP}
    assert not steps & {seq for seq, _ in SH_STEPS}
