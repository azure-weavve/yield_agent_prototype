"""metro 계측 commonality — 분할점 스윕과 집계.

설계 `docs/superpowers/specs/2026-08-08-metro-commonality-design.md` §1·§9.
"""

import sqlite3

import ya_config
from tools import metro_commonality as mc


# ---------------------------------------------------------------- 스윕 (순수 함수)
# 합성 입력으로 돌린다. 더미 DB 를 거치면 실패했을 때 스윕이 틀린 것인지 데이터가
# 바뀐 것인지 갈리지 않는다.

def _sweep_case(spec: str):
    """'T131 c130 T129' -> _sweep(...) 결과.

    T = 타깃, c = 대조군. 값 내림차순으로 적는다 (스윕이 받는 순서 그대로).
    """
    rows, t_valid, c_valid, nt, nc = [], 0, 0, 0, 0
    for i, tok in enumerate(spec.split()):
        bit = 1 << i
        rows.append((float(tok[1:]), bit))
        if tok[0] == "T":
            t_valid |= bit
            nt += 1
        else:
            c_valid |= bit
            nc += 1
    return mc._sweep(rows, t_valid, c_valid, nt, nc)


def test_sweep_finds_the_planted_split_exactly_at_the_boundary_value():
    """심어둔 분할점을 경계값까지 정확히 지목한다.

    타깃 사이에 대조군 1장을 끼워 완전 분리를 막았다 — 완전 분리면 어느 분할점이든
    같은 점수라 "정확히 129.0" 이라는 주장이 성립하지 않는다.
    """
    best = _sweep_case("T131.0 T130.6 c130.2 T129.8 T129.4 T129.0 "
                       "c128.5 c128.2 c127.9 c127.6")
    score, split, a, c = best["ge"]
    assert split == 129.0                      # 심어둔 자리
    assert (a, c) == (5, 1)                    # 타깃 5/5, 대조군 1/5
    assert abs(score - (1.0 - 1 / 5)) < 1e-9


def test_sweep_never_puts_a_split_inside_a_tie():
    """동점은 가를 수 없다 — 분할점은 서로 다른 값 사이에만 놓인다.

    같은 값 덩어리를 통째로 소비한 뒤에만 평가하는지 본다. 값이 3종류뿐인 입력에서
    분할점이 그 3개 밖(예: 45.5)으로 나오면 덩어리 중간에서 잘랐다는 뜻이다.
    """
    best = _sweep_case("c47 c47 T46 T46 c46 c46 T45 T45 T45 c45")
    for score, split, _a, _c in best.values():
        assert split in {45.0, 46.0, 47.0}


def test_sweep_reports_the_thin_side_as_le_with_the_lower_pieces_top_value():
    """얇은 쪽 신호는 `le` 방향으로 나오고, split 은 아래 조각의 최댓값이다.

    "127.0 이상" 의 여집합은 "127.0 미만" 인데, 엔지니어가 읽는 형태는 "126.x 이하"
    가 아니라 아래 조각의 최댓값이다. 방향을 안 돌리면 이 신호를 통째로 놓친다.
    """
    best = _sweep_case("c130 c129 c128 c127.5 T127.0 T126.5 c126.2 T126.0 T125.5 T125.0")
    score, split, a, c = best["le"]
    assert split == 127.0
    assert (a, c) == (5, 1)
    assert abs(score - (1.0 - 1 / 5)) < 1e-9


def test_sweep_excludes_pieces_with_too_few_targets():
    """타깃이 MIN_TARGET 미만인 조각은 **탐색 범위에서** 뺀다.

    어차피 게이트를 못 지날 후보를 시도 횟수에 넣으면 귀무 기준선만 올라가 실제가
    손해를 본다. 여기서는 맨 위 타깃 1장짜리 조각(점수 1.0 - 0 = 1.0)이 최고인데도
    선택되면 안 된다 — 제외가 실제로 걸리는지 이 대비가 보여 준다.
    """
    best = _sweep_case("T99 c90 c89 T88 T87 c86")
    score, split, a, c = best["ge"]
    assert a >= mc.MIN_TARGET
    assert split != 99.0
    assert score < 1.0


