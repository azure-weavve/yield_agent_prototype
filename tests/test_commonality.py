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
    """양쪽 그룹이 똑같이 거친 설비는 후보가 아니다 (score <= 0).

    Etch 쪽도 후보가 아니다 — 대조군이 Etch 에 아무도 안 갔으므로 "Etch 에서 어느
    챔버를 썼나" 는 대비할 짝이 없다. 그 신호는 step_passage 축이 잡는다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "Etch", "ETCH9", "3") for w in t]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert ("chamber", "PHOTO1_1") not in _keys(res)
    assert ("chamber", "ETCH9_3") not in _keys(res)
    assert res["status"] == "no_signal"


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


# ------------------------------------------------------------------ 분모

def test_unequal_step_coverage_no_longer_fakes_a_signal(tmp_path, monkeypatch):
    """스텝 통과율이 그룹마다 다르면 챔버 신호가 없는데도 양의 score 가 나왔다.

    Etch 를 지난 wafer 중 ETCH9_3 을 쓴 비율은 타깃 2/4, 대조군 1/2 로 **똑같다**.
    챔버로는 아무것도 안 갈린다. 그런데 분모가 '이력이 있는 wafer' 면 대조군 분모가
    2 가 아니라 4 로 부풀려져 0.500 - 0.250 = 0.250 짜리 가짜 후보가 만들어졌다.
    """
    t = ["T1", "T2", "T3", "T4"]
    c = ["C1", "C2", "C3", "C4"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]   # 전원이 지나는 스텝
    hs += [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T3", "T4"]]
    hs += [_h("C1", "Etch", "ETCH9", "3"), _h("C2", "Etch", "ETCH8", "1")]
    # C3, C4 는 Etch 를 아예 안 지난다
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert ("chamber", "ETCH9_3") not in _keys(res)
    assert ("equipment", "ETCH9") not in _keys(res)
    assert res["status"] == "no_signal"


def test_step_denominator_counts_only_wafers_at_that_step(tmp_path, monkeypatch):
    """분모는 그 스텝에 간 wafer 만. 안 간 wafer 는 '다른 챔버를 썼다' 가 아니다."""
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]   # T3 는 Etch 안 감
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C1", "C2"]]   # C3 는 Etch 안 감
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 2)     # 3 이 아니다
    assert (ch["control_pass"], ch["control_total"]) == (0, 2)   # 3 이 아니다
    assert ch["score"] == 1.0
    # n_target 은 '이력이 있는 wafer' 그대로다 — 후보 분모와는 다른 개념이다
    assert res["n_target"] == 3


def test_missing_token_excluded_from_chamber_denominator_only(tmp_path, monkeypatch):
    """ch_id 가 '-' 면 챔버 질문에는 답할 수 없고 설비 질문에는 답할 수 있다."""
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h("T1", "Etch", "ETCH9", "3"), _h("T2", "Etch", "ETCH9", "3"),
          _h("T3", "Etch", "ETCH9", "-")]
    hs += [_h("C1", "Etch", "ETCH8", "1"), _h("C2", "Etch", "ETCH8", "1"),
           _h("C3", "Etch", "ETCH8", "-")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert (eq["target_pass"], eq["target_total"]) == (3, 3)     # T3 도 설비는 안다
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 2)     # T3 는 빠진다
    assert (ch["control_pass"], ch["control_total"]) == (0, 2)   # C3 도 빠진다
    assert ch["score"] == 1.0


def test_skip_equipment_stays_a_candidate(tmp_path, monkeypatch):
    """스킵이 'MSKPI1 + ch_id 없음' 으로 기록되면 설비 레벨이 그것을 잡는 유일한 자리다.

    이력 행이 있으므로 step_passage 는 '지났다' 로 센다. 설비 레벨에서 빼면
    이 스킵은 아무도 못 잡는다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "MSKPI1", "-") for w in t]      # 타깃은 스킵
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]      # 대조군은 정상 처리
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "MSKPI1")
    assert (eq["target_pass"], eq["target_total"]) == (2, 2)
    assert (eq["control_pass"], eq["control_total"]) == (0, 2)
    assert eq["score"] == 1.0
    assert ("chamber", "MSKPI1_-") not in _keys(res)   # 결측 토큰은 키를 안 만든다


STEP_PASSAGE_LEGEND = [{"level": "step_passage", "columns": ["step_seq"],
                        "denominator": "all"}]


def test_step_passage_denominator_is_the_whole_group(tmp_path, monkeypatch):
    """'그 스텝을 지났나' 는 모든 wafer 가 답할 수 있다.

    안 지난 wafer 를 분모에서 빼면 커버리지가 항상 1.0 이 되고 대조군 분모가 0 이라
    후보가 통째로 사라져, 이 축이 아무 일도 못 한다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Photo", "PHOTO1", "1") for w in t + c]
    hs += [_h(w, "IrregEC", "ETCH9", "3") for w in t]   # 타깃만 비정규 스텝
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, legend=STEP_PASSAGE_LEGEND)
    cand = _find(res, "step_passage", "IrregEC")
    assert (cand["target_pass"], cand["target_total"]) == (2, 2)
    assert (cand["control_pass"], cand["control_total"]) == (0, 2)
    assert cand["score"] == 1.0


def test_missing_token_on_eqp_id_also_excludes_equipment_denominator(tmp_path, monkeypatch):
    """현재 동작을 잠근다 — 확정된 설계가 아니라 사내 데이터 확인 대기 중인 자리다.

    설계가 결측 토큰으로 이름 댄 컬럼은 ch_id·ppid 뿐이다("스킵 정보는 사라지지
    않는다" — 스킵은 설비 레벨에 남아야 그 축이 잡는다). 그런데 "-" 판정은 legend 의
    모든 컬럼에 걸리므로, eqp_id 자체가 '-' 로 기록되는 스킵이 사내 데이터에 있다면
    그 wafer 는 설비 분모에서도 빠지고 step_passage 는 이력이 있으니 '지났다'로
    세어, 어느 축도 그 스킵을 못 잡는 사각지대가 생긴다. 사내 데이터로 확인하기
    전까지는 동작을 바꾸지 않고 지금 동작만 여기 잠가 둔다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]
    hs += [_h("T3", "Etch", "-", "3")]              # eqp_id 자체가 결측 토큰
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert (eq["target_pass"], eq["target_total"]) == (2, 2)   # T3 는 설비 분모에서도 빠진다


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