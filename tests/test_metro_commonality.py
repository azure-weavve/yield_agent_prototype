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
    """동점은 가를 수 없다 — 같은 값 덩어리를 통째로 소비한 뒤에만 평가한다.

    **split 값만 보면 이 명제를 못 잡는다.** split 은 언제나 데이터에 있는 값에서
    나오므로(`v` 또는 `rows[i][0]`) "split in {45,46,47}" 같은 단언은 원리적으로
    실패할 수 없다 — 덩어리 한가운데서 잘라 카운트가 틀려도 초록이다 (2026-08-12
    리뷰가 버그 버전으로 실증). 그래서 **선택된 조각의 a·c 가 덩어리 경계와 맞는지**를
    본다.

      값     47 47 | 46 46 46 46 | 45 45 45 c45      nt = 5, nc = 5
      라벨    c  c  | T  T  c  c  | T  T  T  c

      경계는 두 곳뿐이다 (맨 아래 컷은 여집합이 비어 평가에서 빠진다).
        47 뒤 -> 위 조각 (a,c) = (0,2),  아래 조각 (5,3)
        46 뒤 -> 위 조각 (a,c) = (2,4),  아래 조각 (3,1)
    """
    best = _sweep_case("c47 c47 T46 T46 c46 c46 T45 T45 T45 c45")
    # 덩어리 경계에서만 잘랐다면 (a, c) 는 이 값들 중 하나일 수밖에 없다.
    # 덩어리 중간에서 자르면 (1,2)·(2,5) 처럼 목록에 없는 값이 나온다.
    legal_ge = {(0, 2), (2, 4)}
    legal_le = {(5, 3), (3, 1)}          # 여집합 = (nt-a, nc-c)
    assert best, "후보가 하나도 안 나왔다"
    for direction, (_s, split, a, c) in best.items():
        assert split in {45.0, 46.0, 47.0}
        legal = legal_ge if direction == "ge" else legal_le
        assert (a, c) in legal, f"{direction} 조각 (a={a}, c={c}) 이 덩어리 경계가 아니다"


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


def test_sweep_picks_the_best_cut_not_just_any_cut():
    """방향당 후보 하나이고, 그 하나는 **최댓값**이어야 한다.

    "방향이 ge/le 둘뿐이고 4-튜플이다" 같은 단언은 자료구조상 보장돼 실패할 방법이
    없다 (2026-08-12 리뷰 지적). 실제 명제는 **여러 컷 중 최고를 골랐는가** 이므로,
    가능한 모든 컷을 손으로 세어 최댓값과 대조한다. 아무 컷이나 집는 구현(예: 첫 컷,
    마지막 컷)은 여기서 걸린다.

    **입력을 고를 때 "첫 컷 == 최댓값" 이 되면 안 된다.** 처음 쓴 입력이 그랬고,
    "최댓값 대신 첫 컷을 집는" 변이가 통과해 버렸다. 여기서는 위쪽에 대조군을 한 장
    끼워 첫 자격 컷(ge 0.25)과 최댓값(ge 0.75)을 갈라 놓는다. le 도 마찬가지로
    첫 컷 -0.25 vs 최댓값 0.0 이다.
    """
    spec = "T99 c98 T97 T96 T95 c94 c93 c92"
    best = _sweep_case(spec)

    toks = spec.split()
    nt = sum(1 for t in toks if t[0] == "T")
    nc = len(toks) - nt
    scores = []
    a = c = 0
    for i, tok in enumerate(toks[:-1]):        # 맨 아래 컷은 분리가 아니다
        if tok[0] == "T":
            a += 1
        else:
            c += 1
        scores.append((a / nt - c / nc, a, c))

    ge_best = max(s for s, a, _c in scores if a >= mc.MIN_TARGET)
    le_best = max(-s for s, a, _c in scores if nt - a >= mc.MIN_TARGET)
    assert abs(best["ge"][0] - ge_best) < 1e-9
    assert abs(best["le"][0] - le_best) < 1e-9


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


