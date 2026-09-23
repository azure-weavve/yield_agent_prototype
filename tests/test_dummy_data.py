"""더미 데이터 검증 — step_history·sensor_log·yield 가 데모 성립 조건을 만족하는지.

데모 성립 조건: 심어둔 챔버(ETCH9_B)는 불량 그룹 wafer 에만 있고, 대조군은 같은
설비(ETCH9)를 쓰되 챔버가 다르다 → 설비 롤업은 눌리고 챔버에서만 갈린다.
"""

import re
import sqlite3

import ya_config
from data.generate_dummy import CONTROL_WAFERS, ETCH_SEQ, GROUP_WAFERS


def _conn():
    conn = sqlite3.connect(ya_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_recent_lot_has_group_and_control():
    """그룹 대조 시나리오: LOT2406 = 불량 그룹(짝수 = GROUP_WAFERS) + 대조 그룹(홀수, 정상)
    + 구멍 케이스 W2406_07(저수율 비타깃)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT wafer_id, yield FROM yield WHERE lot_id = 'LOT2406' ORDER BY wafer_id"
        ).fetchall()
        by_id = {r["wafer_id"]: r for r in rows}
        assert set(by_id) == {
            "W2406_01", "W2406_02", "W2406_03", "W2406_04", "W2406_05", "W2406_06",
            "W2406_07",
        }
        for wid in ("W2406_02", "W2406_04", "W2406_06"):
            assert by_id[wid]["yield"] < ya_config.YIELD_THRESHOLD
        for wid in ("W2406_01", "W2406_03", "W2406_05"):
            assert by_id[wid]["yield"] >= ya_config.YIELD_THRESHOLD
        # lot 평균이 임계 미만이어야 시나리오 1(find_low_yield_lots)에 잡힌다
        avg = sum(r["yield"] for r in rows) / len(rows)
        assert avg < ya_config.YIELD_THRESHOLD


def test_hole_case_ungrouped_low_yield_lot():
    """구멍 (나): LOT2407 은 평균이 임계 미만인 2번째 저수율 lot 인데,
    라벨이 없어 defect 패턴으로는 그룹을 못 묶는다 (출구 B 무대)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT yield FROM yield WHERE lot_id = 'LOT2407'"
        ).fetchall()
        assert len(rows) == 3
        avg = sum(r["yield"] for r in rows) / len(rows)
        assert avg < ya_config.YIELD_THRESHOLD


def test_yield_has_root_lot_and_lot_type():
    import sqlite3, ya_config
    conn = sqlite3.connect(ya_config.DB_PATH); conn.row_factory = sqlite3.Row
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(yield)")}
    assert {"root_lot_id", "lot_type"} <= cols
    # RECENT_LOT 타깃·대조군이 같은 root_lot 을 공유(commonality 층화 성립)
    rows = conn.execute(
        "SELECT DISTINCT root_lot_id FROM yield WHERE wafer_id IN "
        "('W2406_02','W2406_04','W2406_06','W2406_01','W2406_03','W2406_05')").fetchall()
    conn.close()
    assert len(rows) == 1


