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
        defect_type TEXT, step_seq TEXT, date TEXT, root_lot_id TEXT, lot_type TEXT)""")
    conn.execute("""CREATE TABLE step_history (wafer_id TEXT, step_seq TEXT, eqp_id TEXT,
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
    conn.execute("UPDATE step_history SET eqp_id='ETCH9', ch_id='B' WHERE step_seq='Etch'")
    conn.commit(); conn.close()
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["status"] == "no_signal"
    assert res["candidates"] == []


def test_evaluate_passes_requires_status_ok(fx_db, monkeypatch):
    # status != "ok" 인데 candidates 가 비어있지 않은 상황(불변식이 깨진 경우)에도
    # passes 는 status 를 AND 조건으로 봐야 한다 (스펙 §7).
    monkeypatch.setattr(engine.cm, "find_commonality", lambda *a, **k: {
        "status": "no_paired_stratum",
        "candidates": [{"level": "chamber", "step_seq": "Etch", "key": "ETCH9_B",
                        "score": 1.0, "target_pass": 3, "target_total": 3,
                        "control_pass": 0, "control_total": 3,
                        "coverage_target": 1.0, "coverage_control": 0.0}],
        "meta": None, "note": None,
    })
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    assert res["candidates"]
    assert all(c["passes"] is False for c in res["candidates"])


def test_evaluate_issues_claim_id_per_candidate(fx_db):
    """claim_id 는 게이트가 조회할 유일한 키다 — 도구가 발급해 결과에 실어 보낸다."""
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    by_key = {c["key"]: c for c in res["candidates"]}
    assert by_key["ETCH9_B"]["claim_id"] == "eqp_ch:chamber:Etch:ETCH9_B"
    # 모든 후보가 발급받는다 (통과 여부와 무관 — 반려 사유를 돌려주려면 미통과도 조회돼야 한다)
    assert all(c["claim_id"] for c in res["candidates"])


def test_claim_id_is_namespaced_by_hypothesis(fx_db):
    """같은 legend 를 다른 가설 id 로 돌리면 후보는 같고 claim_id 만 갈린다.

    legend 가 다른 두 도구(EQP_CH vs PPID)로 비교하면 애초에 key 가 안 겹쳐서,
    구현에서 id 접두어를 지워도 통과하는 공허한 테스트가 된다.
    """
    a = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                        ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    b = engine.evaluate({"id": "eqp_ch_v2", "legend": EQP_CH},
                        ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    keys = [c["key"] for c in a["candidates"]]
    assert keys and keys == [c["key"] for c in b["candidates"]]   # 같은 후보 집합인지 먼저
    assert not ({c["claim_id"] for c in a["candidates"]} &
                {c["claim_id"] for c in b["candidates"]})


def test_claim_id_is_issued_for_failing_candidates_too(fx_db, monkeypatch):
    """미통과 후보도 발급받는다 - 게이트가 반려 사유를 돌려주려면 조회돼야 한다.

    fx_db 기본 시나리오는 후보가 전부 passes=True 라, 임계를 올려 미통과 후보를
    만들지 않으면 이 요구가 한 번도 검증되지 않는다.
    """
    monkeypatch.setattr(config, "COMMONALITY_PASS_MIN_SCORE", 1.5)
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    failing = [c for c in res["candidates"] if not c["passes"]]
    assert failing, "미통과 후보가 없으면 이 테스트는 아무것도 지키지 않는다"
    by_key = {c["key"]: c for c in failing}
    assert by_key["ETCH9_B"]["claim_id"] == "eqp_ch:chamber:Etch:ETCH9_B"
