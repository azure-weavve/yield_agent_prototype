"""tools/commonality.py 검증 — 설비/챔버 공통성 분석.

step_history 는 ETL 선적재 대상이라 아직 더미 DB 에 없다.
따라서 모든 테스트가 임시 DB 를 만들어 config.DB_PATH 를 바꿔치기한다
(tests/test_yield_tools.py 의 _make_db 패턴과 동일).
"""

import itertools
import random
import sqlite3

import pytest

import ya_config
from tools import commonality as cm


# ------------------------------------------------------------------ 탐색 범위 노브

def test_search_scope_knobs_are_switchable_by_env():
    """탐색 범위 3종을 .env 로 바꿀 수 있어야 한다.

    예전에는 `getattr(ya_config, "COMMONALITY_TOP_K", 20)` 처럼 읽었는데 config 에
    그 이름이 **없어서** 항상 기본값으로 떨어졌다. 오타가 나도 조용히 동작하므로
    아무도 못 알아챘고, .env 에 값을 넣어도 안 먹는 상태가 유지됐다. 지금은 직접
    참조라 이름이 틀리면 AttributeError 로 즉시 걸린다 - 이 테스트는 그 위에
    "실제로 env 가 끝까지 흐르는가" 를 잠근다.

    별도 프로세스로 확인하는 이유는 test_eds_search.py 와 같다: `ya_config` 는
    import 시점에 env 를 읽으므로 이미 import 된 이 세션에서는 반영되지 않는다.
    """
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-c",
         "from tools import commonality as c; "
         "print(c.MIN_TARGET, c.TOP_K, c.MIN_SCORE)"],
        capture_output=True, cwd=root,
        env={**os.environ, "COMMONALITY_MIN_TARGET": "5",
             "COMMONALITY_TOP_K": "3", "COMMONALITY_MIN_SCORE": "0.25"})

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout.decode().split() == ["5", "3", "0.25"]


def test_collect_bits_changes_outputs_only_never_the_counts():
    """wafer 목록 누적 플래그가 2x2 카운트를 건드리면 안 된다.

    이 플래그는 순열 경로의 비용(실측 +22%)을 피하려고 둔 것이라, 관측은 켜고
    귀무는 끈 채로 돈다. 그래서 **켜고 끈 결과의 a/b/c/d 가 정확히 같아야** 한다 -
    다르면 귀무가 실제와 다른 것을 재게 되고, 순열 p 가 조용히 뜻을 잃는다.
    """
    from data.generate_dummy import MULTI_CONTROLS, MULTI_TARGETS

    targets = sorted(MULTI_TARGETS)
    controls = sorted(MULTI_CONTROLS)
    wafers_all = targets + controls
    bits = {w: 1 << i for i, w in enumerate(wafers_all)}
    legend = [{"level": "chamber", "columns": ["eqp_id", "ch_id"]}]

    with cm._conn() as conn:
        rows = cm._history(conn, wafers_all, legend)
    passed, answer, seen, _colmap = cm._build_index(rows, bits, legend)
    t_mask = 0
    for w in targets:
        t_mask |= bits[w]
    c_mask = 0
    for w in controls:
        c_mask |= bits[w]
    masks = [("M2423", t_mask, c_mask)]

    off, rep_off = cm._aggregate(masks, passed, answer, seen, set())
    on, rep_on = cm._aggregate(masks, passed, answer, seen, set(), collect_bits=True)

    assert rep_off == rep_on
    assert set(off) == set(on)
    # mh_num/mh_den/mh_scale(T5) — MH 가중 누적자(2026-09-17 R-B1 이후 정수쌍
    # 세 필드)도 플래그와 무관해야 한다. 셋 중 하나라도 빠뜨리면 그 필드로 새는
    # 훼손(M5 계열)이 이 테스트를 그냥 통과한다 - 예전에 mh_scale 을 안 넣어서
    # 실제로 그 자리가 비어 있었다(N-1 자리만 고치는 함정).
    counts = ("a", "b", "c", "d", "strata", "mh_num", "mh_den", "mh_scale")
    for key in off:
        assert {k: off[key][k] for k in counts} == {k: on[key][k] for k in counts}, key

    # 그리고 켠 쪽만 목록 재료를 들고 있다 — 길이는 카운트와 같다.
    assert cm._score_map(off) == cm._score_map(on)
    for key, e in on.items():
        assert e["a_bits"].bit_count() == e["a"]
        assert e["c_bits"].bit_count() == e["c"]
        assert "strata_detail" in e            # 켠 쪽만 층별 상세를 갖는다
    # 끈 쪽은 키 자체가 없다 — 귀무 경로의 dict 를 원래 크기로 두려는 의도적 형태다.
    assert all("a_bits" not in e and "c_bits" not in e for e in off.values())
    assert all("strata_detail" not in e for e in off.values())


def test_search_scope_defaults_match_config():
    """모듈 상수가 config 를 그대로 받는다 - 중간에 다른 기본값이 끼면 안 된다."""
    assert cm.MIN_TARGET == ya_config.COMMONALITY_MIN_TARGET
    assert cm.TOP_K == ya_config.COMMONALITY_TOP_K
    assert cm.MIN_SCORE == ya_config.COMMONALITY_MIN_SCORE
    assert cm.N_PERMUTATIONS == ya_config.COMMONALITY_PERMUTATIONS


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
    """스킵이 'MSKIP1 + ch_id 없음' 으로 기록되면 설비 레벨이 그것을 잡는 유일한 자리다.

    이력 행이 있으므로 step_passage 는 '지났다' 로 센다. 설비 레벨에서 빼면
    이 스킵은 아무도 못 잡는다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "MSKIP1", "-") for w in t]      # 타깃은 스킵
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]      # 대조군은 정상 처리
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "MSKIP1")
    assert (eq["target_pass"], eq["target_total"]) == (2, 2)
    assert (eq["control_pass"], eq["control_total"]) == (0, 2)
    assert eq["score"] == 1.0
    assert ("chamber", "MSKIP1_-") not in _keys(res)   # 결측 토큰은 키를 안 만든다


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
    """eqp_id 가 결측 토큰이면 설비 분모에서도 빠진다 — 현재 동작을 잠근다.

    "-" 판정은 legend 의 모든 컬럼에 걸리는데 설계가 결측 토큰으로 이름 댄 것은
    ch_id·ppid 뿐이다. **사내에서는 스킵을 MSKIP1 이라는 실제 설비 코드로 기록하기로
    약속돼 있어 eqp_id 에 "-" 가 들어오는 경우가 없다**(2026-08-09 확인). 그래서
    "스킵 정보는 사라지지 않는다"(설계 §354-366)가 깨지는 사각지대는 실데이터에 없다.

    그래도 이 테스트를 남기는 이유: 그 약속이 바뀌어 eqp_id 에 결측 토큰이 들어오면
    그 wafer 는 설비 분모에서 빠지는데 step_passage 는 이력이 있으니 '지났다'로 세어
    어느 축도 그 스킵을 못 잡는다. MISSING_TOKENS 를 손대는 사람이 그 대가를 여기서
    읽게 한다.
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


# ---------------------------------------------------- Mantel-Haenszel 가중 (pooling-mh-score)

