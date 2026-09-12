"""레지스트리 로더·도구 생성 — legend 스키마."""

import pytest
import yaml
from domain import registry

VALID = [{"id": "eqp_ch_commonality", "name": "설비/챔버 공통성",
          "description": "타깃만 거친 (스텝, 설비/챔버)를 찾는다",
          "legend": [{"level": "equipment", "columns": ["eqp_id"]},
                     {"level": "chamber", "columns": ["eqp_id", "ch_id"]}]}]


def test_load_valid_yaml(tmp_path):
    p = tmp_path / "h.yaml"
    p.write_text(yaml.safe_dump(VALID, allow_unicode=True), encoding="utf-8")
    specs = registry.load_hypotheses(p)
    assert specs[0]["id"] == "eqp_ch_commonality"
    assert specs[0]["legend"][0]["level"] == "equipment"


def test_reject_missing_field(tmp_path):
    bad = [{"id": "x", "name": "n", "description": "d"}]  # legend 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="legend"):
        registry.load_hypotheses(p)


def test_reject_malformed_legend(tmp_path):
    bad = [{"id": "x", "name": "n", "description": "d",
            "legend": [{"level": "eq"}]}]  # columns 없음
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        registry.load_hypotheses(p)


def test_reject_unknown_denominator(tmp_path):
    """denominator 오타가 조용히 무시되면 분모가 말없이 바뀐다."""
    bad = [{"id": "x", "name": "n", "description": "d",
            "legend": [{"level": "eq", "columns": ["eqp_id"],
                        "denominator": "everything"}]}]
    p = tmp_path / "h.yaml"; p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="denominator"):
        registry.load_hypotheses(p)


def test_build_tools_produces_named_callables():
    tools = registry.build_tools(VALID)
    assert tools[0].name == "hyp_eqp_ch_commonality"
    assert "설비" in tools[0].description


def test_real_yaml_loads_and_builds():
    """저장소의 실제 hypotheses.yaml 이 로드·빌드된다."""
    specs = registry.load_hypotheses()
    ids = {s["id"] for s in specs}
    assert "eqp_ch_commonality" in ids and "ppid_commonality" in ids
    assert {t.name for t in registry.build_tools(specs)} == {f"hyp_{i}" for i in ids}


def test_the_eqp_ch_description_tells_the_llm_not_to_double_count_a_roll_up():
    """설비 후보와 챔버 후보가 같은 wafer 를 가리키면 근거가 하나라는 것은 **분석 루프
    LLM 이 읽는 계약**(yaml)에도 있어야 한다.

    게이트가 접는 것과 별개로, 분석 루프는 도구 결과를 직접 보고 다음 도구를 고른다.
    거기서 둘을 별개 근거로 세면 확신도가 부풀고 종료 판단이 흔들린다. 이 저장소에서
    "통계를 고쳤는데 yaml 을 안 고쳐" 생긴 결함이 반복해서 났다.
    """
    spec = {s["id"]: s for s in registry.load_hypotheses()}["eqp_ch_commonality"]
    assert "level_columns" in spec["description"]
    assert "같은 wafer" in spec["description"]


def test_every_hypothesis_says_sensor_claims_are_not_pickable():
    """센서에 claim_id 가 실리기 시작했으므로 yaml 계약이 그 지위를 말해야 한다.

    LLM 은 도구 결과에서 claim_id 를 보면 "지목할 수 있는 것" 으로 읽는다 -
    `finalize` 계약이 "도구가 발급한 claim_id 를 그대로 옮겨라" 뿐이기 때문이다.
    말해 주지 않으면 1단이 빈손인 흔한 경로에서 센서를 지목하고 반려당한다.
    반려 문구로 가르치는 것으로는 부족하다 - 그건 이미 한 바퀴를 버린 뒤다.

    **가설 전부를 센다.** 통계 해석 문단이 4곳에 복붙돼 있어 한 곳만 고치면 나머지
    축을 돌린 대화에서만 계약이 사라지는데, 지난 순열 p 교정에서 리뷰 Important
    2건이 정확히 그 구멍이었다.
    """
    specs = registry.load_hypotheses()
    assert specs                    # 빈 목록이면 아래 루프가 공허하게 통과한다
    for spec in specs:
        d = spec["description"]
        assert "2단 센서" in d, spec["id"]
        assert "지목 대상이 아니다" in d, spec["id"]
        # 근거로는 실린다는 반쪽도 함께 적혀야 한다 - "쓸모없다" 로 읽으면 LLM 이
        # 2단을 아예 안 돌려 '왜' 가 리포트에서 사라진다. 다만 "전부 실린다" 도
        # 거짓이다(판별선을 넘은 것만 실린다). "근거" 만 세면 설명 어디에나 있어
        # 공허하므로, 규칙의 나머지 반쪽인 판별선 쪽을 단언한다.
        assert "근거" in d, spec["id"]
        assert "판별선을 넘은(passes=true)" in d, spec["id"]