def test_unknown_subitem_tokens_are_surfaced_and_normal_ones_are_not():
    """모르는 토큰만 드러낸다 — 정상 포인트는 목록에 안 들어간다.

    "통계 토큰이 아니면 전부 미상" 으로 두면 이 목록이 **정상 포인트 전체**가 되고
    (실데이터면 수천 개), 그 안에 새 통계 토큰이 한 줄 섞여도 아무도 못 본다.
    목적이 정확히 무력화되므로 포인트 이름 규칙(`_POINT_ID`)으로도 함께 판정한다.
    """
    targets, controls = _metro_groups()
    _c, _a, _s, unknown, _m, _b = _prepare(targets, controls)
    assert unknown == set(), f"더미에는 미상 토큰이 없어야 하는데 {sorted(unknown)}"


def test_a_new_statistic_token_shows_up_as_unknown():
    """변별력 — 사내에 없던 토큰이 들어오면 실제로 드러나는가.

    위 테스트만 있으면 `unknown` 을 항상 빈 집합으로 만드는 구현도 통과한다.
    통계값인 척하는 새 토큰(AVG2)과 형식이 다른 포인트(POINT_1) 둘 다 잡혀야 한다.
    """
    targets, controls = _metro_groups()
    bits = {w: 1 << i for i, w in enumerate(targets + controls)}
    rows = [{"wafer_id": targets[0], "step_seq": "CC001500", "item": "THK",
             "subitem_id": tok, "value": 1.0}
            for tok in ("AVG", "P01", "AVG2", "POINT_1")]
    _c, _a, _s, unknown = mc._build_metro_index(rows, bits, mc.METRO_LEGEND)
    assert unknown == {"AVG2", "POINT_1"}


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


# ---------------------------------------------------------------- 순열검정 (설계 §9)

def _observed(masks, combos, answer, seen):
    agg, _ = mc._aggregate_metro(masks, combos, answer, seen)
    return {k: v["score"] for k, v in agg.items()}


def test_stratified_shuffle_rejects_a_pure_lot_effect():
    """lot 으로만 갈리는 값은 기각된다 — 가장 중요한 성질.

    두 lot 의 값 범위가 안 겹치므로, root_lot 안에서 섞으면 어느 라벨을 뽑아도
    "위쪽 lot 에 타깃이 몰린다" 가 그대로 남는다 -> 귀무가 항상 관측만큼 좋다 -> p = 1.
    """
    from data.generate_dummy import METRO_LOT_EFFECT

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    obs = _observed(masks, combos, answer, seen)
    perm = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                       1000, mc.PERM_SEED)

    key = ("metro", METRO_LOT_EFFECT[0], METRO_LOT_EFFECT[1], "ge")
    assert obs[key] > 0.5                    # 점수만 보면 꽤 높은 후보다
    assert perm["p"][key] == 1.0             # 그런데 우연으로 전부 설명된다


def test_unstratified_shuffle_makes_that_lot_effect_look_like_a_finding():
    """변별력 — 층화를 빼면 같은 조합의 p 가 급락한다.

    이걸 안 보면 위 테스트가 "층화 덕분"인지 "그 조합이 원래 안 나오는 것"인지
    구분되지 않는다. stratum 을 하나로 합치면 = 전체 섞기다 (설계 §2-2 의 반례).

    절대값으로 "유의해진다" 까지 주장하지는 않는다 — 더미가 17장이라 전체 섞기에서도
    0.09 언저리다. **층화 하나가 p 를 1.0 에서 그 값으로 10배 넘게 끌어내린다**는
    대비가 이 테스트의 내용이고, 실데이터처럼 표본이 커지면 그 격차가 벌어진다.
    """
    from data.generate_dummy import METRO_LOT_EFFECT

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    obs = _observed(masks, combos, answer, seen)

    merged_t = merged_c = 0
    for _rl, t, c in masks:
        merged_t |= t
        merged_c |= c
    merged = [("ALL", merged_t, merged_c)]
    strat = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                        1000, mc.PERM_SEED)
    flat = mc._permutation_stats_metro(merged, combos, answer, seen, obs,
                                       1000, mc.PERM_SEED)

    key = ("metro", METRO_LOT_EFFECT[0], METRO_LOT_EFFECT[1], "ge")
    assert strat["p"][key] == 1.0                  # 층화: 우연으로 전부 설명된다
    assert flat["p"][key] < strat["p"][key] / 10   # 전체 섞기: 발견처럼 보인다


