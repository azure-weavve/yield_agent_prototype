"""tools/commonality.py 검증 — 설비/챔버 공통성 분석.

step_history 는 ETL 선적재 대상이라 아직 더미 DB 에 없다.
따라서 모든 테스트가 임시 DB 를 만들어 config.DB_PATH 를 바꿔치기한다
(tests/test_yield_tools.py 의 _make_db 패턴과 동일).
"""

import sqlite3

import ya_config
from tools import commonality as cm


# ------------------------------------------------------------------ 픽스처

def _make_db(tmp_path, monkeypatch, yield_rows, history_rows):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (
        wafer_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, yield REAL NOT NULL,
        defect_type TEXT NOT NULL, step_seq TEXT, date TEXT NOT NULL,
        root_lot_id TEXT NOT NULL, lot_type TEXT NOT NULL)""")
    conn.executemany("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)", yield_rows)
    conn.execute("""CREATE TABLE step_history (
        wafer_id TEXT NOT NULL, step_seq TEXT NOT NULL, eqp_id TEXT NOT NULL,
        ch_id TEXT, timestamp TEXT)""")
    conn.executemany("INSERT INTO step_history VALUES (?,?,?,?,?)", history_rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(ya_config, "DB_PATH", db)


def _y(wid, root, lot_type="prod"):
    """yield 행 — commonality 는 root_lot_id / lot_type 만 읽는다."""
    return (wid, f"{root}.1", 90.0, "none", None, "2026-06-17", root, lot_type)


def _h(wid, step, eqp, ch=None, ts="2026-06-17 10:00:00"):
    return (wid, step, eqp, ch, ts)


def _keys(res):
    return {(c["level"], c["key"]) for c in res["candidates"]}


def _find(res, level, key):
    return next(c for c in res["candidates"] if c["level"] == level and c["key"] == key)


# ------------------------------------------------------------------ 기본 신호

def test_clean_separation_scores_one(tmp_path, monkeypatch):
    """타깃 3장 전원이 ETCH9 3번 챔버를 거치고 대조군은 아무도 안 거친 경우."""
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = []
    for w in t:
        hs += [_h(w, "Etch", "ETCH9", "3"), _h(w, "Photo", "PHOTO1", "1")]
    for w in c:
        hs += [_h(w, "Etch", "ETCH8", "1"), _h(w, "Photo", "PHOTO1", "1")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert res["status"] == "ok"
    # Etch 만 분리된다. Photo(PHOTO1_1)는 양쪽 다 거쳐 score 0 → 탈락
    assert _keys(res) == {("equipment", "ETCH9"), ("chamber", "ETCH9_3")}

    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (3, 3)
    assert (ch["control_pass"], ch["control_total"]) == (0, 3)
    assert ch["coverage_target"] == 1.0 and ch["coverage_control"] == 0.0
    assert ch["score"] == 1.0
    assert ch["step_seq"] == "Etch" and ch["eqp_id"] == "ETCH9" and ch["ch_id"] == "3"
    assert ch["n_strata"] == 1


def test_shared_equipment_excluded(tmp_path, monkeypatch):
    """양쪽 그룹이 똑같이 거친 설비는 후보가 아니다 (score <= 0)."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "Etch", "ETCH9", "3") for w in t]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert ("chamber", "PHOTO1_1") not in _keys(res)
    assert ("chamber", "ETCH9_3") in _keys(res)


# ------------------------------------------------------------------ 조기 출구

def test_all_common_returns_no_signal(tmp_path, monkeypatch):
    """전원이 같은 경로 → 분리 없음. '원인 없음'이 아니라 lot 내부 대조 한계."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t + c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert res["status"] == "no_signal"
    assert res["candidates"] == []
    assert "lot 밖 대조군" in res["note"]


def test_single_target_is_insufficient_group(tmp_path, monkeypatch):
    """타깃 1장이면 모든 경로가 '공통'이라 계산 자체를 하지 않는다."""
    _make_db(tmp_path, monkeypatch,
             [_y("T1", "A45Z5"), _y("C1", "A45Z5")],
             [_h("T1", "Etch", "ETCH9", "3"), _h("C1", "Etch", "ETCH8", "1")])

    res = cm.find_commonality(["T1"], ["C1"])
    assert res["status"] == "insufficient_group"
    assert res["candidates"] == []
    assert res["n_target"] == 1


def test_control_in_other_root_lot_is_not_paired(tmp_path, monkeypatch):
    """대조군이 타깃과 다른 root_lot 뿐이면 route 교락 없이 비교할 짝이 없다."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "AAAAA") for w in t] + [_y(w, "BBBBB") for w in c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert res["status"] == "no_paired_stratum"
    assert res["candidates"] == []


