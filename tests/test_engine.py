"""engine.evaluate — commonality legend 어댑터. 게이트 계약(passes/value) 매핑 검증."""

import sqlite3
import pytest

import ya_config
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
    monkeypatch.setattr(ya_config, "DB_PATH", db)
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
    monkeypatch.setattr(ya_config, "COMMONALITY_PASS_MIN_SCORE", 1.5)
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
                        "coverage_target": 1.0, "coverage_control": 0.0,
                        "target_wafers": ["G1", "G2", "G3"], "control_wafers": []}],
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
    monkeypatch.setattr(ya_config, "COMMONALITY_PASS_MIN_SCORE", 1.5)
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    failing = [c for c in res["candidates"] if not c["passes"]]
    assert failing, "미통과 후보가 없으면 이 테스트는 아무것도 지키지 않는다"
    by_key = {c["key"]: c for c in failing}
    assert by_key["ETCH9_B"]["claim_id"] == "eqp_ch:chamber:Etch:ETCH9_B"


def test_evaluate_carries_permutation_p(fx_db):
    """p 가 후보에 실려 나간다.

    3대3 은 6장 중 3장을 고르는 20가지뿐이라 완전 분리여도 p 가 0.05 아래로
    못 내려간다. 판정이 p 와 무관하다는 요구는 `_passes` 를 직접 때리는
    아래 테스트가 잠근다 - 여기서 `passes is True` 를 단언해도 p 문턱이 0.05
    이하로 들어오면 그대로 통과해 버려 아무것도 지키지 못한다.
    """
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    ch = {c["key"]: c for c in res["candidates"]}["ETCH9_B"]
    assert ch["p_permutation"] == 0.05


def test_gate_verdict_never_reads_the_permutation_p():
    """p 는 실려 나가되 판정에는 안 쓴다 (설계 §2-3).

    자동 차단은 실데이터를 본 뒤에 얹는다. 지금 p 로 거르면 소표본에서 바닥값이
    0.05~0.17 인 후보가 통째로 사라져, 진짜 원인이 게이트 앞에서 증발한다.
    같은 후보를 p 만 바꿔 넣어 판정이 안 변하는 것으로 잠근다.
    """
    cand = {"score": 1.0, "target_pass": 3}
    verdicts = {engine._passes({**cand, "p_permutation": p, "p_min_possible": p},
                               0.5, 2, "ok", True)
                for p in (None, 0.0001, 0.05, 0.5, 0.99)}
    assert verdicts == {(True, None)}


def test_evaluate_carries_the_p_floor_so_a_big_p_can_be_read_correctly(fx_db):
    """p 만 실으면 "바닥값" 과 "약한 신호" 가 같은 숫자로 보인다.

    3대3 은 6장에서 3장을 고르는 20가지뿐이라 완전 분리여도 p 가 0.05 밑으로
    못 내려간다. 그 0.05 는 **이 표본이 낼 수 있는 최강 결과**인데, 바닥값을
    같이 싣지 않으면 리포트에서 "유의하지 않다" 로 읽힌다 - 뜻이 정반대다.
    `hypotheses.yaml` 이 LLM 에게 이 필드를 읽으라고 지시하므로, 없으면 LLM 은
    무시하거나 지어낸다.
    """
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH},
                          ["G1", "G2", "G3"], ["C1", "C2", "C3"])
    ch = {c["key"]: c for c in res["candidates"]}["ETCH9_B"]
    assert ch["p_min_possible"] == 0.05
    assert ch["n_permutations_total"] == 20
    assert ch["p_permutation"] == ch["p_min_possible"]   # 완전 분리 = 바닥값에 닿음


def test_evaluate_carries_the_fdr_table_and_family_wise_p(fx_db):
    """`hypotheses.yaml` 이 LLM 에게 "결과 최상위의 fdr_table" 을 읽으라고 지시한다.

    어댑터가 후보 목록만 넘기고 최상위 통계를 버리면 그 지시가 거짓이 되고,
    commonality 가 순열 회차마다 모은 재료(null_counts·null_max)가 계산만 되고
    버려진다. 값을 지어내지 말고 commonality 가 낸 것을 그대로 옮겨야 한다.
    """
    args = (["G1", "G2", "G3"], ["C1", "C2", "C3"])
    res = engine.evaluate({"id": "eqp_ch", "legend": EQP_CH}, *args)
    raw = engine.cm.find_commonality(*args, legend=EQP_CH)

    assert res["fdr_table"], "완전 분리 후보가 있는데 표가 비면 재료를 버린 것이다"
    assert res["fdr_table"] == raw["fdr_table"]
    assert res["p_family_wise"] is not None
    assert res["p_family_wise"] == raw["p_family_wise"]
    # 1등의 p 도 바닥값을 동반해야 한다 - 최상위 값이라 근거 줄이 교정 못 해 준다
    assert res["p_family_wise_min_possible"] == raw["p_family_wise_min_possible"]
    assert res["p_family_wise"] >= res["p_family_wise_min_possible"]