def test_single_stratum_mh_score_matches_the_old_pooled_formula(tmp_path, monkeypatch):
    """T1 — stratum 이 하나면 새 MH 점수가 옛 pooled 식(a/nt - c/nc)과
    **대수적으로**(실수값으로) 같다 — `_score_map` 독스트링과 같은 표현이다.

    ⚠️ **"비트 단위로 같다" 가 아니다** — 2026-09-20 재리뷰(RR-M1)가 실측했다.
    정수 정확 산술(R-B1)을 거치면 값이 `(a·nc-c·nt)/(nt·nc)` 라
    `fl(a/nt) - fl(c/nc)` 와 **다른 double** 이 나온다(`nt,nc<=79` 전수의 51%).
    옛 값과 비트 단위로 같게 만드는 float 분기를 한때 넣었다가
    **되돌렸다**(동점 손실 — `_aggregate` 독스트링의 "RR-M4" 절).

    ⚠️ **`round(.,3)` 기준으로도 일반적으로 같지 않다**(2026-09-21 3차 리뷰
    TR-M3 — RR-M1 이 처음 지적한 것을 다시 정정한다). `nt,nc<=79` 전수에서
    반올림 후에도 갈리는 조합이 **5,528건**이다(예: `nt=3, a=1, nc=48, c=7` 에서
    `score 0.188` vs `score_pooled 0.187`). 아래 `ch["score_pooled"] ==
    ch["score"] == 0.417` 는 **성질이 아니라 이 픽스처(2/3, 1/4)의 우연**이다 —
    다른 수치를 넣으면 이 등식이 깨질 수 있다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3", "C4"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2"]]     # 타깃 2/3
    hs += [_h("T3", "Etch", "ETCH8", "1")]
    hs += [_h(w, "Etch", "ETCH9", "3") for w in ["C1"]]          # 대조군 1/4
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C2", "C3", "C4"]]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    ch = _find(res, "chamber", "ETCH9_3")
    assert (ch["target_pass"], ch["target_total"]) == (2, 3)
    assert (ch["control_pass"], ch["control_total"]) == (1, 4)
    # 옛 pooled 식: 2/3 - 1/4 = 0.41666... -> round(.,3) = 0.417
    assert ch["score"] == 0.417
    assert ch["n_strata"] == 1
    # ⚠️ 아래 등식은 "단일 stratum 이므로 pooled == MH" 라는 성질이 아니다
    # (TR-M3) — 반올림 경로가 다른 두 계산(정수 정확 나눗셈 한 번 vs 별도로
    # 반올림된 float 뺄셈)이 **이 특정 수치(2/3, 1/4)에서 우연히** 같은
    # 3자리 값을 냈을 뿐이다. 위 독스트링의 5,528건 반례가 그 증거다.
    assert ch["score_pooled"] == ch["score"] == 0.417


def test_pooled_equals_mh_when_all_strata_have_the_same_shape(tmp_path, monkeypatch):
    """T2 — 모든 stratum 의 (타깃 수, 대조군 수) 가 같으면(3/17, 3/17) 어떤 후보든
    pooled == MH 다 — **실수값으로는** 대수적 사실이다(2026-09-16 실측 1차, 후보
    18개 전부 차이 0.000). 가중치 w_i 가 stratum 마다 같아지므로 MH 가중평균이
    단순평균으로 무너지고, 그 단순평균이 실수값으로는 pooled 값과 같다.

    ⚠️ 이것도 **반올림 후까지** 항상 같다는 뜻은 아니다(TR-M3, 2026-09-21 3차
    리뷰 — T1 과 같은 문제). MH 는 정수 정확 나눗셈 한 번, pooled 는 별도로
    반올림된 float 뺄셈이라 반올림 경로가 다르다. 아래 `cand["score"] ==
    cand["score_pooled"]` 가 이 픽스처의 후보 전부에서 성립하는 것은 이 특정
    수치(3/17 조합)들이 우연히 일치했기 때문일 수 있다.
    """
    ta = [f"TA{i}" for i in range(1, 4)]
    ca = [f"CA{i}" for i in range(1, 18)]
    tb = [f"TB{i}" for i in range(1, 4)]
    cb = [f"CB{i}" for i in range(1, 18)]
    ys = [_y(w, "LOTA") for w in ta + ca] + [_y(w, "LOTB") for w in tb + cb]
    hs = []
    # stratum A: 타깃 2/3, 대조군 5/17 이 ETCH9
    hs += [_h(w, "Etch", "ETCH9", "1") for w in ta[:2]] + [_h(ta[2], "Etch", "ETCH8", "1")]
    hs += [_h(w, "Etch", "ETCH9", "1") for w in ca[:5]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ca[5:]]
    # stratum B: 타깃 1/3, 대조군 10/17 이 ETCH9 (비율이 A 와 다르다 — 그래도 크기는 같다)
    hs += [_h(tb[0], "Etch", "ETCH9", "1")] + [_h(w, "Etch", "ETCH8", "1") for w in tb[1:]]
    hs += [_h(w, "Etch", "ETCH9", "1") for w in cb[:10]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in cb[10:]]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(ta + tb, ca + cb)
    assert res["candidates"]                      # 검증할 후보가 있어야 한다
    for cand in res["candidates"]:
        assert cand["score"] == cand["score_pooled"], cand["key"]
        assert cand["n_strata"] == 2


def test_simpsons_paradox_fixture_flips_sign_between_pooled_and_mh(tmp_path, monkeypatch):
    """T3 — 심슨 픽스처(`docs/2026-09-16-pooling-전제-측정.md` 2차 실측 재현).

    LOT2405: 타깃 2/2 · 대조 18/18 (stratum 차 d=0.000)
    LOT2406: 타깃 1/4 · 대조 0/3   (stratum 차 d=+0.250)
    두 stratum 다 타깃이 불리하지 않은데(0.000, +0.250) **pooled 로 합치면 -0.357**
    로 뒤집힌다 - 교과서적 심슨의 역설. MH 가중은 +0.122 로 부호를 지킨다.
    """
    t2405, c2405 = ["T1", "T2"], [f"C{i}" for i in range(1, 19)]        # 대조 18장
    t2406, c2406 = ["T3", "T4", "T5", "T6"], ["D1", "D2", "D3"]         # 대조 3장
    ys = ([_y(w, "LOT2405") for w in t2405 + c2405]
          + [_y(w, "LOT2406") for w in t2406 + c2406])
    hs = []
    # LOT2405: 타깃 전원 + 대조군 전원 ETCH9 (d = 0.000)
    hs += [_h(w, "Etch", "ETCH9", "1") for w in t2405 + c2405]
    # LOT2406: 타깃 1/4 · 대조 0/3 이 ETCH9, 나머지는 다른 설비(분모용 이력)
    hs += [_h("T3", "Etch", "ETCH9", "1")]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T4", "T5", "T6"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2406]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t2405 + t2406, c2405 + c2406)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["n_strata"] == 2
    assert eq["score"] == 0.122          # MH 가중 — 양수, 부호를 지킨다
    assert eq["score_pooled"] == -0.357  # pooled — 음수로 뒤집힌다(심슨의 역설)
    assert eq["score"] > 0 and eq["score_pooled"] < 0
    by_root = {d["root_lot_id"]: d for d in eq["strata_detail"]}
    assert by_root["LOT2405"]["d"] == 0.0
    assert by_root["LOT2406"]["d"] == 0.25
    # FR-3/C1·C2(2026-09-21 4차 리뷰) — 층별 상세는 `d` 외에도 target/control
    # 의 pass/total 네 값을 싣는다(`_aggregate` 의 collect_bits 블록). 위 `d`
    # 만 잠그면 그 네 값이 조용히 틀려도 `d` 가 우연히 맞아떨어지는 훼손을
    # 놓친다 - stratum 마다 값으로 직접 잠근다.
    assert by_root["LOT2405"] == {
        "root_lot_id": "LOT2405", "target_pass": 2, "target_total": 2,
        "control_pass": 18, "control_total": 18, "d": 0.0}
    assert by_root["LOT2406"] == {
        "root_lot_id": "LOT2406", "target_pass": 1, "target_total": 4,
        "control_pass": 0, "control_total": 3, "d": 0.25}


def test_exact_stratum_cancellation_does_not_leak_a_near_zero_candidate(tmp_path, monkeypatch):
    """T10(R-M-a) — 층 간 상쇄로 참값이 **정확히 0** 인 후보는 절단을 통과하면 안 된다.

    stratum A(타깃 9/12·대조 2/3, `contrib`(=w·d)=+0.2 아니라 원 d=9/12-2/3≈0.083,
    w=2.4)와 stratum B(타깃 1/3·대조 3/7, `contrib`=-0.2 아니라 원
    d=1/3-3/7≈-0.095, w=2.1)를 골라 **가중 기여분(w·d) 자체가 +0.2/-0.2 로
    정확히 상쇄**되게 만들었다 — 정수쌍으로는 `term_n1*m2 + term_n2*m1 == 0`
    이지만 `1/3`·`2/3` 등이 이진 부동소수점으로 딱 안 떨어져 float 로 누적하면
    실제로 `+8.3e-17` 잔여가 남는다(직접 검증). 이 잔여가 `s > MIN_SCORE(0.0)` 를
    통과시켜 **`status: ok`(score 0.0 인 가짜 후보)로 뒤집히는 것을 이 픽스처로
    재현했다**(2026-09-17 리뷰, 2층 조합 7,572개가 이 상태였다고 실측). 정수
    정확 산술이면 분자가 정확히 정수 0 이라 절단에 걸려 후보 자체가 안 생긴다.
    """
    ta = [f"TA{i}" for i in range(1, 13)]     # 12장 — 9장이 TESTEQ
    ca = [f"CA{i}" for i in range(1, 4)]      # 3장 — 2장이 TESTEQ
    tb = [f"TB{i}" for i in range(1, 4)]      # 3장 — 1장이 TESTEQ
    cb = [f"CB{i}" for i in range(1, 8)]      # 7장 — 3장이 TESTEQ
    ys = [_y(w, "ROOTA") for w in ta + ca] + [_y(w, "ROOTB") for w in tb + cb]
    hs = []
    hs += [_h(w, "Etch", "TESTEQ") for w in ta[:9]] + [_h(w, "Etch", "OTHEREQ") for w in ta[9:]]
    hs += [_h(w, "Etch", "TESTEQ") for w in ca[:2]] + [_h(w, "Etch", "OTHEREQ") for w in ca[2:]]
    hs += [_h(w, "Etch", "TESTEQ") for w in tb[:1]] + [_h(w, "Etch", "OTHEREQ") for w in tb[1:]]
    hs += [_h(w, "Etch", "TESTEQ") for w in cb[:3]] + [_h(w, "Etch", "OTHEREQ") for w in cb[3:]]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(ta + tb, ca + cb)
    assert ("equipment", "TESTEQ") not in _keys(res)
    assert ("equipment", "OTHEREQ") not in _keys(res)     # 상쇄는 대칭이라 둘 다 0
    assert res["status"] == "no_signal"


def test_stratum_skip_excludes_strata_where_the_candidate_never_appears(tmp_path, monkeypatch):
    """RR-M5(2026-09-20 재리뷰, 사용자 결정: 문장만 좁히고 동작은 유지) — 후보가
    아예 나타나지 않은 stratum 은 MH 가중평균에서 통째로 빠진다
    (`_aggregate` 의 `a == 0 and c_ == 0` 스킵). pooled 시절에는 "분자·분모
    양쪽에서 대칭으로 뺀다" 로 옳았지만, 가중평균에서는 `d_i=0` 이고 `w_i>0`
    인 **정보 있는** stratum 을 평균에서 빼는 것이라 점수가 부풀 수 있다.

    stratum A(타깃 2/2 · 대조군 0/2 - 완전 분리, d=1.0)와 stratum B(타깃·
    대조군 전원이 다른 설비를 써서 이 후보가 아예 안 나타남)를 만든다. 지금
    동작은 B 를 빼고 A 만으로 score=1.0 을 낸다 - B 를 `d=0, w=6*6/12=3.0`
    으로 포함했다면(`w_A=2*2/4=1.0`) 가중평균은
    `(1.0*1.0 + 3.0*0.0)/(1.0+3.0) = 0.25` 로 내려갔을 것이다(수기 계산).
    이 테스트는 그 **현재 동작**(스킵 유지)을 잠근다 - 추정량을 고치는 것은
    이번 재리뷰의 사용자 결정으로 범위 밖이다.
    """
    ta, ca = ["TA1", "TA2"], ["CA1", "CA2"]
    tb = [f"TB{i}" for i in range(1, 7)]
    cb = [f"CB{i}" for i in range(1, 7)]
    ys = [_y(w, "AAAAA") for w in ta + ca] + [_y(w, "BBBBB") for w in tb + cb]
    hs = []
    # stratum A: 타깃 전원 SPECIAL, 대조군은 아무도 안 감(완전 분리, d=1.0)
    hs += [_h(w, "Etch", "SPECIAL", "1") for w in ta]
    hs += [_h(w, "Etch", "OTHEREQ", "1") for w in ca]
    # stratum B: 전원 OTHEREQ - SPECIAL 은 아예 안 나타난다(스킵 대상)
    hs += [_h(w, "Etch", "OTHEREQ", "1") for w in tb + cb]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(ta + tb, ca + cb)
    special = _find(res, "equipment", "SPECIAL")
    assert special["n_strata"] == 1          # stratum B 는 안 셈해진다(스킵)
    assert special["score"] == 1.0           # stratum A 만으로 낸 값

    # 참고용 수기 계산 — stratum B 를 포함했다면 나왔을 값과 다르다는 것을
    # 남겨 둔다(현재 동작이 이 값을 안 낸다는 것 자체가 잠기는 사실이다).
    w_a, w_b = 1.0, 3.0
    hypothetical_if_included = (w_a * 1.0 + w_b * 0.0) / (w_a + w_b)
    assert hypothetical_if_included == 0.25
    assert special["score"] != hypothetical_if_included


def test_mh_recurrence_is_exact_for_three_or_more_strata(tmp_path, monkeypatch):
    """M14(TR-M1, 2026-09-21 3차 리뷰) — MH 점화식(`_aggregate` 의 mh_num/mh_den/
    mh_scale 누적)이 S>=3 에서 잠겨 있지 않았다. `e["mh_scale"] = scale * m` 를
    `= m` 로 바꾸면(누적곱을 빼고 직전 stratum 의 m 만 남긴다) S<=2 에서는
    수학적 항등이라 T1~T3·T10 이 전부 그대로 통과하고, S>=3 인 관측 후보가
    78,078건 실재하는데도 그 훼손을 잡는 단언이 하나도 없었다.

    3개 stratum (3/4, 2/6)·(2/3, 0/6)·(1/4, 0/3) 의 정답 MH 값을 손으로 미리
    구했다(`w_i·d_i`·`w_i` 를 stratum 마다 계산해 합산):

        stratum1: term_n=3*6-2*4=10, term_d=4*6=24, m=10
        stratum2: term_n=2*6-0*3=12, term_d=3*6=18, m=9
        stratum3: term_n=1*3-0*4=3,  term_d=4*3=12, m=7
        Σ term_n/m = 1 + 4/3 + 3/7 = 58/21
        Σ term_d/m = 12/5 + 2 + 12/7 = 214/35
        score = (58/21)/(214/35) = 2030/4494 = 145/321 = 0.4517133...

    점화식으로 재현한 값(mh_num=1740, mh_den=3852 -> 1740/3852 = 145/321)과
    일치한다 — round(.,3) = **0.452**. 훼손판(`mh_scale=m`)으로 손으로 다시
    돌리면 mh_num=1497, mh_den=2880 -> **0.520**(판별선 0.5 를 **넘어 버린다** -
    "정답 MH 0.4517(미달) 인데 훼손값은 0.5198(통과)" 가 이 사례다). 두 값이
    3자리 반올림에서도 뚜렷이 갈리므로 이 하드코딩된 기대값이 훼손을 잡는다.
    """
    t1, c1 = ["T1", "T2", "T3", "T4"], [f"C{i}" for i in range(1, 7)]
    t2, c2 = ["T5", "T6", "T7"], [f"C{i}" for i in range(7, 13)]
    t3, c3 = ["T8", "T9", "T10", "T11"], [f"C{i}" for i in range(13, 16)]
    ys = ([_y(w, "ROOT1") for w in t1 + c1]
          + [_y(w, "ROOT2") for w in t2 + c2]
          + [_y(w, "ROOT3") for w in t3 + c3])
    hs = []
    # ROOT1: 타깃 3/4 · 대조군 2/6 이 ETCH9
    hs += [_h(w, "Etch", "ETCH9", "1") for w in ["T1", "T2", "T3"]]
    hs += [_h("T4", "Etch", "ETCH8", "1")]
    hs += [_h(w, "Etch", "ETCH9", "1") for w in ["C1", "C2"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C3", "C4", "C5", "C6"]]
    # ROOT2: 타깃 2/3 · 대조군 0/6 이 ETCH9
    hs += [_h(w, "Etch", "ETCH9", "1") for w in ["T5", "T6"]]
    hs += [_h("T7", "Etch", "ETCH8", "1")]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2]
    # ROOT3: 타깃 1/4 · 대조군 0/3 이 ETCH9
    hs += [_h("T8", "Etch", "ETCH9", "1")]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T9", "T10", "T11"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c3]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t1 + t2 + t3, c1 + c2 + c3, n_permutations=0)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["n_strata"] == 3
    assert (eq["target_pass"], eq["target_total"]) == (6, 11)      # 3+2+1, 4+3+4
    assert (eq["control_pass"], eq["control_total"]) == (2, 15)    # 2+0+0, 6+6+3
    assert eq["score"] == 0.452          # 145/321, round(.,3) — 판별선 0.5 미달
    assert eq["score"] < 0.5


def test_strata_detail_d_is_rounded_to_three_places(tmp_path, monkeypatch):
    """FR-8/C3(2026-09-21 4차 리뷰) — `strata_detail` 의 stratum 별 `d` 는
    **표시용**이라 3자리로 반올림한다(`_aggregate` 의 `collect_bits` 블록
    주석). 타깃 1/3 은 `0.3333...` 이라 반올림 없이 그대로 실리면 이 값과
    다르다 - 3자리 반올림이 실제로 일어나는지를 값으로 잠근다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h("T1", "Etch", "ETCH9", "3")]                 # 타깃 1/3
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T2", "T3"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]         # 대조군 0/7
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, n_permutations=0)
    ch = _find(res, "chamber", "ETCH9_3")
    assert ch["strata_detail"][0]["d"] == 0.333            # round(1/3 - 0/7, 3)
    assert ch["strata_detail"][0]["d"] != 1 / 3            # 반올림 안 하면 이 값이었다