# ------------------------------------------------------------------ 결측·NULL

def test_wafer_without_history_excluded_from_denominator(tmp_path, monkeypatch):
    """이력 없는 wafer 를 '안 거침'으로 세면 결측이 신호로 둔갑한다."""
    t, c = ["T1", "T2", "T3"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]   # T3 이력 없음
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 2)    # 3 이 아니다
    assert ch["score"] == 1.0
    assert res["n_target"] == 2
    assert res["meta"]["missing_history"] == ["T3"]


def test_null_chamber_yields_equipment_level_only(tmp_path, monkeypatch):
    """ch_id 가 없으면 'ETCH9_None' 같은 가짜 챔버 키를 만들지 않는다."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Diff", "DIFF1", None) for w in t]
    hs += [_h(w, "Diff", "DIFF2", None) for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert _keys(res) == {("equipment", "DIFF1")}
    assert all(c_["ch_id"] is None for c_ in res["candidates"])


# ------------------------------------------------------------------ 층화

def test_counts_pooled_across_root_lots(tmp_path, monkeypatch):
    """EDS 확장으로 타깃이 두 root_lot 에 걸치면 stratum 별로 세고 합산한다."""
    ys = [_y(w, "AAAAA") for w in ["T1", "T2", "C1", "C2"]]
    ys += [_y(w, "BBBBB") for w in ["T3", "T4", "C3", "C4"]]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2", "T3", "T4"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C1", "C2", "C3", "C4"]]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(["T1", "T2", "T3", "T4"], ["C1", "C2", "C3", "C4"])
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (4, 4)
    assert (ch["control_pass"], ch["control_total"]) == (0, 4)
    assert ch["n_strata"] == 2
    assert {s["root_lot_id"] for s in res["strata"]} == {"AAAAA", "BBBBB"}


# ------------------------------------------------------------------ 정렬·절단

def test_larger_sample_ranks_first_on_score_tie(tmp_path, monkeypatch):
    """score 1.0 동점이면 표본이 큰 후보(4/4)가 작은 후보(2/2)보다 위로."""
    ys = [_y(w, "AAAAA") for w in ["T1", "T2", "C1", "C2"]]
    ys += [_y(w, "BBBBB") for w in ["T3", "T4", "C3", "C4"]]
    # Etch 는 두 stratum 모두에 존재 → 타깃 4장
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2", "T3", "T4"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C1", "C2", "C3", "C4"]]
    # CVD 는 stratum A 에만 존재 → 타깃 2장
    hs += [_h(w, "CVD", "CVD1", "1") for w in ["T1", "T2"]]
    hs += [_h(w, "CVD", "CVD2", "1") for w in ["C1", "C2"]]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(["T1", "T2", "T3", "T4"], ["C1", "C2", "C3", "C4"])
    etch = _find(res, "chamber", "ETCH9_3")
    cvd = _find(res, "chamber", "CVD1_1")
    assert etch["score"] == cvd["score"] == 1.0
    assert (etch["target_pass"], cvd["target_pass"]) == (4, 2)
    assert res["candidates"].index(etch) < res["candidates"].index(cvd)


def test_top_k_truncates_and_reports_remainder(tmp_path, monkeypatch):
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = []
    for i in range(4):                       # 후보 8개 (챔버 4 + 설비 4)
        hs += [_h(w, f"S{i}", f"EQ{i}", "1") for w in t]
        hs += [_h(w, f"S{i}", f"EQX{i}", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, top_k=3)
    assert len(res["candidates"]) == 3
    assert res["truncated"] == 5


# ------------------------------------------------------------------ 입구 방어·meta

def test_wafer_in_both_lists_counts_as_target_only(tmp_path, monkeypatch):
    """겹친 wafer 를 양쪽에 세면 score 가 부당하게 깎인다."""
    ys = [_y(w, "A45Z5") for w in ["T1", "T2", "C1"]]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]
    hs += [_h("C1", "Etch", "ETCH8", "1")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(["T1", "T2"], ["T2", "C1"])   # T2 중복
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 2)
    assert (ch["control_pass"], ch["control_total"]) == (0, 1)
    assert ch["score"] == 1.0


def test_eval_lot_kept_and_reported_in_meta(tmp_path, monkeypatch):
    """평가랏은 배제하지 않는다 — 설비 작업 후 검증랏이 섞여 단서가 될 수 있다."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t] + [_y("C1", "A45Z5"), _y("C2", "A45Z5", "eval")]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    ch = _find(res, "chamber", "ETCH9_3")
    assert ch["control_total"] == 2                       # 평가랏도 분모에 남는다
    assert res["meta"]["control_lot_types"] == {"prod": 1, "eval": 1}
    assert res["meta"]["target_lot_types"] == {"prod": 2}


