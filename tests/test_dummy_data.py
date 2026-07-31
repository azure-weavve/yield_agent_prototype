"""더미 데이터 검증 — step_history·sensor_log·yield 가 데모 성립 조건을 만족하는지.

데모 성립 조건: 심어둔 챔버(ETCH9_B)는 불량 그룹 wafer 에만 있고, 대조군은 같은
설비(ETCH9)를 쓰되 챔버가 다르다 → 설비 롤업은 눌리고 챔버에서만 갈린다.
"""

import re
import sqlite3

import config
from data.generate_dummy import CONTROL_WAFERS, ETCH_SEQ, GROUP_WAFERS


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
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
            assert by_id[wid]["yield"] < config.YIELD_THRESHOLD
        for wid in ("W2406_01", "W2406_03", "W2406_05"):
            assert by_id[wid]["yield"] >= config.YIELD_THRESHOLD
        # lot 평균이 임계 미만이어야 시나리오 1(find_low_yield_lots)에 잡힌다
        avg = sum(r["yield"] for r in rows) / len(rows)
        assert avg < config.YIELD_THRESHOLD


def test_hole_case_ungrouped_low_yield_lot():
    """구멍 (나): LOT2407 은 평균이 임계 미만인 2번째 저수율 lot 인데,
    라벨이 없어 defect 패턴으로는 그룹을 못 묶는다 (출구 B 무대)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT yield FROM yield WHERE lot_id = 'LOT2407'"
        ).fetchall()
        assert len(rows) == 3
        avg = sum(r["yield"] for r in rows) / len(rows)
        assert avg < config.YIELD_THRESHOLD


def test_yield_has_root_lot_and_lot_type():
    import sqlite3, config
    conn = sqlite3.connect(config.DB_PATH); conn.row_factory = sqlite3.Row
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
    from data.generate_dummy import ADV_MISSING_WAFER, SH_STEPS

    with _conn() as conn:
        counts = {r["wafer_id"]: r["n"] for r in conn.execute(
            "SELECT wafer_id, COUNT(*) AS n FROM step_history GROUP BY wafer_id")}
        all_wafers = {r["wafer_id"] for r in conn.execute("SELECT wafer_id FROM yield")}

    assert all_wafers - set(counts) == {ADV_MISSING_WAFER}   # 결측은 심어둔 1장뿐
    assert set(counts.values()) == {len(SH_STEPS)}           # 나머지는 전 스텝 보유


def test_step_seq_is_a_sequence_code_and_area_holds_the_process_name():
    """`step_seq` 는 공정명이 아니라 사내 순번 코드다 — 문자 2자리 + 숫자 6자리.

    더미가 `"Etch"` 같은 이름을 그 컬럼에 담던 시절로 되돌아가면 여기서 잡힌다.
    이름이 담긴 더미로는 리포트가 실데이터와 다르게 읽혀, 데모는 초록인데 사내에서만
    읽히지 않는 상태가 된다. 공정명은 `area` 에 있고 스텝 하나에 하나씩 대응한다.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT step_seq, area FROM step_history").fetchall()

    assert rows
    assert all(re.fullmatch(r"[A-Z]{2}\d{6}", r["step_seq"]) for r in rows)
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
    import config
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