def test_every_hypothesis_tells_the_llm_that_p_is_read_with_its_floor():
    """순위가 **공통 해상도**에서 매겨진다는 것도 yaml 계약에 있어야 한다 - 가설 전부에.

    분석 루프 LLM 은 게이트를 거치기 전에 도구 결과를 직접 읽고 다음 행동을 고른다.
    p 만 보고 "내 후보가 졌다" 고 판단하면, 바닥에 걸려 0.111 에서 멈춘 완전 분리
    후보를 p 0.05 짜리 약한 후보에게 내주고 스스로 버린다. 코드는 그 둘을 동점으로
    본다.

    **가설 전부를 센다.** 통계 해석 문단이 복붙돼 있어 한 곳만 고치면 나머지가
    옛 계약으로 남는데, 지난 순열 p 교정에서 리뷰 Important 2건이 정확히 그 구멍이었다.

    **점수 규칙까지 같이 잠근다.** "바닥에 걸리면 안 진다" 만 적으면 거짓이다 -
    같은 축 안에서는 공통 해상도에서 p 가 같아진 뒤 분리 점수가 우열을 가르므로
    바닥에 걸린 후보도 진다. 반쪽만 적힌 계약을 읽으면 LLM 은 실제 순위를 보고
    "계약과 다르다" 고 판단해 엉뚱한 축을 다시 돈다.
    """
    specs = registry.load_hypotheses()
    assert specs                    # 빈 목록이면 아래 루프가 공허하게 통과한다
    for spec in specs:
        d = spec["description"]
        assert "둘 다 표현할 수 있는 해상도" in d, spec["id"]
        assert "다른 축의** 더 작은 p 에게 지지 않는다" in d, spec["id"]
        assert "같은 축 안에서만" in d, spec["id"]
        assert "축이 다르면 점수는 쓰지 않는다" in d, spec["id"]
        assert "통계적 근거가 없는 것으로 취급" in d, spec["id"]


def test_every_permutation_axis_teaches_p_at_floor_not_a_comparison():
    """바닥에 닿았는지는 **도구가 센 사실**(`p_at_floor`)이다.

    yaml 이 그것을 안 가르치면 LLM 은 p 와 p_min_possible 을 직접 비교해 알아내는데,
    두 값은 4자리로 반올림돼 나가므로 참조 회차가 13,333~19,999 이거나 40,000 이상이면 1/13334 과
    2/13334 이 같은 숫자가 된다. 축이 늘 때 이 문장만 빠지는 것을 여기서 막는다.
    """
    for spec in registry.load_hypotheses():
        if "p_min_possible" in spec["description"]:
            assert "p_at_floor" in spec["description"], spec["id"]


def test_no_axis_blames_the_sample_size_for_a_big_floor():
    """바닥이 큰 이유는 "참조 회차가 적다" 이지 "표본이 작다" 가 아니다.

    두 말이 갈리는 자리가 있다 - 표본이 커도 순열 회차 예산이 작으면 바닥은
    올라간다. yaml 이 원인을 표본 탓으로 적으면 LLM 은 리포트에 "wafer 를 더
    모아야 한다" 고 쓰고, 엔지니어는 늘릴 수 없는 것을 늘리러 간다.
    """
    for spec in registry.load_hypotheses():
        assert "표본이 작아 p" not in spec["description"], spec["id"]


def test_every_permutation_axis_qualifies_the_family_wise_comparison():
    """family-wise 쌍은 **코드가 아니라 이 문장으로만** 한계를 알린다.

    후보별 p 는 `p_at_floor` 라는 사실을 동반하지만 목록 단위 값 한 쌍은 그렇지
    않기로 했다(2026-09-12 결정). 그래서 "둘이 같으면" 을 참고로만 쓰라는 한정절이
    계약의 전부다 - 축이 늘거나 한 블록만 고쳐지면 조용히 갈린다.
    """
    for spec in registry.load_hypotheses():
        if "p_family_wise_min_possible" in spec["description"]:
            assert "참고로만 써라" in spec["description"], spec["id"]