def test_planted_signals_survive_the_permutation_test():
    """심어둔 진짜 신호 둘은 살아남는다 — 검정이 전부를 기각하지는 않는다."""
    from data.generate_dummy import METRO_TRUE_GE, METRO_TRUE_LE

    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    obs = _observed(masks, combos, answer, seen)
    perm = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                       1000, mc.PERM_SEED)

    for step_item, direction in ((METRO_TRUE_GE, "ge"), (METRO_TRUE_LE, "le")):
        key = ("metro", step_item[0], step_item[1], direction)
        assert perm["p"][key] < 0.05
        assert perm["p"][key] > perm["p_min_possible"]   # 바닥에 닿진 않았다


def test_permutation_reports_its_own_floor_and_space():
    """소표본에서 p 가 어디까지 내려갈 수 있는지 함께 싣는다.

    층화 경우의 수 C(7,4) x C(10,1) = 350 이라 전수 열거 경로를 탄다. 관측 라벨을
    빼므로 349 회를 돌고 바닥은 1/350 이다. 이 수가 없으면 작은 p 가 "강한 신호"
    인지 "이 표본의 바닥" 인지 구분되지 않는다.
    """
    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    obs = _observed(masks, combos, answer, seen)
    perm = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                       1000, mc.PERM_SEED)

    assert perm["n_permutations_total"] == 350        # C(7,4) x C(10,1)
    assert perm["n_used"] == 349                      # 관측 라벨은 뺀다
    assert perm["p_min_possible"] == 1 / 350


def test_every_round_scores_all_combinations_with_one_label_set():
    """한 회차 = 라벨 한 번 섞기 -> **전 조합 계산**.

    조합마다 따로 섞으면 조합 간 상관이 깨져, 상관 때문에 가짜가 무더기로 나오는
    현상이 기준선에 반영되지 않는다 (설계 §2-5). 회차 수만큼만 집계가 불리는지,
    그리고 매 호출이 조합 전체를 보는지 센다.
    """
    targets, controls = _metro_groups()
    combos, answer, seen, _u, masks, _b = _prepare(targets, controls)
    obs = _observed(masks, combos, answer, seen)

    calls = []
    real = mc._aggregate_metro

    def _spy(label_masks, cb, an, sn):
        calls.append(len(cb))
        return real(label_masks, cb, an, sn)

    mc._aggregate_metro = _spy
    try:
        perm = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                           1000, mc.PERM_SEED)
    finally:
        mc._aggregate_metro = real

    assert len(calls) == perm["n_used"]               # 회차당 정확히 한 번
    assert set(calls) == {len(combos)}                # 매번 조합 전체를 본다


def test_permutation_p_is_carried_all_the_way_into_the_public_result():
    """2단계에서 잘려 나갔던 자리 — 계산한 통계가 결과 dict 까지 실제로 온다.

    p_min_possible·fdr_table·p_family_wise 계열이 계산은 되는데 소비자에게 안
    가던 사고가 있었다. metro 는 처음부터 그 자리를 잠근다.
    """
    targets, controls = _metro_groups()
    res = mc.find_metro_commonality(targets, controls)

    assert res["status"] == "ok"
    assert res["fdr_table"] and res["p_family_wise"] is not None
    assert res["p_family_wise_min_possible"] is not None
    for c in res["candidates"]:
        for field in ("p_permutation", "p_min_possible", "n_permutations_total",
                      "split_value", "split_direction", "item"):
            assert field in c, field


def test_turning_permutations_off_removes_the_p_explanation_from_the_note():
    """순열을 껐으면 p 를 설명하지 않는다 — 없는 필드를 읽으라고 하면 LLM 이 지어낸다."""
    targets, controls = _metro_groups()
    res = mc.find_metro_commonality(targets, controls, n_permutations=0)

    assert res["candidates"]
    assert "p_permutation" not in res["candidates"][0]
    assert "p_min_possible" not in res["note"]


# ---------------------------------------------------------------- 배선 (엔진·레지스트리)

def _metro_spec():
    from domain import registry
    return next(s for s in registry.load_hypotheses() if s["id"] == "metro_commonality")


def test_engine_routes_the_metro_hypothesis_to_the_metro_tool():
    """가설의 `tool` 필드가 실행 함수를 고른다 — legend 컬럼이 step_history 에 없으므로
    잘못 라우팅되면 ValueError 로 죽는다 (조용히 틀리지는 않는다)."""
    from domain import engine

    targets, controls = _metro_groups()
    res = engine.evaluate(_metro_spec(), targets, controls)
    assert res["status"] == "ok" and res["candidates"]


