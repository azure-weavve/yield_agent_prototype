"""더미 sensor_log — 심어둔 케이스 4종이 의도대로인지.

센서 값은 트레이스가 아니라 wafer 1장의 구간 통계값이고, 구간·통계 종류는
센서 이름에 들어 있다(rf_power_steady_avg). 그래서 ..._avg 와 ..._std 는
서로 독립된 센서로 취급된다 — '분산만 이동' 케이스가 별도 처리 없이 잡히는 이유다.
"""

import sqlite3
import statistics

import config
from data.generate_dummy import (GROUP_WAFERS, CONTROL_WAFERS, SENSOR_COLLINEAR,
                                 SENSOR_DECOYS, SENSOR_MISSING_WAFER, SENSOR_REAL,
                                 SENSOR_STEP, SENSOR_VAR_ONLY)


def _vals(sensor_name, wafer_ids):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        ph = ",".join("?" * len(wafer_ids))
        rows = conn.execute(
            f"SELECT value FROM sensor_log WHERE sensor_name = ? "
            f"AND step_seq = ? AND wafer_id IN ({ph})",
            [sensor_name, SENSOR_STEP, *wafer_ids]).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def test_sensor_log_table_exists_with_expected_columns():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sensor_log)")}
    finally:
        conn.close()
    assert cols == {"wafer_id", "step_seq", "sensor_name", "value", "tkout_time"}


def test_case1_variance_only_shift_keeps_mean_but_moves_std():
    """평균은 같고 분산만 이동 — avg 만 보는 사고의 사각지대."""
    t_avg = _vals(f"{SENSOR_VAR_ONLY}_avg", GROUP_WAFERS)
    c_avg = _vals(f"{SENSOR_VAR_ONLY}_avg", CONTROL_WAFERS)
    t_std = _vals(f"{SENSOR_VAR_ONLY}_std", GROUP_WAFERS)
    c_std = _vals(f"{SENSOR_VAR_ONLY}_std", CONTROL_WAFERS)
    assert abs(statistics.mean(t_avg) - statistics.mean(c_avg)) < 1.0   # 평균은 사실상 동일
    assert statistics.mean(t_std) > statistics.mean(c_std) * 1.5        # 분산은 확실히 이동


def test_case2_real_cause_separates_more_than_decoys():
    """진짜 원인 센서가 미끼보다 크게 갈린다 (순위가 뒤집히면 안 된다)."""
    real_gap = abs(statistics.mean(_vals(f"{SENSOR_REAL}_avg", GROUP_WAFERS))
                   - statistics.mean(_vals(f"{SENSOR_REAL}_avg", CONTROL_WAFERS)))
    for decoy in SENSOR_DECOYS:
        gap = abs(statistics.mean(_vals(f"{decoy}_avg", GROUP_WAFERS))
                  - statistics.mean(_vals(f"{decoy}_avg", CONTROL_WAFERS)))
        assert gap < real_gap


def test_case3_collinear_sensors_move_together():
    """연동된 센서 둘이 함께 이동한다 — 순위만으로는 못 가리는 상황."""
    a, b = SENSOR_COLLINEAR
    for name in (a, b):
        t = statistics.mean(_vals(f"{name}_avg", GROUP_WAFERS))
        c = statistics.mean(_vals(f"{name}_avg", CONTROL_WAFERS))
        assert abs(t - c) > 0


def test_case4_missing_sensor_rows():
    """일부 wafer 는 센서 행이 아예 없다 — 결측이 분모를 오염시키면 안 된다."""
    assert _vals(f"{SENSOR_REAL}_avg", [SENSOR_MISSING_WAFER]) == []
