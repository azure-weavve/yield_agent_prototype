"""process_log 더미 데이터 검증.

데모 성립 조건: 패턴 그룹 wafer 는 자기 그룹의 공정 단계에서만
'공유 이상 장비(-9) + 스펙 초과'를 갖고, 정상 wafer 는 전부 스펙 내.
"""

import sqlite3

import config
from data.generate_dummy import GROUP_WAFERS, PATTERN_GROUPS


def _conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_process_log_table_exists_with_4_rows_per_wafer():
    with _conn() as conn:
        wafers = conn.execute("SELECT COUNT(*) FROM yield").fetchone()[0]
        logs = conn.execute("SELECT COUNT(*) FROM process_log").fetchone()[0]
        assert logs == wafers * 4


def test_pattern_wafer_has_single_anomaly_at_its_step():
    with _conn() as conn:
        # 불량 그룹 wafer — 그룹 공정은 Etch
        rows = conn.execute(
            "SELECT * FROM process_log WHERE wafer_id = 'W2406_02'"
        ).fetchall()
        bad = [r for r in rows if not (r["spec_low"] <= r["param_value"] <= r["spec_high"])]
        assert len(bad) == 1
        assert bad[0]["process_step"] == "Etch"
        assert bad[0]["equipment_id"] == "ETCH-9"


def test_anomaly_equipment_is_always_the_shared_minus9():
    """스펙 이탈은 항상 그룹 공유 이상 장비(-9)에서만 난다.

    옛 버전은 defect_type='center_spot' 으로 그룹을 찾았다. 라벨이 사라졌으므로
    '이상이 있는 wafer 는 전부 -9 를 거쳤다' 로 같은 성질을 라벨 없이 단언한다.
    """
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT equipment_id FROM process_log
            WHERE NOT (spec_low <= param_value AND param_value <= spec_high)
            """
        ).fetchall()
    assert rows
    assert all(r["equipment_id"].endswith("-9") for r in rows)


def test_only_planted_pattern_wafers_have_anomalies():
    """이상을 가진 wafer 수 = 심어둔 패턴 wafer 수. 그 밖은 전부 스펙 내다."""
    expected = len(GROUP_WAFERS) + sum(g["n_past"] for g in PATTERN_GROUPS)
    with _conn() as conn:
        n = conn.execute(
            """
            SELECT COUNT(DISTINCT wafer_id) FROM process_log
            WHERE NOT (spec_low <= param_value AND param_value <= spec_high)
            """
        ).fetchone()[0]
    assert n == expected


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


def test_hole_case_unlabeled_low_yield_wafer_passed_etch9_in_spec():
    """구멍 (가): W2406_07 은 저수율인데 이상 장비 ETCH-9 를 '스펙 안으로' 통과했다.

    라벨이 전원 없어진 지금은 "라벨이 없다" 가 이 wafer 만의 특징이 아니다. 남은
    성질은 '수율은 낮은데 측정값은 스펙 내' 이고, 그것이 대조군에 섞였을 때
    suspect_equipment 를 희석한다.
    """
    with _conn() as conn:
        r = conn.execute(
            "SELECT yield FROM yield WHERE wafer_id = 'W2406_07'"
        ).fetchone()
        assert r["yield"] < config.YIELD_THRESHOLD
        etch = conn.execute(
            "SELECT * FROM process_log WHERE wafer_id = 'W2406_07' AND process_step = 'Etch'"
        ).fetchone()
        assert etch["equipment_id"] == "ETCH-9"
        assert etch["spec_low"] <= etch["param_value"] <= etch["spec_high"]


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


def test_process_log_has_eq_chamber():
    with _conn() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(process_log)")}
        assert "eq_chamber" in cols
        # 진짜 원인: 불량군 3장 전부 Etch 에서 ETCH9_B
        rows = conn.execute(
            "SELECT eq_chamber FROM process_log "
            "WHERE process_step='Etch' AND wafer_id IN ('W2406_02','W2406_04','W2406_06')"
        ).fetchall()
        assert {r["eq_chamber"] for r in rows} == {"ETCH9_B"}


def test_control_shares_equipment_not_chamber():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT equipment_id, eq_chamber FROM process_log "
            "WHERE process_step='Etch' AND wafer_id IN ('W2406_01','W2406_03','W2406_05')"
        ).fetchall()
        assert all(r["equipment_id"] == "ETCH-9" for r in rows)      # 같은 설비
        assert all(r["eq_chamber"] != "ETCH9_B" for r in rows)       # 다른 챔버


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
            "WHERE defect_type IS NOT NULL OR process_step IS NOT NULL"
        ).fetchone()[0]
    assert n == 0
