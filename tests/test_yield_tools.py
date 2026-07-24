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


def test_get_wafers_returns_rows_for_known_ids_only():
    rows = yt.get_wafers(["W2406_02", "W_NOPE", "W2406_01"])
    assert [r["wafer_id"] for r in rows] == ["W2406_01", "W2406_02"]  # 미존재는 조용히 제외
    assert rows[1]["lot_id"] == "LOT2406"


def test_find_normal_wafers_applies_yield_threshold():
    # 구멍 (가): W2406_07 은 none 이지만 88.5 < 90 → 대조군 후보에서 제외
    assert yt.find_normal_wafers("LOT2406") == ["W2406_01", "W2406_03", "W2406_05"]


def test_find_low_yield_lots_threshold_binds_at_runtime(monkeypatch):
    # 문제 9: 기본 인자가 import 시점 값으로 굳으면 런타임 변경이 무시된다
    monkeypatch.setattr(config, "YIELD_THRESHOLD", 0.0)
    assert yt.find_low_yield_lots() == []


def test_compare_process_logs_finds_suspect_equipment_and_violations():
    # 더미 데이터 설계 변경: 대조군도 Etch 에서 같은 설비 ETCH-9 를 쓴다(다른 챔버
    # ETCH9_C). 설비 단위 신호는 의도적으로 억제되어 ETCH-9 가 더 이상 suspect_equipment
    # 에 잡히지 않는다 — 실제 원인은 챔버 단위(eq_chamber=ETCH9_B)에만 있고, 그건 이
    # 구 도구가 아니라 새 chamber_concentration 가설로 찾는다.
    res = yt.compare_process_logs(
        ["W2406_02", "W2406_04", "W2406_06"],
        ["W2406_01", "W2406_03", "W2406_05"],
    )
    # 대조군도 ETCH-9 를 거치므로 더 이상 suspect 로 잡히지 않는다 (공유 설비는 제외 대상)
    suspects = {(r["process_step"], r["equipment_id"]) for r in res["suspect_equipment"]}
    assert ("Etch", "ETCH-9") not in suspects
    # 스펙 이탈은 불량 그룹 3장 전부, 모두 ETCH-9 (이 부분은 변경 없음)
    assert len(res["group_spec_violations"]) == 3
    assert all(v["equipment_id"] == "ETCH-9" for v in res["group_spec_violations"])
    # 대조표: 대조군 3장도 이제 ETCH-9 를 거치므로 control_count 는 0 -> 3
    etch9 = next(r for r in res["equipment_usage"]
                 if (r["process_step"], r["equipment_id"]) == ("Etch", "ETCH-9"))
    assert (etch9["group_count"], etch9["control_count"]) == (3, 3)


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
        spec_low REAL, spec_high REAL)""")
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


# ------------------------------------------------ find_counterexamples


def test_find_counterexamples_one_for_etch9_hypothesis():
    # 더미 데이터 설계 변경: 대조군 3장도 Etch 에서 ETCH-9 를 쓴다(챔버만 다름=ETCH9_C).
    # ETCH-9 사용자: 불량군 3 + 과거 center_spot 패턴 4 + 구멍(가) W2406_07 1 + 대조군 3
    # = 11장 (기존 8장에서 대조군 3장 추가). 대조군은 defect_type='none' 이고 값이
    # 스펙 내(균등분포)이므로 반례(passed_but_normal)에도 3장이 새로 추가된다.
    res = yt.find_counterexamples("ETCH-9", "Etch", "center_spot")
    assert res["equipment_wafers"] == 11
    assert [r["wafer_id"] for r in res["passed_but_normal"]] == [
        "W2406_01", "W2406_03", "W2406_05", "W2406_07",
    ]
    assert all(r["in_spec"] is True for r in res["passed_but_normal"])
    assert res["passed_but_normal_rate"] == round(4 / 11, 3)
    assert res["defect_wafers"] == 7
    assert res["defect_without_equipment"] == []
    assert res["defect_without_equipment_rate"] == 0.0


def test_find_counterexamples_found_for_normal_equipment():
    # ETCH-1 통과자는 대부분 정상 → 'ETCH-1 이 원인' 가설이면 반례가 다수 잡힌다
    res = yt.find_counterexamples("ETCH-1", "Etch", "center_spot")
    assert res["passed_but_normal"]
    assert 0.0 < res["passed_but_normal_rate"] <= 1.0
    assert all(r["in_spec"] for r in res["passed_but_normal"])
    # center_spot 은 전부 ETCH-9 를 거쳤으므로 'ETCH-1 없이 발생' 비율 100%
    assert res["defect_without_equipment_rate"] == 1.0


def test_find_counterexamples_unknown_equipment():
    res = yt.find_counterexamples("ETCH-99", "Etch", "center_spot")
    assert res["equipment_wafers"] == 0
    assert res["passed_but_normal_rate"] == 0.0
    assert res["defect_without_equipment_rate"] == 1.0


# ------------------------------------------------ spec NULL 처리 (사내 실데이터: 편측/미정 spec)


def test_compare_parameter_distribution_null_spec_no_crash(tmp_path, monkeypatch):
    # 같은 (step, param) 3행 중 spec 있는 행 2개, 그중 1개 이탈 → 이탈률 0.5.
    # 다른 (step, param) 은 전 행 spec 없음 → 이탈률 None.
    _make_db(
        tmp_path, monkeypatch,
        rows=[("W1", "L1", 95.0, "none", "Normal", "2024-06-01"),
              ("W2", "L1", 95.0, "none", "Normal", "2024-06-01"),
              ("W3", "L1", 95.0, "none", "Normal", "2024-06-01")],
        logs=[("W1", "Etch", "ETCH-1", "rf_power", 500.0, 450.0, 550.0),   # spec 있음, 이탈 아님
              ("W2", "Etch", "ETCH-1", "rf_power", 600.0, 450.0, 550.0),   # spec 있음, 이탈
              ("W3", "Etch", "ETCH-1", "rf_power", 700.0, None, None),     # spec 없음
              ("W1", "CMP", "CMP-1", "pressure", 10.0, None, None)],      # 전 행 spec 없음
    )
    rows = yt.compare_parameter_distribution(["W1", "W2", "W3"], [])
    etch = next(r for r in rows if (r["process_step"], r["param_name"]) == ("Etch", "rf_power"))
    assert etch["group"]["n"] == 3                       # 기술통계는 전체 행 기준 유지
    assert etch["spec_violation_rate_group"] == 0.5       # 분모 = spec 있는 행 수(2)
    cmp_row = next(r for r in rows if (r["process_step"], r["param_name"]) == ("CMP", "pressure"))
    assert cmp_row["spec_violation_rate_group"] is None    # spec 있는 행 0개 → 판정 불가


def test_compare_parameter_distribution_one_sided_spec_high_violation(tmp_path, monkeypatch):
    # spec_low 만 NULL(편측), param_value 가 spec_high 초과 → 이탈로 잡혀야 한다.
    _make_db(
        tmp_path, monkeypatch,
        rows=[("W1", "L1", 95.0, "none", "Normal", "2024-06-01")],
        logs=[("W1", "Etch", "ETCH-1", "rf_power", 600.0, None, 550.0)],
    )
    rows = yt.compare_parameter_distribution(["W1"], [])
    etch = rows[0]
    assert etch["spec_violation_rate_group"] == 1.0


def test_find_counterexamples_null_spec_in_spec_none(tmp_path, monkeypatch):
    _make_db(
        tmp_path, monkeypatch,
        rows=[("W1", "L1", 95.0, "none", "Normal", "2024-06-01"),
              ("W2", "L1", 95.0, "none", "Normal", "2024-06-01")],
        logs=[("W1", "Etch", "ETCH-1", "rf_power", 500.0, None, None),     # 양쪽 spec 없음
              ("W2", "Etch", "ETCH-1", "rf_power", 500.0, None, 550.0)],   # 편측, spec 이내
    )
    res = yt.find_counterexamples("ETCH-1", "Etch", "none_placeholder")
    by_id = {r["wafer_id"]: r for r in res["passed_but_normal"]}
    assert by_id["W1"]["in_spec"] is None
    assert by_id["W2"]["in_spec"] is True


def test_compare_process_logs_one_sided_spec_violation_and_both_null_excluded(tmp_path, monkeypatch):
    _make_db(
        tmp_path, monkeypatch,
        rows=[("W1", "L1", 80.0, "center_spot", "Normal", "2024-06-01")],
        logs=[("W1", "Etch", "ETCH-9", "rf_power", 600.0, None, 550.0),    # 편측, 상한 초과 → 이탈
              ("W1", "CMP", "CMP-1", "pressure", 10.0, None, None)],      # 양쪽 NULL → 안 잡힘
    )
    res = yt.compare_process_logs(["W1"], [])
    steps = {(v["process_step"], v["param_name"]) for v in res["group_spec_violations"]}
    assert ("Etch", "rf_power") in steps
    assert ("CMP", "pressure") not in steps