def test_find_commonality_candidate_list_and_order_are_invariant_to_score_pooled(
        tmp_path, monkeypatch):
    """FR-2(2026-09-21 4차 리뷰, "도구 불변") — 이전 라운드는 자리마다 따로
    잠가서(TR-M4 의 `commonality.py:911` 훼손 등) 새 자리가 생길 때마다 뚫렸다.
    한 성질로 대신 잠근다: **`extra.score_pooled` 를 흔들어도 `find_commonality`
    의 후보 목록과 순서가 같다.**

    `score_pooled` 는 도구 내부에서 원시 2x2 로부터 파생되는 출력이라 외부
    입력처럼 직접 주입할 수 없다 - 대신 MH 점수(`score`)는 **똑같이 0.5 로
    묶이는데** `score_pooled` 는 **서로 다른 세 값**이 나오도록 stratum 모양을
    설계해 같은 효과를 낸다(심슨류 구성, T3 와 같은 기법). 후보가 `round(score,3)`
    으로 **동률**이 되도록 만들어 정렬의 **동점 깨기**(`-coverage_target`)와
    `top_k` 절단까지 같은 픽스처로 겨눈다.

    stratum 모양(타깃 2/대조 4, 타깃 6/대조 2)을 세 후보(EQA·EQB·EQC)가
    공유하되 어느 wafer 가 각 설비를 지났는지만 다르게 짜서:

        EQA(step S_A, 단층 - LOT2 에는 아예 안 나타남): score=0.5, score_pooled=0.5
        EQB(step S_B, 2층): score=0.5, score_pooled=0.292
        EQC(step S_C, 2층): score=0.5, score_pooled=0.708

    셋 다 `score` 가 0.500 으로 동률이라 실제 정렬은 둘째 키
    `-coverage_target`(EQC 0.875 > EQB 0.625 > EQA 0.5)로 갈린다 - **실제
    순서는 [EQC, EQB]** 이고 `top_k=2` 면 EQA 가 잘린다. `score_pooled` 를
    대신 읽는 훼손이라면 `-score_pooled` 로 정렬해 **[EQC, EQA]** 가 나오고
    EQB 가 잘렸을 것이다(0.708 > 0.5 > 0.292) - 두 정렬이 실제로 갈리는
    지점을 검산해 픽스처가 공허하지 않음을 확인했다.
    """
    t1, c1 = ["T1", "T2"], ["C1", "C2", "C3", "C4"]
    t2, c2 = ["T3", "T4", "T5", "T6", "T7", "T8"], ["D1", "D2"]
    ys = [_y(w, "LOT1") for w in t1 + c1] + [_y(w, "LOT2") for w in t2 + c2]
    hs = []
    # step S_A — LOT2 wafer 는 전혀 안 나온다 -> EQA 는 단층 후보다.
    hs += [_h("T1", "S_A", "EQA"), _h("T2", "S_A", "OTHERA")]
    hs += [_h(w, "S_A", "OTHERA") for w in c1]
    # step S_B — 두 stratum 모두. LOT1 타깃 2/2·대조 2/4, LOT2 타깃 3/6·대조 0/2.
    hs += [_h(w, "S_B", "EQB") for w in ["T1", "T2"]]
    hs += [_h("C1", "S_B", "EQB"), _h("C2", "S_B", "EQB")]
    hs += [_h("C3", "S_B", "OTHERB"), _h("C4", "S_B", "OTHERB")]
    hs += [_h(w, "S_B", "EQB") for w in ["T3", "T4", "T5"]]
    hs += [_h(w, "S_B", "OTHERB") for w in ["T6", "T7", "T8"]]
    hs += [_h(w, "S_B", "OTHERB") for w in ["D1", "D2"]]
    # step S_C — 두 stratum 모두. LOT1 타깃 1/2·대조 0/4, LOT2 타깃 6/6·대조 1/2.
    hs += [_h("T1", "S_C", "EQC"), _h("T2", "S_C", "OTHERC")]
    hs += [_h(w, "S_C", "OTHERC") for w in c1]
    hs += [_h(w, "S_C", "EQC") for w in t2]
    hs += [_h("D1", "S_C", "EQC"), _h("D2", "S_C", "OTHERC")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t1 + t2, c1 + c2, top_k=2, n_permutations=0)
    eqa = next((c for c in res["candidates"] if c["key"] == "EQA"), None)
    eqb = _find(res, "equipment", "EQB")
    eqc = _find(res, "equipment", "EQC")

    # 동률과 score_pooled 발산부터 검산한다 - 이게 안 맞으면 아래 순서 단언이
    # 공허해진다.
    assert eqb["score"] == eqc["score"] == 0.5
    assert (eqb["score_pooled"], eqc["score_pooled"]) == (0.292, 0.708)

    ranked = [c["key"] for c in res["candidates"] if c["level"] == "equipment"]
    assert ranked == ["EQC", "EQB"]                 # score 기준 순서 + top_k 절단
    assert eqa is None                               # score 기준이면 EQA 가 잘린다
    assert res["truncated"] == 1


def test_n_strata_matches_the_length_of_strata_detail(tmp_path, monkeypatch):
    """FR-4/C38(2026-09-21 4차 리뷰) — `n_strata` 는 `e["strata"]` 누적으로 세고
    `strata_detail` 은 `collect_bits` 로 별도 리스트에 모은다. 둘이 같은 값이 되는
    것은 **둘 다 `nt == 0 or nc == 0` 스킵을 통과한 stratum 만 세기** 때문이다.
    `e["strata"] += 1` 이 그 스킵 **앞**으로 옮겨지면 `n_strata` 만 부푼다.

    ⚠️ 그 훼손은 "후보가 그 stratum 에 나타났는데(`a` 또는 `c_` > 0) 한쪽이 그
    스텝에 답하지 못한" stratum 에서만 드러난다 - 그런 stratum 이 없으면 이 단언은
    공허하다(Claude main 실측 2026-09-21: 두 stratum 모두 대조군이 그 스텝을 지나던
    처음 픽스처에서는 이 훼손이 SURVIVED). 그래서 CCCCC 의 대조군은 Etch 를 아예
    안 거치게 둔다 - ETCH9_3 은 그 stratum 의 타깃 2장에 나타나지만(a=2) nc=0 이라
    건너뛴다.
    """
    ys = [_y(w, "AAAAA") for w in ["T1", "T2", "C1", "C2"]]
    ys += [_y(w, "BBBBB") for w in ["T3", "T4", "C3", "C4"]]
    ys += [_y(w, "CCCCC") for w in ["T5", "T6", "C5", "C6"]]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in ["T1", "T2", "T3", "T4", "T5", "T6"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["C1", "C2", "C3", "C4"]]
    # CCCCC 대조군은 Etch 를 안 거친다. 다른 이력은 있어야 stratum 자체가 성립한다.
    hs += [_h(w, "Depo", "DEPO1", "1") for w in ["C5", "C6"]]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(["T1", "T2", "T3", "T4", "T5", "T6"],
                              ["C1", "C2", "C3", "C4", "C5", "C6"])
    ch = _find(res, "chamber", "ETCH9_3")
    assert ch["n_strata"] == 2                      # CCCCC 는 nc=0 이라 세지 않는다
    assert ch["n_strata"] == len(ch["strata_detail"])
    assert {d["root_lot_id"] for d in ch["strata_detail"]} == {"AAAAA", "BBBBB"}