def test_split_lot_root_lot_spans_multiple_lots():
    """분할 lot: root_lot R2418 이 lot 3개로 갈리고, 타깃 lot 에는 비타깃이 0장이다.

    이 성질이 root_lot 기준과 lot 기준을 가른다 — lot 으로 대조군을 찾으면 0장이다.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT wafer_id, lot_id, lot_type FROM yield "
            "WHERE root_lot_id = 'R2418' ORDER BY wafer_id").fetchall()
    assert len(rows) == 8
    assert {r["lot_id"] for r in rows} == {"R2418.1", "R2418.2", "R2418.3"}
    assert [r["wafer_id"] for r in rows if r["lot_id"] == "R2418.1"] == [
        "R2418_01", "R2418_02", "R2418_03", "R2418_04"]
    # 평가랏이 섞여 있다 — 필터가 아니라 컨텍스트 (corrections B-4)
    assert {r["lot_type"] for r in rows if r["lot_id"] == "R2418.2"} == {"eval"}
    assert {r["lot_type"] for r in rows if r["lot_id"] == "R2418.3"} == {"prod"}


def test_split_lot_signal_is_target_only_chamber():
    """분할 lot 을 하나로 보면 타깃 전용 챔버가 score 1.0 으로 잡힌다."""
    from data.generate_dummy import SPLIT_CONTROLS, SPLIT_TARGETS
    from tools import commonality as cm

    res = cm.find_commonality(SPLIT_TARGETS, SPLIT_CONTROLS)
    top = res["candidates"][0]
    assert top["key"] == "ETCH5_B"
    assert top["score"] == 1.0
    # lot_type 은 배제 대상이 아니라 meta 로 실린다
    assert res["meta"]["control_lot_types"] == {"eval": 2, "prod": 2}


def test_every_wafer_has_the_full_step_path_except_the_planted_gap():
    """wafer 마다 공정 경로가 빠짐없이 있다 — 결측은 의도적으로 심은 1장뿐.

    옛 `test_process_log_table_exists_with_4_rows_per_wafer` 가 지키던 성질이다
    (테이블이 아니라 '경로 완전성'이 본체였다). step_history 로 그대로 표현된다.
    이력이 조용히 빠지면 commonality 의 분모가 줄어 점수가 부풀지만 다른 테스트는
    초록이다 — 실데이터 쪽은 load_internal.validate() 검사 #4 가 같은 것을 막는다.
    """
    from data.generate_dummy import (ADV_MISSING_WAFER, SH_STEPS, IRREG_TARGETS,
                                     METRO_STEPS, METRO_WAFERS)

    with _conn() as conn:
        counts = {r["wafer_id"]: r["n"] for r in conn.execute(
            "SELECT wafer_id, COUNT(*) AS n FROM step_history GROUP BY wafer_id")}
        all_wafers = {r["wafer_id"] for r in conn.execute("SELECT wafer_id FROM yield")}

    assert all_wafers - set(counts) == {ADV_MISSING_WAFER}   # 결측은 심어둔 1장뿐

    def _expected(w):
        # 비정규 스텝 케이스의 타깃은 정상 경로 + 1 (심어둔 초과분).
        # metro lot 은 정상 경로 + 계측 스텝 — 실데이터도 계측이 이력에 남는다.
        return (len(SH_STEPS)
                + (1 if w in IRREG_TARGETS else 0)
                + (len(METRO_STEPS) if w in METRO_WAFERS else 0))

    # wafer 별로 고정한다 — 값의 집합만 보면 초과분이 어느 wafer 에 붙든 통과한다.
    assert counts == {w: _expected(w) for w in counts}


def test_step_seq_is_a_sequence_code_and_area_holds_the_process_name():
    """`step_seq` 는 공정명이 아니라 사내 순번 코드다 — 문자 2자리 + 숫자 6자리.

    더미가 `"Etch"` 같은 이름을 그 컬럼에 담던 시절로 되돌아가면 여기서 잡힌다.
    이름이 담긴 더미로는 리포트가 실데이터와 다르게 읽혀, 데모는 초록인데 사내에서만
    읽히지 않는 상태가 된다. 공정명은 `area` 에 있고 스텝 하나에 하나씩 대응한다.

    비정규 스텝은 뒤에 `EC` 가 붙는다("CC002000EC"). 정규식을 그만큼 넓혔으므로,
    **그 케이스가 실제로 더미에 있다는 것도 함께 고정한다** — 안 그러면 넓힌 정규식이
    진짜 형식 위반을 통과시켜도 아무도 모른다.
    """
    from data.generate_dummy import IRREG_STEP

    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT step_seq, area FROM step_history").fetchall()

    assert rows
    assert all(re.fullmatch(r"[A-Z]{2}\d{6}(EC)?", r["step_seq"]) for r in rows)
    assert IRREG_STEP in {r["step_seq"] for r in rows}
    assert all(r["area"] for r in rows)                      # 공정명 결측 없음
    assert len({r["step_seq"] for r in rows}) == len(rows)   # step_seq 1개 = area 1개


def test_planted_chamber_is_exclusive_to_the_group_wafers():
    """심은 챔버(ETCH9_B)를 거친 wafer 는 더미 전체에서 GROUP_WAFERS 뿐이다.

    옛 버전은 process_log 의 스펙 이탈로 '이상은 심은 곳에만' 을 단언했다. 파라미터가
    사라졌으므로 step_history 로 표현 가능한 형태 — 챔버 배타성 — 으로 좁혔다.
    과거 패턴 wafer 에는 애초에 step_history 신호가 없다 (데모가 타깃 7장 중
    '불량군 3장 전용' 이라고 말하는 이유). 챔버 B 를 쓰는 다른 케이스는 설비가 다르다:
    적대적 lot 은 ETCH1/2/3, 분할 lot 은 ETCH5.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT wafer_id FROM step_history "
            "WHERE eqp_id = 'ETCH9' AND ch_id = 'B'"
        ).fetchall()
    assert {r["wafer_id"] for r in rows} == set(GROUP_WAFERS)


def test_control_shares_equipment_but_not_chamber():
    """대조군은 Etch 에서 같은 설비(ETCH9)를 쓰되 챔버가 다르다.

    설비 레벨 롤업이 눌리고 챔버 레벨에서만 갈리는 것이 이 시나리오의 핵심이다.
    (옛 버전은 process_log 의 equipment_id/eq_chamber 로 같은 것을 봤다.)
    """
    ph = ",".join("?" * len(CONTROL_WAFERS))
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT eqp_id, ch_id FROM step_history "
            f"WHERE step_seq = ? AND wafer_id IN ({ph})",
            [ETCH_SEQ, *CONTROL_WAFERS],
        ).fetchall()
    assert len(rows) == len(CONTROL_WAFERS)
    assert all(r["eqp_id"] == "ETCH9" for r in rows)
    assert all(r["ch_id"] != "B" for r in rows)