def test_metro_only_fields_reach_the_gate_contract():
    """split_value·split_direction·item 이 LLM 이 읽는 자리까지 온다.

    없으면 LLM 이 key 문자열("THK >= 129.0")을 다시 파싱해야 하고, 그러다 방향을
    뒤집거나 숫자를 놓친다. 2단계에서 계산만 하고 안 실어 보내 터졌던 자리와 같다.
    """
    from domain import engine

    targets, controls = _metro_groups()
    res = engine.evaluate(_metro_spec(), targets, controls)
    for c in res["candidates"]:
        assert c["item"] and c["split_direction"] in ("ge", "le")
        assert isinstance(c["split_value"], (int, float))


def test_gate_still_passes_a_candidate_that_permutation_fully_explains():
    """**게이트는 p 를 판정에 쓰지 않는다** — 지금 계약을 그대로 못 박는다.

    lot 효과 조합은 score 0.55 로 판별선을 넘지만 p_permutation 은 1.0 이다(층화
    섞기가 우연으로 전부 설명한다). 그래도 passes 는 True 다 — 자동 차단은 실데이터를
    본 뒤에 위에 얹기로 했고, 지금은 LLM 이 p 를 읽어 판단한다(hypotheses.yaml 이
    그렇게 지시한다).

    이 테스트는 "옳다" 가 아니라 "지금 이렇다" 를 적는다. 게이트에 p 를 물리는 날
    여기가 빨간불이 되어 **의도한 변경인지** 되묻게 된다.

    ⚠️ metro 에서는 이 계약의 위험이 다른 축보다 크다. 신호가 전혀 없는 데이터에
    판별선(score 0.5)을 걸어 본 실측에서 **계측 표본이 작으면 후보의 48.7%가 그 선을
    넘었다**(전수 계측이면 0%). 분할점을 최대화해서 고르는 데다 커버리지가 거칠게
    양자화되기 때문이다. metro 는 별도 도구라 게이트가 metro 안에서만 최고 점수를
    비교하므로, **순수 잡음이 1등이 되어 승인될 수 있다.** 지금 이것을 막는 것은
    `hypotheses.yaml` 이 LLM 에게 fdr_table 을 함께 읽으라고 지시하는 것뿐이다.
    """
    from data.generate_dummy import METRO_LOT_EFFECT
    from domain import engine

    targets, controls = _metro_groups()
    res = engine.evaluate(_metro_spec(), targets, controls)
    lot_effect = [c for c in res["candidates"]
                  if c["step_seq"] == METRO_LOT_EFFECT[0]
                  and c["item"] == METRO_LOT_EFFECT[1]
                  and c["split_direction"] == "ge"]
    assert len(lot_effect) == 1
    assert lot_effect[0]["p_permutation"] == 1.0     # 우연으로 전부 설명된다
    assert lot_effect[0]["passes"] is True           # 그래도 판별선은 넘는다
    assert lot_effect[0]["score"] > 0.5


def test_registry_rejects_an_unknown_tool_at_load_time():
    """모르는 `tool` 은 로드에서 잡는다 — 안 잡으면 실행 시점 KeyError 로 터진다."""
    import pytest
    import yaml
    from domain import registry

    spec = dict(_metro_spec(), tool="metrology")     # 오타
    path = ya_config.DB_PATH.parent / "_bad_hyp.yaml"
    path.write_text(yaml.safe_dump([spec], allow_unicode=True), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="모르는 tool"):
            registry.load_hypotheses(path)
    finally:
        path.unlink()


def test_registry_rejects_a_malformed_where_clause():
    """`where` 형태가 틀리면 로드에서 막는다.

    조용히 안 걸러지면 한 wafer 가 조합에 여러 값을 주는 상태가 되고, 그건 색인이
    ValueError 로 잡지만 **legend 를 고친 사람이 아니라 실행자가** 만난다.
    """
    import pytest
    import yaml
    from domain import registry

    spec = _metro_spec()
    broken = dict(spec, legend=[dict(spec["legend"][0], where=[])])
    path = ya_config.DB_PATH.parent / "_bad_where.yaml"
    path.write_text(yaml.safe_dump([broken], allow_unicode=True), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="where"):
            registry.load_hypotheses(path)
    finally:
        path.unlink()


