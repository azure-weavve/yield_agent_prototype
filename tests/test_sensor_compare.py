"""2단 센서 비교 — 효과크기 랭킹, 집계값만 반환, 재현 키."""

import ya_config
from data.generate_dummy import (CONTROL_WAFERS, GROUP_WAFERS, SENSOR_REAL,
                                 SENSOR_STEP, SENSOR_VAR_ONLY)
from tools import sensor_compare as sc


def _run():
    return sc.compare_sensor_distribution(SENSOR_STEP, GROUP_WAFERS, CONTROL_WAFERS)


def test_real_cause_sensor_ranks_first():
    res = _run()
    assert res["status"] == "ok"
    assert res["candidates"][0]["sensor_name"] == f"{SENSOR_REAL}_avg"


def test_variance_only_shift_is_a_candidate():
    """평균은 같고 분산만 이동한 센서도 후보에 오른다.

    ..._std 가 독립된 센서 이름이라 별도 처리 없이 잡힌다 — 이 설계의 핵심 이득.
    """
    names = [c["sensor_name"] for c in _run()["candidates"]]
    assert f"{SENSOR_VAR_ONLY}_std" in names
    assert f"{SENSOR_VAR_ONLY}_avg" not in names[:3]      # 평균은 안 갈린다


def test_return_is_bounded_and_carries_raw_counts():
    """반환은 top-K 로 유계이고, wafer 별 원본값을 싣지 않는다."""
    res = _run()
    assert len(res["candidates"]) <= ya_config.SENSOR_TOP_K
    c = res["candidates"][0]
    assert set(c) == {"claim_id", "passes", "reject_reason",
                      "sensor_name", "effect_size", "target_mean", "control_mean",
                      "target_std", "control_std", "n_target", "n_control"}
    assert c["n_target"] == len(GROUP_WAFERS)


def test_note_says_candidates_are_not_conclusions():
    assert "후보" in _run()["note"]


def test_refetch_key_reproduces_the_same_numbers():
    """재-fetch 키만으로 같은 집계값을 다시 만들 수 있어야 한다 (감사 추적)."""
    res = _run()
    k = res["refetch_key"]
    again = sc.compare_sensor_distribution(
        k["step_seq"], k["target_wafers"], k["control_wafers"])
    assert again["candidates"] == res["candidates"]


def test_quiet_sensors_do_not_reach_the_top():
    """어느 그룹에서도 안 갈리는 센서는 상위에 오지 않는다."""
    from data.generate_dummy import SENSOR_QUIET

    top3 = [c["sensor_name"] for c in _run()["candidates"][:3]]
    assert not any(q in name for q in SENSOR_QUIET for name in top3)


def test_two_normal_groups_do_not_separate():
    """같은 분포에서 나온 두 그룹은 큰 효과크기를 내지 않는다.

    정상 wafer 끼리 갈라 비교한다. 우연한 분리가 없지는 않으므로(센서 수백 개면
    당연하다) 상태가 아니라 **크기**를 본다 — 진짜 원인의 효과크기보다 확실히 작아야 한다.
    """
    a = ["W2401_001", "W2401_002", "W2401_003", "W2401_004"]
    b = ["W2401_006", "W2401_007", "W2401_008", "W2401_009"]
    res = sc.compare_sensor_distribution(SENSOR_STEP, a, b)
    real = _run()["candidates"][0]["effect_size"]
    if res["candidates"]:
        assert res["candidates"][0]["effect_size"] < real


def test_insufficient_sample_is_reported_not_computed():
    res = sc.compare_sensor_distribution(SENSOR_STEP, GROUP_WAFERS[:1], CONTROL_WAFERS)
    assert res["status"] == "insufficient_sample"
    assert res["candidates"] == []


def test_step_without_sensors_is_no_signal():
    """1단이 지목한 스텝에 센서 행이 없으면 '원인 없음' 이 아니라 no_signal 이다.

    더미는 Etch 에만 센서를 심는다. 조회 실패(fetch_failed)와 구분되어야 한다.
    """
    res = sc.compare_sensor_distribution("CMP", GROUP_WAFERS, CONTROL_WAFERS)
    assert res["status"] == "no_signal"
    assert res["candidates"] == []
    assert "원인 없음이 아니다" in res["note"]


def test_candidates_carry_the_gate_contract():
    """센서 후보도 claim_id 를 받는다 - 그래야 게이트가 조회하고 리포트가 인용한다.

    claim_id 에 step_seq 를 넣는 이유: 다른 스텝의 두 번째 호출이 첫 호출의 근거를
    덮어쓰면 안 된다. 두 스텝은 서로를 대체하는 재실행이 아니라 다른 질문이다.
    """
    res = _run()
    assert res["kind"] == "sensor"
    c = res["candidates"][0]
    assert c["claim_id"] == f"sensor:{SENSOR_STEP}:{c['sensor_name']}"
    assert c["passes"] is True                     # 실제 원인 센서는 효과가 크다
    assert c["reject_reason"] is None


def test_weak_effect_is_recorded_but_does_not_pass(monkeypatch):
    """판별선 미달 센서는 목록에 남되 passes=False 다 (1단 미통과 후보와 같은 취급).

    지우면 게이트가 reject_reason 을 돌려줄 수 없고, 그대로 통과시키면 d=0.05 짜리가
    리포트 [근거] 에 올라간다.
    """
    monkeypatch.setattr(ya_config, "SENSOR_PASS_MIN_EFFECT", 99.0)
    cands = _run()["candidates"]
    assert cands, "후보 자체는 여전히 나와야 한다"
    assert all(c["passes"] is False for c in cands)
    assert all("99.0" in c["reject_reason"] for c in cands)


def test_kind_is_present_even_when_nothing_separates():
    """판별자는 모든 경로에 있어야 한다 - 하나라도 빠지면 그 경로의 결과가
    build_bundle 에서 조용히 무시된다."""
    res = sc.compare_sensor_distribution(SENSOR_STEP, GROUP_WAFERS[:1], CONTROL_WAFERS)
    assert res["status"] == "insufficient_sample"
    assert res["kind"] == "sensor"
