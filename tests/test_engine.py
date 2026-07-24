"""engine 비교타입·판별 계층 단위 테스트. 픽스처 DB 를 임시 생성해 결정론 검증."""

import sqlite3
import pytest

from domain import engine


@pytest.fixture
def fx_db(tmp_path, monkeypatch):
    """process_log + yield 최소 픽스처. 불량군 3장 전원 Etch=ETCH-9, 대조군 3장은 ETCH-1~3."""
    db = tmp_path / "fx.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE yield (wafer_id TEXT PRIMARY KEY, lot_id TEXT, yield REAL, "
                 "defect_type TEXT, process_step TEXT, date TEXT)")
    conn.execute("CREATE TABLE process_log (wafer_id TEXT, process_step TEXT, equipment_id TEXT, "
                 "eq_chamber TEXT, param_name TEXT, param_value REAL, spec_low REAL, spec_high REAL)")
    group = ["G1", "G2", "G3"]
    control = ["C1", "C2", "C3"]
    group_vals = [570.0, 572.0, 568.0]
    control_vals = [500.0, 502.0, 498.0]
    for w, v in zip(group, group_vals):
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?)", (w, "L", 80.0, "center_spot", "Etch", "d"))
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Etch", "ETCH-9", "ETCH9_B", "rf_power", v, 450.0, 550.0))
    for i, (w, v) in enumerate(zip(control, control_vals)):
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?)", (w, "L", 95.0, "none", "Normal", "d"))
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Etch", f"ETCH-{i+1}", f"ETCH{i+1}_A", "rf_power", v, 450.0, 550.0))
    conn.commit(); conn.close()
    monkeypatch.setattr(engine.config, "DB_PATH", str(db))
    return db


def test_group_only_flags_group_exclusive_equipment(fx_db):
    cands = engine.group_only_categorical(["G1", "G2", "G3"], ["C1", "C2", "C3"], "equipment_id", {})
    passing = [c for c in cands if c["passes"]]
    assert len(passing) == 1
    c = passing[0]
    assert c["value"] == ["Etch", "ETCH-9"]
    assert c["specificity"] == 1.0
    assert c["n_group"] == 3 and c["n_control"] == 0


def test_group_only_excludes_shared_equipment(fx_db):
    # 대조군도 쓰는 값은 통과 후보가 아니다
    cands = engine.group_only_categorical(["G1", "G2", "G3"], ["C1", "C2", "C3"], "equipment_id", {})
    assert all(c["value"] != ["Etch", "ETCH-1"] or not c["passes"] for c in cands)


def test_unknown_column_raises_clear_error(fx_db):
    with pytest.raises(ValueError, match="bogus"):
        engine.group_only_categorical(["G1", "G2", "G3"], ["C1", "C2", "C3"],
                                       "bogus; DROP TABLE yield", {})


def test_numeric_shift_flags_drifted_parameter(fx_db):
    cands = engine.numeric_distribution_shift(["G1", "G2", "G3"], ["C1", "C2", "C3"], "param_value", {})
    passing = [c for c in cands if c["passes"]]
    assert len(passing) == 1
    c = passing[0]
    assert c["value"] == ["Etch", "rf_power"]
    assert c["specificity"] is None
    assert c["effect_size"] is not None and abs(c["effect_size"]) >= 0.8
    assert c["spec_violation_rate"] == 1.0     # 불량군 3행 전부 스펙 밖 (스펙 이탈 흡수)


def test_numeric_shift_rejects_when_no_drift(fx_db, monkeypatch):
    # 대조군도 570 이면 효과크기 0 → 탈락 (기존 오탐 보정)
    import sqlite3
    conn = sqlite3.connect(fx_db)
    conn.execute("UPDATE process_log SET param_value = 570.0 WHERE wafer_id LIKE 'C%'")
    conn.commit(); conn.close()
    cands = engine.numeric_distribution_shift(["G1", "G2", "G3"], ["C1", "C2", "C3"], "param_value", {})
    assert all(not c["passes"] for c in cands)


def test_numeric_shift_unknown_column_raises_clear_error(fx_db):
    with pytest.raises(ValueError, match="bogus"):
        engine.numeric_distribution_shift(["G1", "G2", "G3"], ["C1", "C2", "C3"],
                                           "bogus; DROP TABLE yield", {})


def test_group_only_matches_legacy_compare_process_logs():
    """이관 안전망: engine 통과 후보의 장비 == 기존 도구 suspect_equipment."""
    from tools import yield_tools as yt
    group = ["W2406_02", "W2406_04", "W2406_06"]
    control = ["W2406_01", "W2406_03", "W2406_05"]
    legacy = {r["equipment_id"] for r in yt.compare_process_logs(group, control)["suspect_equipment"]}
    cands = engine.group_only_categorical(group, control, "equipment_id", {})
    ours = {c["value"][1] for c in cands if c["passes"]}
    assert ours == legacy