def test_candidate_ranking_uses_score_not_score_pooled(tmp_path, monkeypatch):
    """TR-M4(e, 2026-09-21 3차 리뷰) — `commonality.py:911` 의 후보 정렬 키가
    score 대신 score_pooled 를 쓰는 훼손이 SURVIVED 했다. 정렬은 바로 뒤
    `candidates[:top_k]` 절단으로 이어져 **후보의 존재 여부 자체**를 정하는
    판정 자리인데, 잠그는 단언이 없었다.

    후보 A(심슨 픽스처, score=0.122·score_pooled=-0.357, 다층)와 후보
    B(단층, score=score_pooled=0.1)를 함께 넣는다. score 로 정렬하면 A 가
    1등(0.122 > 0.1)인데, score_pooled 로 정렬했다면 B 가 1등이었을 것이다
    (0.1 > -0.357) - 두 정렬이 실제로 갈리는 값을 골랐다.
    """
    t2405, c2405 = ["T1", "T2"], [f"C{i}" for i in range(1, 19)]
    t2406, c2406 = ["T3", "T4", "T5", "T6"], ["D1", "D2", "D3"]
    tb = [f"TB{i}" for i in range(1, 11)]
    cb = [f"CB{i}" for i in range(1, 11)]
    ys = ([_y(w, "LOT2405") for w in t2405 + c2405]
          + [_y(w, "LOT2406") for w in t2406 + c2406]
          + [_y(w, "LOT9") for w in tb + cb])
    hs = []
    # 후보 A(equipment, ETCH9) — T3 심슨 픽스처 그대로
    hs += [_h(w, "Etch", "ETCH9", "1") for w in t2405 + c2405]
    hs += [_h("T3", "Etch", "ETCH9", "1")]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T4", "T5", "T6"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2406]
    # 후보 B(equipment, DEPOX) — 단층, 타깃 1/10 · 대조군 0/10
    hs += [_h("TB1", "Depo", "DEPOX", "1")]
    hs += [_h(w, "Depo", "OTHERDEPO", "1") for w in tb[1:]]
    hs += [_h(w, "Depo", "OTHERDEPO", "1") for w in cb]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t2405 + t2406 + tb, c2405 + c2406 + cb, n_permutations=0)
    a = _find(res, "equipment", "ETCH9")
    b = _find(res, "equipment", "DEPOX")
    assert (a["score"], a["score_pooled"]) == (0.122, -0.357)
    assert (b["score"], b["score_pooled"]) == (0.1, 0.1)
    # score 기준: A(0.122)가 B(0.1)를 이긴다. score_pooled 였다면 B(0.1)가
    # A(-0.357)를 이겼을 것 — 그 반대 결과를 이 순서 단언이 잡는다.
    ranked = [c["key"] for c in res["candidates"] if c["level"] == "equipment"]
    assert ranked.index("ETCH9") < ranked.index("DEPOX")


def test_score_map_does_not_round(tmp_path, monkeypatch):
    """tm4(2026-09-21 3차 리뷰) — `_score_map` 독스트링의 "반올림하지 않는다"
    계약이 안 잠겨 있었다. 나눗셈 결과를 `round(...,3)` 으로 미리 반올림해도
    스위트가 그대로 통과했다 - 귀무와 관측이 절단(`s > MIN_SCORE`)을 반올림
    전 정밀도로 공유해야 한다는 계약(설계 §1-4)이 이 자리에서 안 지켜져도
    아무것도 안 걸렸다는 뜻이다.
    """
    agg = {("k",): {"mh_num": 1, "mh_den": 3}}     # 1/3 = 0.3333... (3자리와 다르다)
    out = cm._score_map(agg)
    assert out[("k",)] == 1 / 3
    assert out[("k",)] != round(1 / 3, 3)


def test_null_distribution_shares_the_score_function_with_the_observed_path(
        tmp_path, monkeypatch):
    """T4 — 관측과 귀무가 `_score_map` 한 함수를 같이 탄다(설계 §1-4, D1/D3).

    `_score_map` 을 감시용 래퍼로 바꿔치기해 실측한다: 관측 1회 + 순열 회차만큼
    불려야 하고, 매 호출의 agg 항목이 mh_num/mh_den 을 갖고 있어야 한다.

    ⚠️ **정정(R-B2, 2026-09-17 리뷰)** — 이 호출 횟수·키 존재 검사는 "귀무만
    옛 pooled 로 갈아치우는 분기(M3b)" 를 **잡지 못한다**(625건 SURVIVED 로
    실측됨). `_score_map` 안에서 `"strata_detail" in e` 로 갈라도 호출은 여전히
    한 번씩 일어나고 agg 항목에는 mh_num/mh_den 키가 그대로 있기 때문이다 -
    이 테스트는 "같은 함수를 호출한다" 만 잠그고 "그 함수가 같은 값을 낸다" 는
    잠그지 못한다. 값으로 잠그는 것은 바로 아래
    `test_score_map_gives_the_identical_value_regardless_of_collect_bits` 다.
    """
    t2405, c2405 = ["T1", "T2"], [f"C{i}" for i in range(1, 19)]
    t2406, c2406 = ["T3", "T4", "T5", "T6"], ["D1", "D2", "D3"]
    ys = ([_y(w, "LOT2405") for w in t2405 + c2405]
          + [_y(w, "LOT2406") for w in t2406 + c2406])
    hs = [_h(w, "Etch", "ETCH9", "1") for w in t2405 + c2405]
    hs += [_h("T3", "Etch", "ETCH9", "1")]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T4", "T5", "T6"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2406]
    _make_db(tmp_path, monkeypatch, ys, hs)

    calls = []
    real_score_map = cm._score_map

    def _spy(agg):
        calls.append(agg)
        return real_score_map(agg)

    monkeypatch.setattr(cm, "_score_map", _spy)
    res = cm.find_commonality(t2405 + t2406, c2405 + c2406, n_permutations=50)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["p_permutation"] is not None            # 순열이 실제로 돌았다

    # 1회(관측) + 순열 회차만큼(전수 열거면 더 적을 수 있으나 최소 관측보다는 많다)
    assert len(calls) > 1
    assert all("mh_num" in e and "mh_den" in e for agg in calls for e in agg.values())


def test_score_map_gives_the_identical_value_regardless_of_collect_bits(tmp_path, monkeypatch):
    """T4(R-B2 보강) — "같은 함수" 를 **값으로** 확인한다.

    2026-09-17 리뷰: 위 호출-횟수 테스트는 `_score_map` 내부에서
    `"strata_detail" in e` 로 갈라 **귀무만 옛 pooled 를 쓰게 하는 훼손(M3b)** 을
    못 잡았다(625건 전부 SURVIVED). 원인은 기존 `test_collect_bits_changes_
    outputs_only_never_the_counts` 의 픽스처가 stratum 1개라 pooled == MH 로
    우연히 같았기 때문이다 - **층 모양이 달라 pooled != MH 인** 심슨 픽스처로
    collect_bits on/off(= 관측 모양 vs 귀무 모양)의 `_score_map` 결과가 **값으로**
    같아야 하고, 그 값이 실제로 MH(0.122)여야 한다(우연한 일치가 아님을 증명).
    """
    t2405, c2405 = ["T1", "T2"], [f"C{i}" for i in range(1, 19)]
    t2406, c2406 = ["T3", "T4", "T5", "T6"], ["D1", "D2", "D3"]
    ys = ([_y(w, "LOT2405") for w in t2405 + c2405]
          + [_y(w, "LOT2406") for w in t2406 + c2406])
    hs = [_h(w, "Etch", "ETCH9", "1") for w in t2405 + c2405]
    hs += [_h("T3", "Etch", "ETCH9", "1")]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in ["T4", "T5", "T6"]]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2406]
    _make_db(tmp_path, monkeypatch, ys, hs)

    wafers_all = t2405 + t2406 + c2405 + c2406
    bits = {w: 1 << i for i, w in enumerate(wafers_all)}
    with cm._conn() as conn:
        rows = cm._history(conn, wafers_all, cm.EQP_CH_LEGEND)
    passed, answer, seen, _colmap = cm._build_index(rows, bits, cm.EQP_CH_LEGEND)

    def _mask(wafers):
        m = 0
        for w in wafers:
            m |= bits[w]
        return m

    masks = [("LOT2405", _mask(t2405), _mask(c2405)),
             ("LOT2406", _mask(t2406), _mask(c2406))]
    off, _ = cm._aggregate(masks, passed, answer, seen, set())
    on, _ = cm._aggregate(masks, passed, answer, seen, set(), collect_bits=True)

    key = ("equipment", "Etch", "ETCH9")
    assert "strata_detail" not in off[key]      # 귀무 경로의 모양(off)
    assert "strata_detail" in on[key]           # 관측 경로의 모양(on)
    scores_off, scores_on = cm._score_map(off), cm._score_map(on)
    assert scores_off == scores_on              # 모양이 달라도 같은 함수 = 같은 값
    assert round(scores_off[key], 3) == round(scores_on[key], 3) == 0.122
    assert round(scores_off[key], 3) != -0.357  # pooled 로 조용히 안 갈아탔다


