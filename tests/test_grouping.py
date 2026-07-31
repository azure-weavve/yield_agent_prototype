"""정규화 계층 검증 — 형제 묶기(EDS)와 대조군 선정(형제 lot 합집합). 더미 DB seed 42 고정."""

from tools import eds_search, grouping

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
    assert res["unmatched_siblings"] == []               # 형제 전원 yield DB 실재


def test_group_input_passes_through_without_grouping():
    res = grouping.normalize_target(["W2407_01", "W2407_02"])
    assert res["mode"] == "group"
    assert res["target_group"] == ["W2407_01", "W2407_02"]
    assert res["siblings"] == []
    assert res["unmatched_siblings"] == []


def test_eds_siblings_absent_from_yield_db_go_to_unmatched(monkeypatch):
    # EDS 인덱스와 yield DB 는 별도 시스템 — 동기화가 어긋나면 EDS 가 DB 에 없는
    # 형제를 반환할 수 있다. 그런 형제는 분석 대상에서 빼고 unmatched_siblings 로 분리한다.
    class _Stub:
        def search(self, wafer_id, k):
            return [{"wafer_id": "W2406_04", "similarity": 0.95},
                    {"wafer_id": "W_GHOST", "similarity": 0.90}]

    monkeypatch.setattr(eds_search, "_searcher", _Stub())
    res = grouping.normalize_target(["W2406_02"])
    assert "W_GHOST" not in res["target_group"]
    assert res["unmatched_siblings"] == ["W_GHOST"]
    assert res["target_group"] == ["W2406_02", "W2406_04"]
    assert [s["wafer_id"] for s in res["siblings"]] == ["W2406_04"]


def test_single_input_with_no_siblings_is_isolated():
    # 6절 4번: 형제가 안 잡히면 isolated (자동 분석 범위 밖)
    res = grouping.normalize_target(["W2407_01"])
    assert res["isolated"] is True
    assert res["target_group"] == ["W2407_01"]


def test_unknown_wafer_is_reported():
    res = grouping.normalize_target(["W_NOPE", "W2406_02"])
    assert res["unknown_wafers"] == ["W_NOPE"]


def test_control_is_all_non_targets_in_same_root_lots():
    """대조군 = 타깃과 같은 root_lot 의 비타깃 전원. 출처는 root_lot 단위로 명시한다.

    W2406_04·W2406_06 은 center_spot 불량이지만 이 호출에서는 타깃이 아니므로
    대조군에 들어간다 — 새 규칙에는 라벨 조건이 없다.
    """
    res = grouping.select_control(["W2406_02", "W2410_cen1"])   # LOT2406 + LOT2402
    assert "stage" not in res                                   # 단계 개념 폐기
    assert res["insufficient"] is False
    assert set(res["sources"]) == {"LOT2406", "LOT2402"}
    assert res["sources"]["LOT2406"] == [
        "W2406_01", "W2406_03", "W2406_04", "W2406_05", "W2406_06", "W2406_07"]
    assert set(res["control_group"]) == {w for ws in res["sources"].values() for w in ws}


def test_control_reports_yield_distribution_instead_of_filtering():
    """저수율·무라벨 wafer 를 거르지 않고 yield_summary 로 보인다 (spec 결정 2)."""
    import config

    res = grouping.select_control(["W2406_02", "W2410_cen1"])
    assert "W2406_07" in res["control_group"]          # 88.5 — 옛 규칙에서는 제외됐다
    assert res["yield_summary"]["threshold"] == config.YIELD_THRESHOLD
    assert res["yield_summary"]["n_below_threshold"] >= 1
    assert res["yield_summary"]["median"] > 0


def test_control_spans_split_lots_of_same_root_lot():
    """타깃 lot 안에 비타깃이 0장이어도 같은 root_lot 의 다른 분할 lot 에서 찾는다."""
    from data.generate_dummy import SPLIT_CONTROLS, SPLIT_TARGETS

    res = grouping.select_control(SPLIT_TARGETS)
    assert res["control_group"] == SPLIT_CONTROLS
    assert set(res["sources"]) == {"R2418"}            # 출처는 root_lot 단위
    assert res["insufficient"] is False


def test_control_group_is_empty_when_no_yield_rows():
    res = grouping.select_control(["W_NOPE"])
    assert res["control_group"] == []
    assert res["yield_summary"] is None
    assert res["insufficient"] is True


def test_control_excludes_target_members():
    # 대조군 후보 조건을 우연히 만족하는 target 멤버가 있어도 자기 자신과 대조하지 않는다
    res = grouping.select_control(["W2406_01", "W2406_02"])     # W2406_01 은 none·93+
    assert "W2406_01" not in res["control_group"]


def test_control_insufficient_reported_honestly():
    # 7절 3단계: 부족하면 확장하지 않고 정직 보고 (LOT2407 대조군 후보 = W2407_03 뿐)
    res = grouping.select_control(["W2407_01", "W2407_02"])
    assert res["control_group"] == ["W2407_03"]
    assert res["insufficient"] is True


def test_eds_index_miss_is_reported_not_raised(monkeypatch):
    """yield DB 엔 있지만 EDS 인덱스엔 없는 wafer — 예외가 아니라 사실로 보고한다.

    LocalEDSSearcher 는 KeyError, HttpEDSSearcher 는 requests 예외를 던진다.
    정규화 계층은 흐름을 정하지 않는다(판단은 status_node).
    """
    class _Missing:
        def search(self, wafer_id, k):
            raise KeyError(wafer_id)

    monkeypatch.setattr(eds_search, "_searcher", _Missing())
    res = grouping.normalize_target(["W2406_02"])
    assert res["eds_error"] is not None
    assert "KeyError" in res["eds_error"]
    assert res["siblings"] == []
    assert res["isolated"] is False        # '형제 없음' 과 '조회 실패' 는 다르다
    assert res["target_group"] == ["W2406_02"]


def test_normal_path_reports_no_eds_error():
    res = grouping.normalize_target(["W2406_02"])
    assert res["eds_error"] is None
