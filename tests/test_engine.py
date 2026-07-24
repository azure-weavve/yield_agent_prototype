"""engine.evaluate — commonality legend 어댑터. 게이트 계약(passes/value) 매핑 검증."""

import sqlite3
import pytest

import config
from domain import engine

EQP_CH = [{"level": "equipment", "columns": ["eqp_id"]},
          {"level": "chamber", "columns": ["eqp_id", "ch_id"]}]
PPID = [{"level": "ppid", "columns": ["ppid"]}]


@pytest.fixture
def fx_db(tmp_path, monkeypatch):
    """step_history 픽스처. 불량군 3장 전원 Etch=ETCH9_B(+PPID_X), 대조군은 ETCH8/PPID_Y.
    Photo 는 양쪽 공유(미끼)."""
    db = tmp_path / "fx.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (wafer_id TEXT PRIMARY KEY, lot_id TEXT, yield REAL,
        defect_type TEXT, process_step TEXT, date TEXT, root_lot_id TEXT, lot_type TEXT)""")
    conn.execute("""CREATE TABLE step_history (wafer_id TEXT, process_step TEXT, eqp_id TEXT,
        ch_id TEXT, ppid TEXT, timestamp TEXT)""")
    group, control = ["G1", "G2", "G3"], ["C1", "C2", "C3"]
    for w in group:
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)",
                     (w, "L.1", 80.0, "none", None, "d", "R1", "prod"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Etch", "ETCH9", "B", "PPID_X", "t"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Photo", "PHOTO1", "A", "PPID_Z", "t"))
    for i, w in enumerate(control):
        conn.execute("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)",
                     (w, "L.1", 95.0, "none", None, "d", "R1", "prod"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Etch", "ETCH8", str(i), "PPID_Y", "t"))
        conn.execute("INSERT INTO step_history VALUES (?,?,?,?,?,?)",
                     (w, "Photo", "PHOTO1", "A", "PPID_Z", "t"))
    conn.commit(); conn.close()
    monkeypatch.setattr(config, "DB_PATH", db)
    return db


def test_evaluate_maps_chamber_to_gate_contract(fx_db):
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["hypothesis_id"] == "eqp_ch"
    assert res["status"] == "ok"
    by_key = {c["key"]: c for c in res["candidates"]}
    ch = by_key["ETCH9_B"]
    assert ch["value"] == ["Etch", "ETCH9_B"]        # 게이트 토큰 = value[-1]
    assert ch["passes"] is True
    assert (ch["target_pass"], ch["control_pass"]) == (3, 0)
    # 미끼 Photo(PHOTO1_A)는 양쪽 공유 → score 0 → 후보에서 탈락(애초에 안 실림)
    assert "PHOTO1_A" not in by_key


def test_evaluate_ppid_legend(fx_db):
    res = engine.evaluate({"id": "ppid", "legend": PPID}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    by_key = {c["key"]: c for c in res["candidates"]}
    assert by_key["PPID_X"]["passes"] is True
    assert by_key["PPID_X"]["value"] == ["Etch", "PPID_X"]


def test_evaluate_passes_false_below_threshold(fx_db, monkeypatch):
    # 임계를 1.0 초과로 올리면 score 1.0 후보도 passes=False
    monkeypatch.setattr(config, "COMMONALITY_PASS_MIN_SCORE", 1.5)
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert all(not c["passes"] for c in res["candidates"])


def test_evaluate_no_signal_status(fx_db, monkeypatch):
    # 대조군도 ETCH9_B 를 거치면 분리 없음 → no_signal, 후보 빈 리스트
    conn = sqlite3.connect(fx_db)
    conn.execute("UPDATE step_history SET eqp_id='ETCH9', ch_id='B' WHERE process_step='Etch'")
    conn.commit(); conn.close()
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["status"] == "no_signal"
    assert res["candidates"] == []


def test_evaluate_passes_requires_status_ok(fx_db, monkeypatch):
    # status != "ok" 인데 candidates 가 비어있지 않은 상황(불변식이 깨진 경우)에도
    # passes 는 status 를 AND 조건으로 봐야 한다 (스펙 §7).
    monkeypatch.setattr(engine.cm, "find_commonality", lambda *a, **k: {
        "status": "no_paired_stratum",
        "candidates": [{"level": "chamber", "process_step": "Etch", "key": "ETCH9_B",
                        "score": 1.0, "target_pass": 3, "target_total": 3,
                        "control_pass": 0, "control_total": 3,
                        "coverage_target": 1.0, "coverage_control": 0.0}],
        "meta": None, "note": None,
    })
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["candidates"]
    assert all(c["passes"] is False for c in res["candidates"])