def test_score_map_gives_the_identical_value_for_equivalent_integer_fractions():
    """M11(RR-M2, 2026-09-20 재리뷰) — 같은 유리수를 다른 (분자, 분모) 쌍으로
    나타내도 `_score_map` 이 비트 단위로 같은 값을 내야 한다.

    `float(e["mh_num"]) / float(e["mh_den"])` 로 미리 float 변환하는 훼손은
    참값 0 도 T3(심슨 픽스처)도 그냥 통과해 버렸다(재리뷰 실측 - 631 passed 로
    SURVIVED). 정수 그대로 파이썬 `int / int` 나눗셈을 쓰는 것만이 "같은
    유리수는 항상 같은 double" 을 보장한다 - 누적자가 2^53 을 넘으면(m≈30 에서
    stratum 11개) 같은 유리수의 다른 (num, den) 표현이 실제로 다른 double 이
    될 수 있다. 아래 숫자는 무작위 탐색으로 찾은 실제 반례다 - `float` 로
    먼저 변환해 나누면 두 표현이 갈린다(마지막 단언이 그 사실 자체를 확인한다).
    """
    num, den, k = 853513164, 911666163, 844721699730106015
    small = {("k",): {"mh_num": num, "mh_den": den}}
    scaled = {("k",): {"mh_num": num * k, "mh_den": den * k}}
    out_small = cm._score_map(small)
    out_scaled = cm._score_map(scaled)
    assert out_small[("k",)] == out_scaled[("k",)]
    # 이 반례가 실제로 float 변환에서 갈린다는 것도 함께 확인해 둔다 - 안 그러면
    # "우연히 두 표현이 뭘 해도 같다" 는 반례를 못 배제한다.
    assert float(num * k) / float(den * k) != out_small[("k",)]


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


# --------------------------------------------------------------- 순열검정

def test_permutation_p_is_deterministic(tmp_path, monkeypatch):
    """같은 입력이 같은 p 를 내야 한다 — 시드가 고정돼 있다.

    감사 기록에 실리는 값이라 실행마다 흔들리면 안 된다. 3대3(n_total=20)은
    기본 상한(10000) 아래라 그냥 두면 전수 열거 경로로 가서 rng 를 한 번도 안
    쓴다 — 그건 "열거는 열거다"라는 동어반복만 검증한다. 무작위 표본 경로를
    강제해야 고정 시드 제약을 실제로 잠글 수 있다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)
    monkeypatch.setattr(cm, "PERM_EXHAUSTIVE_MAX", 10)      # 무작위 표본 경로로 강제

    first = cm.find_commonality(t, c)
    second = cm.find_commonality(t, c)
    assert [x["p_permutation"] for x in first["candidates"]] == \
           [x["p_permutation"] for x in second["candidates"]]


def test_small_group_cannot_reach_a_small_p(tmp_path, monkeypatch):
    """2대2 는 완전 분리여도 p 를 0.167 아래로 못 내린다 — 공간이 없다.

    4장 중 2장을 타깃으로 고르는 경우의 수가 6이고 관측 라벨을 빼면 5회다.
    p 는 아무리 좋아도 1/(5+1) = 0.167 이다. 이것이 "2대2 의 score 1.0" 이
    확신이 아니라는 것을 숫자로 말하는 자리다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["score"] == 1.0                      # 완전 분리인데도
    assert eq["n_permutations_total"] == 6
    assert eq["p_min_possible"] == 0.1667
    assert eq["p_permutation"] == 0.1667           # 최소값에 닿았다 = 귀무가 못 넘었다


def test_larger_group_with_the_same_separation_gets_a_much_smaller_p(tmp_path, monkeypatch):
    """같은 score 1.0 이라도 표본이 크면 p 가 훨씬 작다 — 이것이 순열검정의 일이다.

    6대6 은 경우의 수가 924 라 p 가 0.001 수준까지 내려간다. score 만 보면
    2대2 와 6대6 이 똑같이 1.0 인데, p 가 그 둘을 갈라놓는다.
    """
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["score"] == 1.0
    assert eq["n_permutations_total"] == 924
    assert eq["p_permutation"] < 0.01


def test_shuffling_keeps_each_lot_target_count(tmp_path, monkeypatch):
    """섞기는 root_lot 안에서만 한다 — lot 별 타깃 수가 회차마다 그대로여야 한다.

    lot 을 가로질러 섞으면 lot 효과가 신호로 잡힌다(설계 §2-2). 그 방어가
    실제로 작동하는지는 여기서만 볼 수 있다 - 결과 dict 에는 안 드러난다.
    전수 열거·무작위 표본 두 경로 모두에서 확인한다 — 이 strata 는 경우의 수가
    작아(9) 기본 상한이면 전수 경로만 타는데, 실데이터가 실제로 타는 경로는
    표본 쪽이라 그쪽의 stratum 보존도 따로 잠가야 한다.
    """
    # lot A: 타깃 2 대조군 1,  lot B: 타깃 1 대조군 2
    strata = [("A", 0b000011, 0b000100), ("B", 0b001000, 0b110000)]
    seen = 0
    for _rl, t, c in strata:
        seen |= t | c                      # 이 테스트는 전원이 이력 있다고 가정
    n_total = cm._n_permutations_total(strata, seen)

    for perm_exhaustive_max in (10000, 2):     # 전수 열거 경로, 무작위 표본 경로
        monkeypatch.setattr(cm, "PERM_EXHAUSTIVE_MAX", perm_exhaustive_max)
        rng = random.Random(0)
        seen_any = False
        for labels in cm._iter_label_sets(strata, n_total, 50, rng, seen):
            seen_any = True
            for (rl, t, c), (_rl0, t0, c0) in zip(labels, strata):
                assert t.bit_count() == t0.bit_count()      # 타깃 수 보존
                assert t | c == t0 | c0                     # 같은 wafer 풀
                assert t & c == 0                           # 겹치지 않는다
        assert seen_any


def test_observed_labeling_is_not_part_of_the_null(tmp_path, monkeypatch):
    """전수 열거에서 관측 라벨을 뺀다 — 안 빼면 최소 p 에 절대 못 닿는다.

    관측은 자기 자신 이상이므로 귀무에 넣으면 '넘은 횟수' 가 늘 1 이상이 되고,
    p_min_possible 이 달성 불가능한 값이 되어 공간 부족을 읽을 수 없게 된다.
    """
    rng = random.Random(0)
    strata = [("A", 0b0011, 0b1100)]                    # 타깃 2 대조군 2 -> 6가지
    seen = 0b1111                                       # 이 테스트는 전원이 이력 있다고 가정
    n_total = cm._n_permutations_total(strata, seen)
    assert n_total == 6
    label_sets = list(cm._iter_label_sets(strata, n_total, 0, rng, seen))
    assert len(label_sets) == 5                         # 관측 하나가 빠졌다
    assert all(labels[0][1] != 0b0011 for labels in label_sets)


def test_note_warns_against_recomputing_score_from_coverage(tmp_path, monkeypatch):
    """m5(2026-09-17 리뷰) — `note` 가 coverage_target/coverage_control 로 score 를
    재계산하지 말라고 명시해야 한다. 이 둘은 score 바로 옆에 나란히 실리는 숫자라
    "차를 내면 score" 로 착각하기 **가장 쉬운 재료**다(target_pass/target_total
    보다도 직접적이다) - stratum 이 여럿이면 그 차는 이제 score(MH 가중)와 다르다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert "coverage_target" in res["note"] and "coverage_control" in res["note"]
    assert "다시 계산해 score 대신 쓰지 마라" in res["note"]


def test_note_also_warns_against_averaging_strata_detail(tmp_path, monkeypatch):
    """rm9(2026-09-20 재리뷰) — `strata_detail` 의 stratum 별 `d` 는
    coverage_target/control 보다도 score 계산 재료에 더 가깝다(이미 stratum
    별로 나뉜 위험차다). 재계산 금지 문장이 coverage_*·target_pass/total 만
    막으면 이 필드로 새는 재계산(단순 평균)은 안 걸린다 - stratum 마다
    가중치가 달라 단순 평균은 MH 가중평균과 다르다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    assert "strata_detail" in res["note"]
    assert "단순 평균" in res["note"]