def test_step_history_planted_eqp_ch_and_ppid_separation():
    import ya_config
    from tools import commonality as cm
    t = ["W2406_02", "W2406_04", "W2406_06"]
    c = ["W2406_01", "W2406_03", "W2406_05"]
    res = cm.find_commonality(t, c)               # 기본 EQP_CH legend
    keys = {(x["level"], x["key"]) for x in res["candidates"]}
    assert ("chamber", "ETCH9_B") in keys
    ppid = cm.find_commonality(t, c, legend=[{"level": "ppid", "columns": ["ppid"]}])
    assert ("ppid", "PPID_X") in {(x["level"], x["key"]) for x in ppid["candidates"]}


def test_ground_truth_columns_are_null():
    """정답지 컬럼은 DB 에 값이 없다 (A-2·A-3).

    '어느 스텝이 원인인가'·'무슨 불량인가' 는 시스템이 추론할 결론이지 입력이 아니다.
    실데이터 적재기(load_internal)가 이미 NULL 을 강제하므로 더미도 같아야 한다.
    누가 더미에 라벨을 다시 채우면 이 테스트가 먼저 깨진다.
    """
    with _conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM yield "
            "WHERE defect_type IS NOT NULL OR step_seq IS NOT NULL"
        ).fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------- metro 계측 (3단계)
# 아래 테스트들은 **뒤 Task 의 테스트가 공허해지지 않게** 무대를 고정한다. 심어둔
# 분할점이나 상관 구조가 조용히 사라지면 스윕·거르기 테스트는 초록인 채로 아무것도
# 검증하지 않게 된다.

def _metro_avg(conn, step, item):
    """(스텝, item) 의 AVG 행 -> {wafer_id: 값}."""
    return {r["wafer_id"]: r["value"] for r in conn.execute(
        "SELECT wafer_id, value FROM metro "
        "WHERE step_seq = ? AND item = ? AND subitem_id = 'AVG'", (step, item))}


def test_metro_has_both_stat_tokens_and_points_with_avg_as_their_mean():
    """통계 토큰 5종과 측정 포인트가 다 있고, AVG 가 진짜 포인트들의 평균이다.

    1차는 AVG 만 쓰지만 **나머지가 실제로 존재해야** 거르기 테스트가 성립한다.
    AVG = 포인트 평균인 것은 실데이터의 성질이기도 하고, 오프셋 합이 0 이라는
    생성기 불변식을 여기서 잠근다.
    """
    from data.generate_dummy import (METRO_POINT_SUBITEMS, METRO_STAT_SUBITEMS,
                                     METRO_TRUE_GE)

    with _conn() as conn:
        subs = {r["subitem_id"] for r in conn.execute(
            "SELECT DISTINCT subitem_id FROM metro")}
        step, item = METRO_TRUE_GE
        rows = conn.execute(
            "SELECT wafer_id, subitem_id, value FROM metro "
            "WHERE step_seq = ? AND item = ?", (step, item)).fetchall()

    assert subs == set(METRO_STAT_SUBITEMS) | set(METRO_POINT_SUBITEMS)

    by_wafer: dict[str, dict[str, float]] = {}
    for r in rows:
        by_wafer.setdefault(r["wafer_id"], {})[r["subitem_id"]] = r["value"]
    assert by_wafer
    for wid, vals in by_wafer.items():
        pts = [vals[s] for s in METRO_POINT_SUBITEMS]
        assert abs(sum(pts) / len(pts) - vals["AVG"]) < 1e-6, wid


def test_metro_points_are_correlated_with_avg():
    """포인트가 AVG 주변에 있다 — 거르기를 꺼면 한 item 이 top_k 를 잠식하는 무대.

    상관이 없으면 필터를 꺼도 후보 순위가 안 흔들려 §9 의 변별력 테스트가 통과해
    버린다. 그래서 '흩어진 정도가 신호 폭보다 훨씬 작다'를 여기서 고정한다.
    """
    from data.generate_dummy import METRO_POINT_SUBITEMS, METRO_TRUE_GE

    step, item = METRO_TRUE_GE
    with _conn() as conn:
        avg = _metro_avg(conn, step, item)
        rows = conn.execute(
            "SELECT wafer_id, subitem_id, value FROM metro WHERE step_seq = ? "
            "AND item = ? AND subitem_id IN (%s)"
            % ",".join("?" * len(METRO_POINT_SUBITEMS)),
            (step, item, *METRO_POINT_SUBITEMS)).fetchall()

    spread = max(abs(r["value"] - avg[r["wafer_id"]]) for r in rows)
    signal = max(avg.values()) - min(avg.values())
    assert spread < signal / 4, f"포인트 흩어짐 {spread} 이 신호 폭 {signal} 에 비해 크다"


