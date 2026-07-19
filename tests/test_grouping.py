"""정규화 계층 검증 — 형제 묶기(EDS)와 대조군 선정(형제 lot 합집합). 더미 DB seed 42 고정."""

from tools import grouping

CEN_SIBLINGS = ["W2410_cen1", "W2411_cen2", "W2412_cen3", "W2413_cen4"]


def test_single_input_expands_to_eds_siblings_across_lots():
    # Q1 확정: 한 장 입력 → EDS 유사맵(컷오프 0.8)으로 형제 묶기, 전 lot 탐색
    res = grouping.normalize_target(["W2406_02"])
    assert res["mode"] == "single"
    assert res["isolated"] is False
    assert set(res["target_group"]) == {"W2406_02", "W2406_04", "W2406_06", *CEN_SIBLINGS}
    assert res["target_group"][0] == "W2406_02"          # 입력 wafer 가 선두
    sims = [s["similarity"] for s in res["siblings"]]
    assert sims == sorted(sims, reverse=True)            # 유사도 내림차순
    assert all(s >= 0.8 for s in sims)
    # defect 라벨은 참고 정보로만 (판정 기준 아님 — 6절 3번)
    assert res["label_counts"][0]["defect_type"] == "center_spot"


def test_group_input_passes_through_without_grouping():
    res = grouping.normalize_target(["W2407_01", "W2407_02"])
    assert res["mode"] == "group"
    assert res["target_group"] == ["W2407_01", "W2407_02"]
    assert res["siblings"] == []


def test_single_input_with_no_siblings_is_isolated():
    # 6절 4번: 형제가 안 잡히면 isolated (자동 분석 범위 밖)
    res = grouping.normalize_target(["W2407_01"])
    assert res["isolated"] is True
    assert res["target_group"] == ["W2407_01"]


def test_unknown_wafer_is_reported():
    res = grouping.normalize_target(["W_NOPE", "W2406_02"])
    assert res["unknown_wafers"] == ["W_NOPE"]


def test_control_is_union_of_sibling_lots_with_yield_condition():
    # 7절 1단계: 형제 각자의 lot 에서 none+수율임계 wafer 합집합. 출처 명시.
    res = grouping.select_control(["W2406_02", "W2410_cen1"])   # LOT2406 + LOT2402
    assert res["stage"] == 1
    assert res["insufficient"] is False
    assert set(res["sources"]) == {"LOT2406", "LOT2402"}
    assert res["sources"]["LOT2406"] == ["W2406_01", "W2406_03", "W2406_05"]
    assert "W2406_07" not in res["control_group"]        # 88.5 < 90 — 오염원 제외 (문제 2)
    assert set(res["control_group"]) == {w for ws in res["sources"].values() for w in ws}


def test_control_excludes_target_members():
    # 대조군 후보 조건을 우연히 만족하는 target 멤버가 있어도 자기 자신과 대조하지 않는다
    res = grouping.select_control(["W2406_01", "W2406_02"])     # W2406_01 은 none·93+
    assert "W2406_01" not in res["control_group"]


def test_control_insufficient_reported_honestly():
    # 7절 3단계: 부족하면 확장하지 않고 정직 보고 (LOT2407 대조군 후보 = W2407_03 뿐)
    res = grouping.select_control(["W2407_01", "W2407_02"])
    assert res["control_group"] == ["W2407_03"]
    assert res["insufficient"] is True