def test_permutation_can_be_turned_off(tmp_path, monkeypatch):
    """n_permutations=0 이면 순열을 아예 안 돌리고 키도 안 생긴다.

    비용이 드는 계산이라 끌 수 있어야 하고, 껐을 때 결과는 순열 도입 전과 같아야
    한다 - 껐다 켜는 것이 다른 답을 내면 둘 중 하나는 틀린 것이다.
    """
    t, c = ["T1", "T2", "T3"], ["C1", "C2", "C3"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    off = cm.find_commonality(t, c, n_permutations=0)
    on = cm.find_commonality(t, c)
    assert "p_permutation" not in off["candidates"][0]
    assert "p_permutation" in on["candidates"][0]
    # note 도 같이 꺼져야 한다 - 없는 필드를 읽으라고 하면 LLM 은 지어낸다
    assert "p_permutation" not in off["note"]
    assert "p_min_possible" not in off["note"]
    assert "p_permutation" in on["note"]
    # 순열이 얹는 필드 전부. 새 필드를 여기 안 넣으면 아래 단언이 그 필드 때문에
    # 깨지는데, 그건 "후보가 바뀌었다" 가 아니라 목록이 낡은 것이다.
    perm_fields = ("p_permutation", "p_min_possible", "p_at_floor",
                   "n_permutations_total", "n_reference")
    strip = lambda r: [{k: v for k, v in x.items() if k not in perm_fields}
                       for x in r["candidates"]]
    assert strip(off) == strip(on)          # 순열은 후보 자체를 바꾸지 않는다


def test_enumeration_and_sampling_agree(tmp_path, monkeypatch):
    """전수 열거와 무작위 표본이 같은 결론을 내야 한다 (설계 검증 목록).

    같은 데이터를 두 경로로 돌린다. 6대6 은 경우의 수가 924 라 기본값이면 전수
    열거를 타는데, 열거 상한을 낮춰 무작위 표본 경로로 강제한다. 두 p 가 크게
    벌어지면 둘 중 하나가 틀린 것이다 - 표본이 편향됐거나 열거가 빠뜨렸거나다.

    두 값의 차이만 재면 안 된다. 완전 분리라 두 p 가 바닥 근처에 붙어 있어 차이가
    작고, 그러면 허용오차 0.01 은 어떤 회귀도 못 잡는다. 그래서 경로마다 **성질**을
    따로 못 박는다 - 전수는 바닥에 닿고(`p_at_floor`), 표본은 관측 라벨이 참조집합에
    남아 바닥에 못 닿으며 그 바닥은 회차 예산이 정한다. p 값 자체는 난수열에
    딸린 숫자라 잠그지 않는다.
    """
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    exhaustive = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert exhaustive["n_permutations_total"] == 924        # 전수 경로였다
    # 923회(관측 제외) 중 관측을 넘은 것이 0 → p = 1/924
    assert exhaustive["p_permutation"] == 0.0011
    assert exhaustive["p_at_floor"] is True                 # 귀무가 한 번도 못 넘었다

    monkeypatch.setattr(cm, "PERM_EXHAUSTIVE_MAX", 10)      # 무작위 표본으로 강제
    sampled = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert sampled["n_permutations_total"] == 924           # 경우의 수는 그대로 보고
    # 표본 경로는 관측 라벨을 빼지 않는다 - 924가지에서 1000번 뽑으므로 관측과
    # 같은 라벨이 다시 나오고, 그것이 "관측 이상" 으로 세어진다. 그래서 완전
    # 분리인데도 표본 경로의 p 는 자기 바닥에 닿지 못한다. **뽑힌 횟수(그래서
    # p 값 자체)는 난수열이 바뀌면 달라진다** - 여기서 잠그는 것은 그 숫자가
    # 아니라 "바닥에 못 닿는다" 는 성질이고, 그 원인은 아래
    # `test_only_the_exhaustive_branch_drops_the_observed_labelling` 이 잠근다.
    assert sampled["p_at_floor"] is False
    assert sampled["p_permutation"] > sampled["p_min_possible"]
    assert sampled["p_min_possible"] == 0.001               # 1/(1000+1) - 계산 예산이 정한다
    # 그럼에도 결론은 같아야 한다: 둘 다 "귀무는 이만한 분리를 거의 못 만든다"
    assert abs(sampled["p_permutation"] - exhaustive["p_permutation"]) < 0.01


def test_only_the_exhaustive_branch_drops_the_observed_labelling():
    """두 경로의 p 가 갈리는 **원인**을 직접 잰다.

    전수 열거는 관측 라벨을 건너뛴다 - 안 그러면 "넘은 횟수" 가 늘 1 이상이 되어
    p 가 자기 바닥에 절대 못 닿고, 그러면 p_min_possible 로 공간 부족을 읽는
    계약이 죽는다. 표본 추출은 반대로 관측 라벨을 다시 뽑을 수 있고, 그것이 위
    `test_enumeration_and_sampling_agree` 에서 표본 경로의 p 가 바닥보다 큰 이유다.

    이 성질을 **여기서** 재는 이유: 위 테스트는 열거 상한을 10 으로 낮춰야
    표본 경로를 타는데, 프로덕션 상한은 10,000 이라 6대6(924가지)은 언제나 전수
    경로다. 즉 그쪽 p 값은 프로덕션에서 나올 수 없는 배치의 산물이다. 원인을
    직접 재면 그 배치에 기대지 않는다.
    """
    masks = [("L1", 0b0011, 0b1100)]                        # 타깃 2 · 대조군 2 = 6가지
    seen = 0b1111
    observed_t = 0b0011

    exhaustive = list(cm._iter_label_sets(masks, 6, 1000, random.Random(0), seen))
    assert len(exhaustive) == 5                             # 6가지 중 관측을 뺐다
    assert all(labels[0][1] != observed_t for labels in exhaustive)

    # n_total 이 PERM_EXHAUSTIVE_MAX 를 넘으면 표본 분기다. 회차 수만큼 뽑으므로
    # 6가지밖에 없는 여기서는 관측 라벨이 반드시 다시 나온다.
    sampled = list(cm._iter_label_sets(masks, 10 ** 6, 50, random.Random(0), seen))
    assert len(sampled) == 50
    assert any(labels[0][1] == observed_t for labels in sampled)


def test_the_note_blames_the_reference_rounds_not_the_sample_for_a_big_floor(
        tmp_path, monkeypatch):
    """바닥값을 정하는 것은 **참조 회차**다 - 표본 크기가 아니다.

    10대10 은 섞을 배치가 184,756 가지나 되는데도 순열 회차를 5로 주면 바닥이
    0.1667 이 된다. 표본이 작아서가 아니라 **예산이 작아서**다. note 가 "표본이
    작아" 라고 말하면 엔지니어는 늘릴 수 없는 wafer 를 더 모으러 가고, 정작
    고칠 수 있는 노브(COMMONALITY_PERMUTATIONS)는 건드리지 않는다.
    """
    t = [f"T{i}" for i in range(1, 11)]
    c = [f"C{i}" for i in range(1, 11)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c, n_permutations=5)
    eq = _find(res, "equipment", "ETCH9")
    assert eq["n_permutations_total"] == 184756      # 표본은 전혀 작지 않다
    assert eq["n_reference"] == 5                    # 예산이 정한 참조 회차
    assert eq["p_min_possible"] == 0.1667
    # note 첫머리의 "표본이 작아 우연한 분리가 흔하다" 는 별개의 참인 문장이라
    # 건드리지 않는다. 여기서 막는 것은 **바닥값의 원인**을 표본 탓으로 적는 것뿐이다.
    assert "표본이 작아 p" not in res["note"]
    assert "참조 회차가 적어" in res["note"]


# -------------------------------------------------------------------- FDR

def _noise_db(tmp_path, monkeypatch, n_steps=10):
    """신호가 없는데 후보는 많이 나오는 데이터.

    6장을 3장씩 나누는 방법이 20가지인데, 스텝마다 서로 다른 3장 조합이 ETCH9 를
    쓰게 한다. 어느 스텝 하나는 우연히 타깃과 정확히 일치해 score 1.0 이 된다.
    실제 원인은 없고 '많이 시도했다' 는 것뿐이다 - FDR 이 잡아야 하는 상황이다.
    """
    wafers = ["T1", "T2", "T3", "C1", "C2", "C3"]
    subsets = list(itertools.combinations(wafers, 3))[:n_steps]
    ys = [_y(w, "A45Z5") for w in wafers]
    hs = []
    for i, sub in enumerate(subsets):
        for w in wafers:
            eqp = "ETCH9" if w in sub else "ETCH8"
            hs.append(_h(w, f"S{i:02d}", eqp, "1"))
    _make_db(tmp_path, monkeypatch, ys, hs)
    return ["T1", "T2", "T3"], ["C1", "C2", "C3"]


def test_fdr_table_has_the_expected_shape(tmp_path, monkeypatch):
    """표의 각 행은 임계·실제 개수·귀무 평균·추정 가짜 비율·회차 수를 담는다.

    `n_used` 가 필요한 이유: 소표본에서 `n_null_mean` 이 양자화된다. 19회를
    돌리면 귀무 평균이 0/19, 1/19, 2/19 ... 값만 가질 수 있으므로, 회차 수를
    모르면 0.053 이 "거의 안 나온다" 인지 "19회 중 1회 = 이 표본의 바닥" 인지
    구분할 수 없다. 후보별 p 에 `p_min_possible` 을 함께 싣는 것과 같은 이유다.
    """
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    assert res["fdr_table"]
    for row in res["fdr_table"]:
        assert set(row) == {"threshold", "n_observed", "n_null_mean", "fdr", "n_used"}
        assert row["n_observed"] > 0
        assert 0.0 <= row["fdr"] <= 1.0
        assert row["n_used"] == 19          # 3대3 = 20가지, 관측 제외 19회
    thresholds = [r["threshold"] for r in res["fdr_table"]]
    assert thresholds == sorted(thresholds, reverse=True)


def test_pure_noise_gets_a_high_fdr(tmp_path, monkeypatch):
    """많이 시도해서 얻은 score 1.0 은 귀무에서도 그만큼 나온다.

    원인이 없는데 후보가 나온 상황이다. 표가 "이 목록은 거의 다 가짜" 라고
    말해야 한다 - 이걸 못 하면 FDR 을 넣은 의미가 없다.
    """
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    top = res["fdr_table"][0]
    assert top["threshold"] == 0.9
    assert top["n_observed"] >= 1
    assert top["fdr"] >= 0.5


def test_real_signal_in_a_large_group_gets_a_low_fdr(tmp_path, monkeypatch):
    """진짜 신호는 귀무가 못 따라온다. 대조군이다."""
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(t, c)
    top = res["fdr_table"][0]
    assert top["threshold"] == 0.9
    assert top["fdr"] < 0.05


def test_family_wise_p_is_carried(tmp_path, monkeypatch):
    """1등이 우연일 확률. 잡음에서는 크고 진짜 신호에서는 작아야 한다."""
    t, c = _noise_db(tmp_path, monkeypatch)
    noisy = cm.find_commonality(t, c)

    t2 = [f"T{i}" for i in range(1, 7)]
    c2 = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t2 + c2]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t2]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c2]
    (tmp_path / "test.db").unlink()        # 같은 tmp_path 에 두 번째 DB 를 새로 쓴다
    _make_db(tmp_path, monkeypatch, ys, hs)
    strong = cm.find_commonality(t2, c2)

    assert strong["p_family_wise"] < noisy["p_family_wise"]


def test_family_wise_p_carries_its_own_floor(tmp_path, monkeypatch):
    """1등의 p 도 바닥에 붙으므로 그 바닥값을 함께 보낸다.

    `p_family_wise` 도 (넘은 횟수+1)/(회차+1) 이라 소표본에서 바닥에 붙는다.
    바닥값 없이 0.05 만 보내면 "1등이 우연일 확률 5%" 로 읽히는데 실제로는 이
    표본이 낼 수 있는 최소값일 수 있다 - 후보별 p 에서 고친 것과 같은 오독이,
    최상위에서 그대로 반복된다. 근거 줄이 교정해 주지도 못한다(최상위 값이라
    Claim 에 안 실린다). 그래서 숫자 자체를 함께 보낸다.

    **이 바닥은 후보별 바닥과 같은 값이 아니다.** family-wise 는 회차별 최댓값을
    재므로 참조집합을 안 좁히고, 후보별 바닥은 좁혀진 참조집합에서 나와 항상 이보다
    크거나 같다. 전수 커버리지 픽스처에서는 우연히 일치하므로
    [[test_the_family_wise_floor_and_the_candidate_floor_part_ways]] 가 갈라 놓는다.
    """
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    assert res["p_family_wise_min_possible"] == 0.05      # 3대3 = 1/20
    assert res["p_family_wise"] >= res["p_family_wise_min_possible"]
    # 후보별 바닥은 좁혀진 참조집합에서 나오므로 이보다 낮아질 수 없다
    assert all(cand["p_min_possible"] >= res["p_family_wise_min_possible"]
               for cand in res["candidates"])


def _partial_noise_db(tmp_path, monkeypatch, n_steps=10):
    """`_noise_db` 와 같지만 **일부 wafer 가 일부 스텝의 이력이 없다.**

    전수 커버리지 픽스처에서는 라벨을 섞어도 `nt`(그 스텝에 이력이 있는 타깃 수)가
    안 움직여 조건화가 아무 것도 안 한다 - 그래서 레전드 축이 "영향 없다" 로 보인다.
    사내 데이터에는 결측이 있으므로 그쪽을 재현한다.
    """
    wafers = ["T1", "T2", "T3", "C1", "C2", "C3"]
    subsets = list(itertools.combinations(wafers, 3))[:n_steps]
    ys = [_y(w, "A45Z5") for w in wafers]
    hs = []
    for i, sub in enumerate(subsets):
        for j, w in enumerate(wafers):
            if i % 3 == 0 and j % 2 == 0:
                continue                  # 이 스텝에는 이 wafer 이력이 없다
            hs.append(_h(w, f"S{i:02d}", "ETCH9" if w in sub else "ETCH8", "1"))
    _make_db(tmp_path, monkeypatch, ys, hs)
    return ["T1", "T2", "T3"], ["C1", "C2", "C3"]