def test_sweep_emits_at_most_one_candidate_per_direction():
    """한 조합은 방향당 후보를 **하나만** 낸다.

    같은 데이터를 조금 다르게 자른 것은 새 정보가 아니고, 검정이 "최고 하나" 기준에
    맞춰져 있어 둘 다 내면 계산이 어긋난다 (설계 §1).
    """
    best = _sweep_case("T99 T98 c97 T96 c95 c94 T93 c92")
    assert set(best) <= {"ge", "le"}
    for v in best.values():
        assert len(v) == 4          # (score, split, a, c) 하나씩


def test_sweep_never_cuts_at_the_very_bottom():
    """전체를 포함하는 컷은 분리가 아니다 (여집합이 빈다).

    막지 않으면 score 0 짜리 후보가 항상 하나씩 생겨 FDR 표의 분모를 오염시킨다.
    """
    best = _sweep_case("T10 T9 c8 c7")
    for _s, split, _a, _c in best.values():
        assert split != 7.0         # 마지막 값 = 전체 포함


# ---------------------------------------------------------------- 색인·집계 (더미)

def _prepare(targets, controls, legend=None):
    """더미 DB 에서 색인과 stratum 마스크를 만든다 (find_metro_commonality 의 앞부분)."""
    legend = legend or mc.METRO_LEGEND
    conn = sqlite3.connect(ya_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = mc._metro_rows(conn, targets + controls, legend)
        meta = {r["wafer_id"]: r["root_lot_id"] for r in conn.execute(
            "SELECT wafer_id, root_lot_id FROM yield WHERE wafer_id IN (%s)"
            % ",".join("?" * len(targets + controls)), targets + controls)}
    finally:
        conn.close()

    bits = {w: 1 << i for i, w in enumerate(targets + controls)}
    combos, answer, seen, unknown = mc._build_metro_index(rows, bits, legend)

    strata: dict[str, list[int]] = {}
    for w in targets:
        strata.setdefault(meta[w], [0, 0])[0] |= bits[w]
    for w in controls:
        if meta[w] in strata:
            strata[meta[w]][1] |= bits[w]
    masks = [(rl, t, c) for rl, (t, c) in sorted(strata.items()) if t and c]
    return combos, answer, seen, unknown, masks, bits


def _metro_groups():
    from data.generate_dummy import METRO_CONTROLS, METRO_TARGETS
    return list(METRO_TARGETS), list(METRO_CONTROLS)


def test_unmeasured_wafers_drop_out_of_the_denominator():
    """계측 안 된 wafer 는 '미통과' 가 아니라 **분모 밖**이다 (1단계 원칙).

    가장 중요한 성질이다. 미계측 대조군 6장을 미통과로 세면 분모가 6 이 아니라 12 가
    되어 점수가 0.33 -> 0.67 로 뛰고 가짜 후보가 게이트를 지난다.
    """
    from data.generate_dummy import METRO_PARTIAL, METRO_UNMEASURED

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    agg, _rep = mc._aggregate_metro(masks, combos, answer, seen)

    step, item = METRO_PARTIAL
    got = {k: v for k, v in agg.items() if k[1] == step and k[2] == item}
    assert got, "일부만 계측된 조합이 후보를 하나도 안 냈다"
    for v in got.values():
        assert v["nc"] == len(controls) - len(METRO_UNMEASURED)
        assert v["nt"] == len(targets)


def test_planted_ge_signal_is_found_with_the_planted_split():
    """진짜 신호 조합에서 심어둔 분할점과 점수가 그대로 나온다."""
    from data.generate_dummy import METRO_TRUE_GE, METRO_TRUTH_GE_SPLIT

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    agg, _rep = mc._aggregate_metro(masks, combos, answer, seen)

    key = ("metro", METRO_TRUE_GE[0], METRO_TRUE_GE[1], "ge")
    assert key in agg
    assert agg[key]["split"] == METRO_TRUTH_GE_SPLIT
    assert agg[key]["a"] == len(targets)            # 타깃 전원
    assert agg[key]["c"] == 1                       # 대조군 1장 (반례)


def test_planted_le_signal_is_found_in_the_other_direction():
    """얇은 쪽 신호는 `le` 로만 잡힌다 — 양방향이 실제로 일하는지 본다."""
    from data.generate_dummy import METRO_TRUE_LE, METRO_TRUTH_LE_SPLIT

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    agg, _rep = mc._aggregate_metro(masks, combos, answer, seen)

    step, item = METRO_TRUE_LE
    assert ("metro", step, item, "le") in agg
    assert agg[("metro", step, item, "le")]["split"] == METRO_TRUTH_LE_SPLIT
    # 반대 방향은 신호가 아니다 — 나오더라도 훨씬 낮아야 한다
    ge = agg.get(("metro", step, item, "ge"))
    assert ge is None or ge["score"] < agg[("metro", step, item, "le")]["score"]


def test_legend_where_clause_filters_rows_not_just_columns():
    """`where` 가 **행을 거른다** — AVG 만 후보가 되고 개별 포인트는 안 들어온다.

    기존 legend 는 columns 로 키를 만들 뿐 행을 안 걸렀다. 이것이 3단계에서 legend 에
    새로 들어가는 유일한 기능이다.
    """
    from data.generate_dummy import METRO_ITEMS, METRO_STEPS

    targets, controls = _metro_groups()
    combos, _a, _s, _u, _m, _b = _prepare(targets, controls)

    assert set(combos) == {("metro", st, it) for st in METRO_STEPS for it in METRO_ITEMS}


def test_dropping_the_where_clause_fails_loudly_instead_of_miscounting():
    """거르기가 실제로 일하는지 — 빼면 **예외로 멈춘다** (변별력).

    이걸 안 보면 필터가 있으나 마나여도 위 테스트는 초록이다.

    설계서는 안 거를 때의 피해를 "한 item 이 top_k 를 잠식한다" 로 적었는데, 후보
    키를 (스텝, item) 으로 좁힌 뒤로는 피해가 그보다 나쁘다 — subitem 이 키에 없어서
    **한 wafer 가 같은 조합에 10번 들어가고 a 가 nt 를 넘는다.** coverage 가 1.0 을
    넘는데 예외는 안 나는, 조용히 틀린 답이다. 그래서 잠식이 아니라 정지가 맞다.
    """
    import pytest

    targets, controls = _metro_groups()
    no_filter = [{"level": "metro", "columns": ["step_seq", "item"]}]
    with pytest.raises(ValueError, match="subitem_id"):
        _prepare(targets, controls, no_filter)


def test_unknown_subitem_tokens_are_surfaced_not_silently_mixed_in():
    """모르는 토큰은 드러낸다 — 조용히 포인트로 취급하면 사내에서만 터진다.

    개별 측정 포인트(P01 ...)는 통계 토큰이 아니므로 여기 잡히는 것이 정상이다.
    요점은 **목록이 비어 있지 않고 실제 토큰을 담는다**는 것 — 새 통계 토큰이
    생겼을 때 그것이 포인트인 척 섞여도 이 자리에서 보인다.
    """
    from data.generate_dummy import METRO_POINT_SUBITEMS

    targets, controls = _metro_groups()
    _c, _a, _s, unknown, _m, _b = _prepare(targets, controls)

    assert unknown == set(METRO_POINT_SUBITEMS)
    assert not (unknown & mc.STAT_TOKENS)


def test_aggregate_depends_only_on_the_labels():
    """같은 색인에 라벨만 바꿔 넣으면 결과가 라벨에만 의존한다.

    순열검정이 이 성질 위에 서 있다 — 회차마다 색인을 다시 만들지 않고 마스크만
    바꿔 같은 함수를 부른다. 타깃과 대조군을 통째로 맞바꾸면 방향이 뒤집혀야 한다.
    """
    from data.generate_dummy import METRO_TRUE_GE

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    swapped = [(rl, c, t) for rl, t, c in masks]

    agg, _r = mc._aggregate_metro(masks, combos, answer, seen)
    agg_sw, _r2 = mc._aggregate_metro(swapped, combos, answer, seen)

    step, item = METRO_TRUE_GE
    assert ("metro", step, item, "ge") in agg
    assert ("metro", step, item, "le") in agg_sw     # 역할이 바뀌면 방향도 바뀐다
    assert abs(agg[("metro", step, item, "ge")]["score"]
               - agg_sw[("metro", step, item, "le")]["score"]) < 1e-9