def test_time_range_reported_for_confounding_check(tmp_path, monkeypatch):
    """시간 교락 진단 재료 — 두 그룹의 처리 시기를 그대로 실어 보낸다."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h("T1", "Etch", "ETCH9", "3", "2026-06-17 08:00:00"),
          _h("T2", "Etch", "ETCH9", "3", "2026-06-17 09:00:00"),
          _h("C1", "Etch", "ETCH8", "1", "2026-06-10 08:00:00"),
          _h("C2", "Etch", "ETCH8", "1", "2026-06-11 08:00:00")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert res["meta"]["target_time_range"] == {"min": "2026-06-17 08:00:00",
                                                "max": "2026-06-17 09:00:00"}
    assert res["meta"]["control_time_range"]["max"] == "2026-06-11 08:00:00"


def test_empty_input_is_insufficient_group(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch, [_y("C1", "A45Z5")], [])
    res = cm.find_commonality([], ["C1"])
    assert res["status"] == "insufficient_group"
    assert res["n_target"] == 0


# ------------------------------------------------------------------ legend 일반화

PPID_LEGEND = [{"level": "ppid", "columns": ["ppid"]}]


def _make_db_ppid(tmp_path, monkeypatch, yield_rows, history_rows):
    """step_history 에 ppid 컬럼을 포함한 픽스처. history_rows = (wid, step, eqp, ch, ppid, ts)."""
    import sqlite3
    db = tmp_path / "test_ppid.db"
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (
        wafer_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, yield REAL NOT NULL,
        defect_type TEXT NOT NULL, step_seq TEXT, date TEXT NOT NULL,
        root_lot_id TEXT NOT NULL, lot_type TEXT NOT NULL)""")
    conn.executemany("INSERT INTO yield VALUES (?,?,?,?,?,?,?,?)", yield_rows)
    conn.execute("""CREATE TABLE step_history (
        wafer_id TEXT NOT NULL, step_seq TEXT NOT NULL, eqp_id TEXT NOT NULL,
        ch_id TEXT, ppid TEXT, timestamp TEXT)""")
    conn.executemany("INSERT INTO step_history VALUES (?,?,?,?,?,?)", history_rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(ya_config, "DB_PATH", db)


def test_ppid_legend_finds_group_exclusive_ppid(tmp_path, monkeypatch):
    """PPID legend: 타깃 전원이 같은 PPID 를 거치고 대조군은 아닌 경우."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [(w, "Etch", "ETCH9", "3", "PPID_X", "2026-06-17 10:00:00") for w in t]
    hs += [(w, "Etch", "ETCH8", "1", "PPID_Y", "2026-06-17 10:00:00") for w in c]
    _make_db_ppid(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, legend=PPID_LEGEND)
    assert res["status"] == "ok"
    assert _keys(res) == {("ppid", "PPID_X")}
    cand = _find(res, "ppid", "PPID_X")
    assert cand["ppid"] == "PPID_X"
    assert (cand["target_pass"], cand["control_pass"]) == (2, 0)


def test_default_legend_matches_eqp_ch(tmp_path, monkeypatch):
    """legend 인자 없이 호출하면 EQP_CH 동작과 동일 (행동보존)."""
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    default = cm.find_commonality(t, c)
    explicit = cm.find_commonality(t, c, legend=cm.EQP_CH_LEGEND)
    assert _keys(default) == _keys(explicit) == {("equipment", "ETCH9"), ("chamber", "ETCH9_3")}


def test_unknown_legend_column_raises(tmp_path, monkeypatch):
    """legend 가 step_history 에 없는 컬럼을 요구하면 명시적 에러."""
    import pytest
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t + c]
    _make_db(tmp_path, monkeypatch, ys, hs)
    with pytest.raises(ValueError, match="bogus"):
        cm.find_commonality(t, c, legend=[{"level": "x", "columns": ["bogus"]}])