def test_the_family_wise_floor_and_the_candidate_floor_part_ways(tmp_path, monkeypatch):
    """이력 결측이 있으면 두 바닥이 갈린다 - 레전드 축도 조건화를 받는다.

    "레전드 3축은 nt 가 안 움직이니 사실상 영향이 없다" 는 서술은 **더미 DB 가 전수
    커버리지라서** 나온 것이었다. 스텝마다 이력이 있는 wafer 가 달라지면 라벨을
    섞을 때 nt 가 움직이고, 참조집합이 좁혀져 후보별 바닥이 올라간다.
    """
    t, c = _partial_noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    floors = {cand["p_min_possible"] for cand in res["candidates"]}
    assert len(floors) > 1, "후보마다 바닥이 갈리지 않는다 - 픽스처가 퇴화했다"
    assert max(floors) > res["p_family_wise_min_possible"]
    # 왜 바닥이 다른지 읽을 숫자가 함께 나가야 한다
    narrowed = [cand for cand in res["candidates"]
                if cand["p_min_possible"] > res["p_family_wise_min_possible"]]
    assert narrowed and all(cand["n_reference"] < res["candidates"][0]
                            ["n_permutations_total"] - 1 for cand in narrowed)


def test_no_fdr_table_when_permutation_is_off(tmp_path, monkeypatch):
    """순열을 끄면 셀 재료가 없다. 빈 표를 내되 키는 유지한다."""
    t, c = _noise_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c, n_permutations=0)
    assert res["fdr_table"] == []
    assert res["p_family_wise"] is None
    assert res["p_family_wise_min_possible"] is None


def _db_insufficient_group(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch,
             [_y("T1", "A45Z5"), _y("C1", "A45Z5")],
             [_h("T1", "Etch", "ETCH9", "3"), _h("C1", "Etch", "ETCH8", "1")])
    return ["T1"], ["C1"]


def _db_unpaired_root_lot(tmp_path, monkeypatch):
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "AAAAA") for w in t] + [_y(w, "BBBBB") for w in c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)
    return t, c


def _db_no_history_at_all(tmp_path, monkeypatch):
    t, c = ["T1", "T2"], ["C1", "C2"]
    _make_db(tmp_path, monkeypatch, [_y(w, "A45Z5") for w in t + c], [])
    return t, c


def test_the_two_no_paired_stratum_paths_are_told_apart(tmp_path, monkeypatch):
    """`no_paired_stratum` 으로 끝나는 조기 반환이 **둘**이다. 원인이 다르다.

    (1) 대조군이 타깃과 다른 root_lot 에만 있다 -> 이력은 멀쩡하고 짝이 없는 것이다.
        대조군 선정을 다시 해야 한다.
    (2) step_history 가 있는 짝이 하나도 없다 -> 적재·추출 범위를 뒤져야 한다.

    status 가 같아서 두 경로를 세우는 테스트가 서로를 대신할 수 있었다. 한쪽을
    지워도 다른 쪽 단언이 통과하면 아무것도 안 잠긴 것이다. 가르는 것은 **note**
    이고, meta.missing_history 는 두 경로 다 세어서 내되 분모가 다르다((1)은 요청
    wafer 전체, (2)는 짝지어진 stratum 안). (2)는 한쪽이 통째로 결측일 때만
    도달하므로 목록이 비지 않아, **빈 목록이면 (1)** 이라고는 말할 수 있다.
    """
    # 두 픽스처가 같은 파일명을 쓰므로 DB 를 따로 둔다.
    first, second = tmp_path / "unpaired", tmp_path / "no_history"
    first.mkdir(); second.mkdir()

    t, c = _db_unpaired_root_lot(first, monkeypatch)
    unpaired = cm.find_commonality(t, c)
    t, c = _db_no_history_at_all(second, monkeypatch)
    no_history = cm.find_commonality(t, c)

    assert unpaired["status"] == no_history["status"] == "no_paired_stratum"
    # status 로는 못 가른다. 사유를 말하는 것은 note 이고, **어느 wafer 냐**에
    # 답할 수 있는 것은 (2) 뿐이다. 결측 wafer 를 못 대면 엔지니어는 어디를
    # 뒤져야 할지 모른다.
    assert unpaired["note"] != no_history["note"]
    assert no_history["meta"]["missing_history"] == ["C1", "C2", "T1", "T2"]
    # 여기서는 실제로 세어 봐도 결측이 없다(픽스처의 네 wafer 모두 이력이 있다).
    # 안 세고 상수로 내면 안 된다 - 바로 위 테스트가 그 경우를 잰다.
    assert unpaired["meta"]["missing_history"] == []


def test_the_unpaired_path_counts_the_missing_history_it_reports(tmp_path, monkeypatch):
    """경로 (1) 의 결측 목록은 **세어서** 내야 한다 - 상수 `[]` 는 사실이 아니다.

    빈 목록에는 "확인했더니 결측이 없다" 와 "확인한 적이 없다" 가 같이 실린다.
    도구가 낸 사실은 게이트도 LLM 도 검증 없이 믿으므로, 안 센 것을 0 으로
    내보내면 결측이 있는 그룹이 "이력은 멀쩡하다" 로 보고된다 - 이 브랜치가
    `p_at_floor` 에서 없앤 것과 같은 모양의 결함이다.
    """
    ys = [_y("T1", "AAAAA"), _y("T2", "AAAAA"),      # 타깃은 AAAAA
          _y("C1", "BBBBB"), _y("C2", "BBBBB")]      # 대조군은 BBBBB -> 짝이 없다
    hs = [_h("T1", "Etch", "ETCH9", "3"),            # T2 · C2 는 이력이 통째로 없다
          _h("C1", "Etch", "ETCH8", "1")]
    _make_db(tmp_path, monkeypatch, ys, hs)

    res = cm.find_commonality(["T1", "T2"], ["C1", "C2"])
    assert res["status"] == "no_paired_stratum"
    # **양쪽을 다 센다.** 한쪽만 세는 분모(타깃만/대조군만)로 좁혀도 결과가 같아지면
    # 그 절반은 안 잠긴 것이다 - 그래서 타깃과 대조군에서 한 장씩 뺐다.
    assert res["meta"]["missing_history"] == ["C2", "T2"]


@pytest.mark.parametrize("build_db", [_db_insufficient_group, _db_unpaired_root_lot,
                                      _db_no_history_at_all])
def test_early_returns_still_carry_the_top_level_keys(build_db, tmp_path, monkeypatch):
    """계산을 못 한 반환에도 최상위 키는 남아야 한다.

    키가 상황에 따라 있다 없다 하면 소비자가 그때그때 다른 모양을 받는다. LLM 은
    `hypotheses.yaml` 지시대로 fdr_table 을 찾다가 없으면 지어내고, 게이트/리포트는
    KeyError 를 피하려고 호출부마다 기본값을 다시 적게 된다. 계약은 여기서 잠근다.
    """
    t, c = build_db(tmp_path, monkeypatch)
    res = cm.find_commonality(t, c)
    assert res["status"] != "ok", "조기 반환 경로를 안 타면 이 테스트는 아무것도 안 지킨다"
    assert res["fdr_table"] == []
    assert res["p_family_wise"] is None
    assert res["p_family_wise_min_possible"] is None


# ------------------------------- 귀무 참조집합은 표본 크기가 같은 회차로 제한한다
# 계측 샘플링이 걸리면 회차마다 **계측된 타깃 장수(nt)** 가 달라진다. 관측 후보는 큰
# nt 로 만들어진 것인데 귀무 회차 대부분은 nt 가 작아 후보가 아예 안 생기고, 그것이
# "안 넘었다" 로 세어져 p 가 작아진다. 무신호 합성 데이터에서 p<=0.50 이 명목 50% 대신
# 93.3% 로 나오던 것이 이 증상이다 (2026-08-28 실측).

_K = ("metro", "S001", "TH", "ge")


def _fixed_null(sizes_by_t, scores_by_t):
    """라벨의 타깃 마스크로 회차를 구분하는 score_fn. 회차별 값을 직접 박는다."""
    def _fn(labels):
        t = labels[0][1]
        scores = {_K: scores_by_t[t]} if t in scores_by_t else {}
        sizes = {_K: sizes_by_t[t]} if t in sizes_by_t else {}
        return scores, sizes
    return _fn


def test_null_reference_set_drops_rounds_the_candidate_could_not_arise_in():
    """후보가 생길 수 없었던 회차는 '안 넘었다' 가 아니라 **참조 표본이 아니다.**

    1 stratum · 타깃 2 · 대조군 2 -> 섞을 수 있는 배치 6개 중 관측을 뺀 5회차.
    그중 표본 크기가 관측과 같은 회차는 2개뿐이고 그 안에서 1번 넘는다.
      옛 계산: (1+1)/(5+1) = 0.333   <- 못 만들어진 회차 3개를 미달로 셌다
      새 계산: (1+1)/(2+1) = 0.667
    """
    masks = [("L1", 0b0011, 0b1100)]
    fn = _fixed_null(sizes_by_t={0b0101: 2, 0b1001: 2},          # 나머지 3회차는 nt 부족
                     scores_by_t={0b0101: 0.9, 0b1001: 0.1})
    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {_K: 2}, 100, 1, fn)
    assert out["n_used"] == 5
    assert out["n_reference"][_K] == 2
    assert abs(out["p"][_K] - 2 / 3) < 1e-9


def test_a_candidate_with_no_comparable_round_is_not_evidence():
    """참조 회차가 0개면 판단 근거가 없다 - p 도 바닥값도 1.0 이어야 한다.

    "비교할 것이 없었다" 를 작은 p 로 내보내면 근거가 없는 후보가 순위 1등이 된다.
    """
    masks = [("L1", 0b0011, 0b1100)]
    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {_K: 7},
                                100, 1, _fixed_null({}, {}))
    assert out["n_reference"][_K] == 0
    assert out["p"][_K] == 1.0
    assert out["p_min_possible"][_K] == 1.0


def test_conditioning_is_inert_when_the_sample_size_never_moves():
    """분기 반대쪽 - 회차마다 nt 가 같으면 옛 계산과 **완전히 같아야** 한다.

    계측이 전수이거나 고정 슬롯이면 nt 가 안 움직인다. 그 조건에서 값이 바뀌면
    결함이 없는 자리까지 건드린 것이다 (실측에서도 전수/고정 슬롯은 불변이었다).
    """
    masks = [("L1", 0b0011, 0b1100)]
    all_t = [0b0101, 0b1001, 0b0110, 0b1010, 0b1100]
    fn = _fixed_null(sizes_by_t={t: 2 for t in all_t},
                     scores_by_t={t: (0.9 if t == 0b0101 else 0.1) for t in all_t})
    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {_K: 2}, 100, 1, fn)
    assert out["n_reference"][_K] == 5
    assert out["p"][_K] == 2 / 6                     # (1+1)/(5+1) - 옛 값 그대로
    assert out["p_min_possible"][_K] == 1 / 6