def test_metro_planted_ge_signal_is_actually_in_the_data():
    """심어둔 ge 분할점에서 타깃 전원 · 대조군 1장이다 (스윕과 무관하게 직접 센다).

    스윕 구현이 이 값을 재현해야 하므로, 데이터 쪽 사실을 먼저 못 박는다.
    """
    from data.generate_dummy import (METRO_TARGETS, METRO_TRUE_GE,
                                     METRO_TRUTH_GE_SPLIT)

    with _conn() as conn:
        avg = _metro_avg(conn, *METRO_TRUE_GE)

    over = {w for w, v in avg.items() if v >= METRO_TRUTH_GE_SPLIT}
    assert over & set(METRO_TARGETS) == set(METRO_TARGETS)   # 타깃 5/5
    assert len(over - set(METRO_TARGETS)) == 1               # 대조군 1장 (반례)


def test_metro_planted_le_signal_is_actually_in_the_data():
    """얇은 쪽도 같다 — 양방향을 안 돌리면 이 조합을 통째로 놓친다."""
    from data.generate_dummy import (METRO_TARGETS, METRO_TRUE_LE,
                                     METRO_TRUTH_LE_SPLIT)

    with _conn() as conn:
        avg = _metro_avg(conn, *METRO_TRUE_LE)

    under = {w for w, v in avg.items() if v <= METRO_TRUTH_LE_SPLIT}
    assert under & set(METRO_TARGETS) == set(METRO_TARGETS)
    assert len(under - set(METRO_TARGETS)) == 1


def test_metro_lot_effect_combination_splits_by_lot_not_by_defect():
    """lot 효과 조합은 root_lot 으로만 갈린다 — 불량 여부와 무관하다.

    층화 섞기가 이걸 기각하고 전체 섞기는 거짓 양성을 내는 것이 §2-2 의 변별력
    무대다. 그러려면 **두 lot 의 값 범위가 겹치지 않아야** 한다.
    """
    from data.generate_dummy import METRO_LOT_EFFECT, METRO_ROOT_LOTS

    with _conn() as conn:
        avg = _metro_avg(conn, *METRO_LOT_EFFECT)

    hi = [v for w, v in avg.items() if w.startswith(METRO_ROOT_LOTS[0])]
    lo = [v for w, v in avg.items() if w.startswith(METRO_ROOT_LOTS[1])]
    assert hi and lo
    assert min(hi) > max(lo)          # 두 lot 이 값으로 완전히 갈린다


def test_metro_tied_combination_has_only_a_few_distinct_values():
    """동점 뭉침 조합 — 분할점을 같은 값 안에 놓을 수 없다는 것을 볼 무대."""
    from data.generate_dummy import METRO_TIED

    with _conn() as conn:
        avg = _metro_avg(conn, *METRO_TIED)

    assert len(set(avg.values())) == 3
    assert len(avg) > 3               # wafer 는 여럿인데 값은 3종류뿐


def test_metro_partial_combination_measures_only_some_wafers():
    """일부만 계측된 조합 — 분모를 '계측된 wafer' 로 세는지 볼 무대.

    미계측 wafer 를 '미통과' 로 세면 대조군 분모가 6 이 아니라 12 가 되어 점수가
    부풀고 가짜 후보가 뜬다 (1단계가 고친 분모 conflation).
    """
    from data.generate_dummy import (METRO_PARTIAL, METRO_TARGETS,
                                     METRO_UNMEASURED, METRO_WAFERS)

    with _conn() as conn:
        avg = _metro_avg(conn, *METRO_PARTIAL)

    assert set(avg) == METRO_WAFERS - set(METRO_UNMEASURED)
    assert set(METRO_UNMEASURED) & set(METRO_TARGETS) == set()   # 타깃은 전원 계측됨
    assert len(avg) < len(METRO_WAFERS)


def test_metro_rows_are_unique_per_wafer_step_item_subitem():
    """metro 에는 재작업이 없다 (2026-08-12 확인) — 그래서 회차를 접는 규칙이 없다.

    그 전제가 깨지면 값 하나를 조용히 골라 쓰게 되므로 데이터 쪽에서 막는다.
    """
    with _conn() as conn:
        dup = conn.execute(
            "SELECT COUNT(*) FROM (SELECT wafer_id, step_seq, item, subitem_id "
            "FROM metro GROUP BY 1,2,3,4 HAVING COUNT(*) > 1)").fetchone()[0]
    assert dup == 0
