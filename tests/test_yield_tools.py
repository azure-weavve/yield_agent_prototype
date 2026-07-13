"""tools/yield_tools.py 결정론적 함수 검증 (더미 DB 는 seed 42 고정)."""

import sqlite3

import config
from tools import yield_tools as yt


def test_get_process_log_returns_4_steps_with_in_spec():
    logs = yt.get_process_log("W2406_02")
    assert len(logs) == 4
    assert all("in_spec" in r for r in logs)


def test_pattern_wafer_anomaly_flagged():
    logs = yt.get_process_log("W2406_02")
    bad = [r for r in logs if not r["in_spec"]]
    assert len(bad) == 1
    assert bad[0]["process_step"] == "Etch"
    assert bad[0]["equipment_id"] == "ETCH-9"


def test_unknown_wafer_returns_empty():
    assert yt.get_process_log("W_NOPE") == []


def test_find_defect_group_splits_target_and_control():
    grp = yt.find_defect_group("LOT2406")
    assert grp["defect_type"] == "center_spot"
    assert grp["target_group"] == ["W2406_02", "W2406_04", "W2406_06"]
    assert grp["control_group"] == ["W2406_01", "W2406_03", "W2406_05"]


def test_find_defect_group_unknown_lot_returns_empty():
    grp = yt.find_defect_group("LOT_NOPE")
    assert grp["defect_type"] == ""
    assert grp["target_group"] == []
    assert grp["control_group"] == []


def test_compare_process_logs_finds_suspect_equipment_and_violations():
    res = yt.compare_process_logs(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
    )
    # 불량 그룹 전원이 거쳤고 대조 그룹은 안 거친 장비에 ETCH-9 가 잡힌다
    suspects = {(r["process_step"], r["equipment_id"]) for r in res["suspect_equipment"]}
    assert ("Etch", "ETCH-9") in suspects
    # 스펙 이탈은 불량 그룹 3장 전부, 모두 ETCH-9
    assert len(res["group_spec_violations"]) == 3
    assert all(v["equipment_id"] == "ETCH-9" for v in res["group_spec_violations"])
    # 대조표에는 두 그룹의 통과 수가 담긴다
    etch9 = next(r for r in res["equipment_usage"]
                 if (r["process_step"], r["equipment_id"]) == ("Etch", "ETCH-9"))
    assert (etch9["group_count"], etch9["control_count"]) == (3, 0)


def test_compare_process_logs_empty_inputs():
    res = yt.compare_process_logs([], [])
    assert res == {"suspect_equipment": [], "equipment_usage": [], "group_spec_violations": []}


# ------------------------------------------------ validate_data_completeness


def _make_db(tmp_path, monkeypatch, rows, logs):
    """검사 시나리오용 임시 DB (실제 스키마와 동일). config.DB_PATH 를 바꿔치기한다."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (
        wafer_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, yield REAL NOT NULL,
        defect_type TEXT NOT NULL, process_step TEXT, date TEXT NOT NULL)""")
    conn.executemany("INSERT INTO yield VALUES (?,?,?,?,?,?)", rows)
    conn.execute("""CREATE TABLE process_log (
        wafer_id TEXT NOT NULL, process_step TEXT NOT NULL, equipment_id TEXT NOT NULL,
        param_name TEXT NOT NULL, param_value REAL NOT NULL,
        spec_low REAL NOT NULL, spec_high REAL NOT NULL)""")
    conn.executemany("INSERT INTO process_log VALUES (?,?,?,?,?,?,?)", logs)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)


def test_validate_completeness_good_on_dummy_wafers():
    res = yt.validate_data_completeness(["W2406_02", "W2406_01"])
    assert res["status"] == "good"
    assert res["checked_wafers"] == 2
    assert res["missing_yield_rows"] == []
    assert res["missing_log_steps"] == []
    assert res["duplicate_logs"] == []


def test_validate_completeness_flags_missing_wafer_as_blocked():
    res = yt.validate_data_completeness(["W2406_02", "W_NOPE"])
    assert res["status"] == "blocked"
    assert res["missing_yield_rows"] == ["W_NOPE"]
    # 전체 process_log 에 존재하는 4개 단계가 전부 누락으로 잡힌다
    assert res["missing_log_steps"] == [
        {"wafer_id": "W_NOPE", "missing_steps": ["CMP", "Diffusion", "Etch", "Photo"]}
    ]
    assert res["warnings"]


def test_validate_completeness_flags_duplicates_as_warning(tmp_path, monkeypatch):
    _make_db(
        tmp_path, monkeypatch,
        rows=[("W1", "L1", 95.0, "none", "Normal", "2024-06-01")],
        logs=[("W1", "Etch", "ETCH-1", "rf_power", 500.0, 450.0, 550.0),
              ("W1", "Etch", "ETCH-1", "rf_power", 501.0, 450.0, 550.0)],
    )
    res = yt.validate_data_completeness(["W1"])
    assert res["status"] == "warning"
    assert res["duplicate_logs"] == [
        {"wafer_id": "W1", "process_step": "Etch", "param_name": "rf_power", "count": 2}
    ]


def test_validate_completeness_empty_input_blocked():
    res = yt.validate_data_completeness([])
    assert res["status"] == "blocked"
    assert res["checked_wafers"] == 0


# ------------------------------------------------ compare_parameter_distribution


def test_compare_parameter_distribution_ranks_rf_power_first():
    rows = yt.compare_parameter_distribution(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
    )
    assert len(rows) == 4                        # 4개 (공정, 파라미터) 전부
    top = rows[0]                                # |effect_size| 1위 = rf_power (d=3.6)
    assert (top["process_step"], top["param_name"]) == ("Etch", "rf_power")
    assert top["group"]["n"] == 3 and top["control"]["n"] == 3
    assert top["group"]["mean"] == 570.0         # 스펙 상한 20% 초과 고정값
    assert top["group"]["std"] == 0.0            # 3장 전부 동일값
    assert top["mean_diff"] > 0 and top["effect_size"] > 2.0
    assert top["spec_violation_rate_group"] == 1.0
    assert top["spec_violation_rate_control"] == 0.0


def test_compare_parameter_distribution_filters_by_step():
    rows = yt.compare_parameter_distribution(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
        process_step="Etch",
    )
    assert [(r["process_step"], r["param_name"]) for r in rows] == [("Etch", "rf_power")]


def test_compare_parameter_distribution_one_sided_group():
    # 대조 그룹이 비어도 죽지 않는다 — 통계는 그룹 쪽만, 비교치는 None
    rows = yt.compare_parameter_distribution(["W2406_02"], [])
    assert all(r["control"]["n"] == 0 for r in rows)
    assert all(r["mean_diff"] is None and r["effect_size"] is None for r in rows)


def test_compare_parameter_distribution_empty_inputs():
    assert yt.compare_parameter_distribution([], []) == []