def test_size_map_counts_every_computable_key_not_just_the_scoring_ones():
    """참조 여부는 **계산이 성립했는가**로 가른다 - MIN_SCORE 절단과 섞으면 안 된다.

    절단에 걸린 회차는 '진짜로 못 넘은' 회차라 분모에 남아야 한다. 그것까지 빼면
    과보정이다(실측: p<=0.05 가 명목 5.0% 대신 0.6% 로 주저앉는다).
    """
    def _mh(a, b, c, d):
        """`_aggregate` 가 쌓는 mh_num/mh_den 을 손으로 재현한다(단일 stratum 취급).

        `_score_map` 이 이제 mh_num/mh_den 으로 나누므로, 손으로 만든 agg 도 그
        모양을 갖춰야 한다. nt=0 이면 mh_den 도 0 이 되어 '계산 불가' 가 그대로
        걸러진다 — 별도 분기를 안 둬도 된다.

        **정수 정확 산술로 재현한다**(rm10, 2026-09-20 재리뷰) - float `w*(a/nt
        - c/nc)` 로 손수 만들면 실제 `_aggregate` 가 쌓는 정수쌍(R-B1) 모양을 안
        타므로, `_score_map` 을 `float(mh_num)/float(mh_den)` 로 바꾸는 훼손(M11)
        이 이 테스트를 그냥 통과해 버린다. `(a*nc-c*nt)/(nt*nc)` 정수쌍(단일
        stratum 이므로 `mh_scale=1`)이 실제 코드가 쌓는 것과 같은 모양이다.
        """
        nt, nc = a + b, c + d
        if nt == 0 or nc == 0:
            return 0, 0
        return a * nc - c * nt, nt * nc

    raw = {
        ("a",): {"a": 2, "b": 1, "c": 3, "d": 1},    # score = 2/3 - 3/4 < 0 -> 절단
        ("b",): {"a": 3, "b": 0, "c": 0, "d": 4},    # score = 1.0 -> 살아남는다
        ("c",): {"a": 0, "b": 0, "c": 2, "d": 2},    # 타깃이 없다 -> 계산 불가
    }
    agg = {k: {**v, "mh_num": _mh(**v)[0], "mh_den": _mh(**v)[1]} for k, v in raw.items()}
    assert set(cm._score_map(agg)) == {("b",)}
    assert cm._size_map(agg) == {("a",): 3, ("b",): 3}


def test_family_wise_floor_does_not_inherit_the_narrowed_reference_set():
    """family-wise 바닥은 **회차 전부**에서 나온다 - 후보별 바닥과 다른 값이다.

    후보별 바닥은 좁혀진 참조집합에서 나오므로 항상 이보다 크거나 같다. 둘을 같은
    값으로 두면 family-wise p 가 바닥에 닿지 않았는데 닿은 것처럼 보고된다.
    """
    masks = [("L1", 0b0011, 0b1100)]
    fn = _fixed_null(sizes_by_t={0b0101: 2, 0b1001: 2},
                     scores_by_t={0b0101: 0.9, 0b1001: 0.1})
    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {_K: 2}, 100, 1, fn)
    assert out["p_family_wise_min_possible"] == 1 / 6      # 5 회차 전부
    assert out["p_min_possible"][_K] == 1 / 3              # 참조 2 회차


def test_a_missing_size_is_not_a_match():
    """크기를 못 받은 후보를 '크기가 같다' 로 읽으면 조건화가 조용히 꺼진다.

    `None != None` 이 거짓이라, `score_fn` 이 크기를 안 실어 주면 모든 회차가
    참조집합에 들어가 **옛(편향된) 계산으로 소리 없이 되돌아간다.** 아무 것도
    안 터지므로 다음 사람이 알 방법이 없다 - 크기가 없으면 비교 불가로 센다.
    """
    masks = [("L1", 0b0011, 0b1100)]

    def _no_sizes(labels):
        return {_K: 0.9}, {}                       # 점수만 주고 크기는 안 준다

    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {_K: 2}, 100, 1, _no_sizes)
    assert out["n_reference"][_K] == 0
    assert out["p"][_K] == 1.0

    # **관측 쪽 크기도 없을 때가 진짜 위험한 경우다.** 위 단언은 `None != 2` 라
    # 가드가 없어도 통과한다 - `None != None` 이 거짓이 되는 조합을 여기서 잰다.
    # 귀무 점수를 관측보다 **낮게** 주는 것도 필수다. 높게 주면 가드가 없어도 전부
    # '넘었다' 로 세어 p 가 1.0 이 되어, 되돌아간 계산과 구별이 안 된다.
    def _low_and_no_sizes(labels):
        return {_K: 0.1}, {}

    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {}, 100, 1, _low_and_no_sizes)
    assert out["n_reference"][_K] == 0
    assert out["p"][_K] == 1.0


# ------------------------------------- 바닥에 닿았다는 것은 비교가 아니라 셈이다

def test_at_floor_is_a_count_the_tool_carries_not_a_comparison_downstream():
    """`p == p_min_possible` 을 소비자가 재계산하면 반올림에 걸린다.

    두 값은 4자리로 반올림돼 나가므로 참조 회차가 13,333~19,999 이거나 40,000 이상이면
    `1/13334 = 0.0001` 과 `2/13334 = 0.0001` 이 같은 숫자가 된다. 귀무가 한 번
    넘은 후보에 "이 표본의 최소값" 딱지가 붙는 것이 그 결과다
    (`graph/evidence.py::format_evidence_line`). 사실을 아는 자리는 넘은 횟수를
    세고 있는 여기뿐이라, 여기서 싣는다.
    """
    masks = [("L1", 0b0011, 0b1100)]

    # 참조 2회차 중 한 번 관측(0.5)을 넘는다 -> p = 2/3, 바닥 1/3. 바닥이 아니다.
    exceeded = cm._null_distribution(
        masks, 0b1111, {_K: 0.5}, {_K: 2}, 100, 1,
        _fixed_null(sizes_by_t={0b0101: 2, 0b1001: 2},
                    scores_by_t={0b0101: 0.9, 0b1001: 0.1}))
    assert exceeded["p_at_floor"][_K] is False

    # 같은 참조집합인데 아무도 못 넘는다 -> p = 1/3 = 바닥.
    at_floor = cm._null_distribution(
        masks, 0b1111, {_K: 0.5}, {_K: 2}, 100, 1,
        _fixed_null(sizes_by_t={0b0101: 2, 0b1001: 2},
                    scores_by_t={0b0101: 0.1, 0b1001: 0.1}))
    assert at_floor["p_at_floor"][_K] is True


def test_a_candidate_with_no_comparable_round_is_not_at_floor():
    """참조 회차가 0이면 **바닥에 닿은 것이 아니라 잴 것이 없었다** 이다.

    넘은 횟수만 세면 둘이 같은 0 이라 정반대 뜻이 한 이름에 실린다. 참조 0회는
    p 도 바닥도 1.0 인 상태이고, 이 저장소는 그것을 "이 표본이 낼 수 있는 최강"
    과 따로 떼어 놓는다(`graph/evidence.py::_is_statistical`, 근거 줄의 "비교
    가능한 귀무 표본이 없어 판단 불가"). 딱지가 안 붙는 이유가 근거 줄의 분기
    **순서**뿐이면, 순서를 뒤집는 것만으로 정반대 문구가 나간다.
    """
    masks = [("L1", 0b0011, 0b1100)]
    out = cm._null_distribution(masks, 0b1111, {_K: 0.5}, {_K: 7}, 100, 1,
                                _fixed_null({}, {}))
    assert out["n_reference"][_K] == 0
    assert out["p"][_K] == out["p_min_possible"][_K] == 1.0
    assert out["p_at_floor"][_K] is False


def test_the_candidate_copies_the_floor_fact_instead_of_recomputing_it(
        tmp_path, monkeypatch):
    """후보 조립은 도구가 센 사실을 **그대로 옮긴다** - 두 숫자를 다시 비교하지 않는다.

    실데이터로는 이 둘이 대개 같은 답을 내서(완전 분리면 p == 바닥 == 사실 True)
    조립부가 몰래 등호로 되돌아가도 티가 안 난다. 그래서 둘이 **갈리는** 순열 결과
    (참조 0회 - p 도 바닥도 1.0 인데 바닥에 닿은 것은 아니다)를 주입해 잰다.
    """
    t, c = ["T1", "T2"], ["C1", "C2"]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    real = cm._permutation_stats

    def _inject(p_val, floor, fact):
        def _fn(*args, **kwargs):
            perm = real(*args, **kwargs)
            return {**perm,
                    "p": {k: p_val for k in perm["p"]},
                    "p_min_possible": {k: floor for k in perm["p_min_possible"]},
                    "p_at_floor": {k: fact for k in perm["p_at_floor"]},
                    "n_reference": {k: 0 for k in perm["n_reference"]}}
        return _fn

    # 참조 0회: p 도 바닥도 1.0 인데 바닥에 닿은 것은 아니다. 등호로 다시 계산하면 True.
    monkeypatch.setattr(cm, "_permutation_stats", _inject(1.0, 1.0, False))
    eq = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert eq["p_permutation"] == eq["p_min_possible"] == 1.0
    assert eq["p_at_floor"] is False

    # 반대 방향도 잠근다 - 안 그러면 "상수 False" 로 고쳐도 안 잡힌다.
    monkeypatch.setattr(cm, "_permutation_stats", _inject(0.5, 0.001, True))
    eq2 = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert eq2["p_permutation"] != eq2["p_min_possible"]
    assert eq2["p_at_floor"] is True


def test_candidate_carries_the_floor_fact(tmp_path, monkeypatch):
    """도구가 낸 후보에 사실이 실려야 소비자가 반올림된 숫자를 다시 안 비교한다."""
    t = [f"T{i}" for i in range(1, 7)]
    c = [f"C{i}" for i in range(1, 7)]
    ys = [_y(w, "A45Z5") for w in t + c]
    hs = [_h(w, "Etch", "ETCH9", "3") for w in t]
    hs += [_h(w, "Etch", "ETCH8", "1") for w in c]
    _make_db(tmp_path, monkeypatch, ys, hs)

    eq = _find(cm.find_commonality(t, c), "equipment", "ETCH9")
    assert eq["p_at_floor"] is True          # 완전 분리 - 귀무가 한 번도 못 넘었다
