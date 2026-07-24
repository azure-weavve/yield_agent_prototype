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
    for w in group:
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?)", (w, "L", 80.0, "center_spot", "Etch", "d"))
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Etch", "ETCH-9", "ETCH9_B", "rf_power", 570.0, 450.0, 550.0))
    for i, w in enumerate(control):
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?)", (w, "L", 95.0, "none", "Normal", "d"))
        conn.execute("INSERT INTO process_log VALUES (?,?,?,?,?,?,?,?)",
                     (w, "Etch", f"ETCH-{i+1}", f"ETCH{i+1}_A", "rf_power", 500.0, 450.0, 550.0))
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


def test_group_only_matches_legacy_compare_process_logs():
    """이관 안전망: engine 통과 후보의 장비 == 기존 도구 suspect_equipment."""
    from tools import yield_tools as yt
    group = ["W2406_02", "W2406_04", "W2406_06"]
    control = ["W2406_01", "W2406_03", "W2406_05"]
    legacy = {r["equipment_id"] for r in yt.compare_process_logs(group, control)["suspect_equipment"]}
    cands = engine.group_only_categorical(group, control, "equipment_id", {})
    ours = {c["value"][1] for c in cands if c["passes"]}
    assert ours == legacy