# ------------------------------------------------- 보정 (설계 §9 "가장 중요" 항목)

def _synthetic(n_lots, per_lot, targets_per_lot, n_combos, measured_per_lot, seed):
    """신호가 **하나도 없는** 합성 색인. 값이 라벨과 완전히 무관하다.

    더미 DB 를 안 쓰는 이유: 계측 샘플링(lot 당 몇 장)을 wafer 수를 키워 가며 걸어야
    하는데, 17장짜리 더미로는 그 조건을 만들 수 없다.
    """
    import random

    rng = random.Random(seed)
    bits, strata, i = {}, [], 0
    for lot in range(n_lots):
        t = c = 0
        ws = []
        for k in range(per_lot):
            w = f"L{lot}_{k}"
            bits[w] = 1 << i
            i += 1
            ws.append(w)
            if k < targets_per_lot:
                t |= bits[w]
            else:
                c |= bits[w]
        strata.append((f"L{lot}", t, c, ws))

    combos, answer, seen = {}, {}, 0
    for ci in range(n_combos):
        key = ("metro", f"S{ci:04d}", "THK")
        rows, mask = [], 0
        for _rl, _t, _c, ws in strata:
            # **스텝마다 다른 wafer 를 잰다** (사내 확인 2026-08-12: 계측 슬롯이
            # 스텝마다 같을 수도 다를 수도 있고, 다른 쪽이 이 도구에 유리하다)
            for w in rng.sample(ws, measured_per_lot):
                rows.append((rng.random(), bits[w]))   # 라벨과 무관한 값
                mask |= bits[w]
        rows.sort(key=lambda vb: -vb[0])
        combos[key], answer[key] = rows, mask
        seen |= mask
    return combos, answer, seen, [(rl, t, c) for rl, t, c, _ws in strata]


def test_no_signal_data_does_not_produce_a_flood_of_small_p():
    """신호가 없으면 p 가 작게 나오면 안 된다 — 설계 §9 가 "가장 중요" 로 꼽은 항목.

    분할점 탐색은 조합마다 여러 자리를 시도해 최고를 고른다. 그 이득이 귀무에
    반영되지 않으면 무신호 데이터에서 작은 p 가 쏟아진다. 귀무도 같은 탐색을 거치는
    구조(`_permutation_stats_metro`)가 실제로 그걸 막는지 여기서 잰다.

    **계측 샘플링이 걸린 조건에서 재는 것이 요점이다.** 스텝마다 계측 wafer 가
    달라지면 조합마다 분모 집합이 달라지는데, 그 상태에서도 보정이 유지되는지는
    심어둔 신호를 잡는 것과 별개 문제다.

    **전수 계측과 나란히 잰다.** 샘플링 조건 하나만 보면 상한을 아무리 잡아도
    "지금 값이 옳은지" 를 못 말한다. 전수 계측은 명목대로 나오는 것이 확인돼 있으므로
    (모듈 docstring 참조) 두 조건의 **차이**가 곧 열린 결함의 크기다.

    ⚠️ 이 테스트는 **결함이 있는 상태를 고정한다.** 샘플링 조건의 p 는 명목보다 약
    2배 작게 나오고, 원인은 귀무 회차에서 후보 키가 정의되지 않는 것을 "안 넘었다" 로
    세는 것이다(모듈 docstring "열린 결함" 절). 여기 상한 15% 는 그 편향을 잡지
    **못하고**, 잡는 것은 아래 `_ratio` 대비다. 결함을 고치면 그 대비가 1.0 에
    가까워지면서 이 테스트가 빨간불이 되어 **개선을 확인해 준다.**
    """
    def _small_p_rate(measured_per_lot):
        combos, answer, seen, masks = _synthetic(
            n_lots=4, per_lot=25, targets_per_lot=5, n_combos=60,
            measured_per_lot=measured_per_lot, seed=11)
        agg, _rep = mc._aggregate_metro(masks, combos, answer, seen)
        obs = {k: v["score"] for k, v in agg.items()}
        perm = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                           1000, mc.PERM_SEED)
        ps = list(perm["p"].values())
        assert len(ps) > 20, "후보가 너무 적어 분포를 못 본다"
        return sum(1 for p in ps if p <= 0.10) / len(ps)

    full = _small_p_rate(25)              # 전수 계측
    sampled = _small_p_rate(3)            # lot 당 3장

    # 탐색 이득이 귀무에 아예 안 잡히면 이 값이 50% 를 훌쩍 넘는다 — 그건 다른 사고다
    assert sampled < 0.35, f"무신호 데이터인데 p<=0.10 이 {sampled:.1%} — 탐색 이득이 귀무에 안 잡힌다"
    # 전수 계측은 명목(10%)대로다. 이쪽이 무너지면 스윕·순열 자체가 틀린 것이다
    assert full < 0.15, f"전수 계측인데 p<=0.10 이 {full:.1%}"
    # 알려진 편향의 크기. 고치면 1.0 에 가까워지고 이 단언이 빨간불이 된다
    assert sampled / full > 1.5, (
        f"샘플링/전수 비 {sampled / full:.2f} — 편향이 줄었다면 좋은 일이니 "
        f"모듈 docstring 의 '열린 결함' 절과 함께 이 단언을 갱신하라")


def test_sampling_raises_the_p_floor_even_when_the_split_is_perfect():
    """계측이 적으면 완전 분리여도 p 가 어느 아래로는 안 내려간다.

    파워를 정하는 것은 계측된 타깃 **장수**가 아니라 **타깃이 계측된 stratum 수 k** 다
    — 층화 순열의 경우의 수가 stratum 별 조합 수의 **곱**이라 lot 당 3장이면 대략
    `3^k` 이고 바닥이 `1/3^k` 다. 이 성질을 모르면 "score 1.0 인데 왜 p 가 0.1 이냐" 를
    데이터 문제로 오해한다.

    여기서는 **고정 슬롯**(스텝마다 같은 wafer)을 강제해 k 를 작게 만든다. 사내는
    스텝마다 다를 수도 있어 실제로는 이보다 낫지만, 나쁜 쪽 끝을 잠가 둔다.
    """
    import random

    rng = random.Random(7)
    # lot 2개, 각 lot 에서 3장만 계측하고 그 3장 중 1장이 타깃 — k = 2 -> 공간 3^2 = 9
    bits, masks, combos, answer, seen = {}, [], {}, {}, 0
    rows = []
    for lot in range(2):
        t = c = 0
        for k in range(3):
            w = f"L{lot}_{k}"
            bits[w] = 1 << len(bits)
            if k == 0:
                t |= bits[w]
                rows.append((100.0 + rng.random(), bits[w]))   # 타깃이 확실히 높다
            else:
                c |= bits[w]
                rows.append((10.0 + rng.random(), bits[w]))
            seen |= bits[w]
        masks.append((f"L{lot}", t, c))
    rows.sort(key=lambda vb: -vb[0])
    key = ("metro", "S0", "THK")
    combos[key], answer[key] = rows, seen

    agg, _rep = mc._aggregate_metro(masks, combos, answer, seen)
    obs = {k: v["score"] for k, v in agg.items()}
    perm = mc._permutation_stats_metro(masks, combos, answer, seen, obs,
                                       1000, mc.PERM_SEED)

    assert agg[(*key, "ge")]["score"] == 1.0          # 완전 분리다
    assert perm["n_permutations_total"] == 9          # 3 x 3
    assert perm["p_min_possible"] == 1 / 9            # 그래도 바닥이 0.111
    assert perm["p"][(*key, "ge")] == 1 / 9           # 완전 분리가 바닥에 닿을 뿐이다


def test_a_where_clause_that_filters_everything_raises_instead_of_reporting_no_signal():
    """`where` 값 오타는 **설정 오류로 멈춘다** — 도메인 결론으로 둔갑하면 안 된다.

    `{'subitem_id': 'AVERAGE'}` 처럼 값이 틀리면 아무 행도 안 걸러지는 게 아니라
    **모든 행이 걸러진다.** 막지 않으면 결과가 status='no_signal' 로 나가고 note 는
    "lot 내부 대조로는 보이지 않는다" 는 도메인 판단을 말한다 — 오타 하나가 분석
    결론으로 LLM 에게 전달된다. 중복 행 방어의 반대쪽 극단이다.
    """
    import pytest

    targets, controls = _metro_groups()
    typo = [{"level": "metro", "columns": ["step_seq", "item"],
             "where": {"subitem_id": "AVERAGE"}}]        # AVG 오타
    with pytest.raises(ValueError, match="전부"):
        _prepare(targets, controls, typo)
