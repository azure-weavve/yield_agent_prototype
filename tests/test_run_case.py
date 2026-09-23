"""data/run_case.py 검증 (P1-4, docs/tasks/case-run-prep/plan.md A1-A10).

사례 DB 는 metro 테이블이 없는 모양이다(load_internal.py DDL 확인) - 여기서도
yield·step_history 두 테이블만 만든다. 원인 챔버(ETCH9_B)를 타깃 전원이 거치고
대조군은 아무도 안 거치게 심어서, groups[0] 이 결정론적으로 그 챔버가 되게 한다
(tests/test_commonality.py 의 clean_separation 패턴과 동일).
"""

import os
import json
import sqlite3
from pathlib import Path

import pytest

import ya_config
from data import run_case
from domain import engine
from graph import evidence


# ------------------------------------------------------------------ DB 픽스처

def _make_db(tmp_path, name: str, yield_rows, step_rows) -> Path:
    db = tmp_path / name
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE yield (
        wafer_id TEXT PRIMARY KEY, lot_id TEXT NOT NULL, yield REAL NOT NULL,
        defect_type TEXT, step_seq TEXT, date TEXT NOT NULL,
        root_lot_id TEXT NOT NULL, lot_type TEXT NOT NULL)""")
    if yield_rows:
        conn.executemany(
            "INSERT INTO yield (wafer_id, lot_id, yield, defect_type, step_seq, "
            "date, root_lot_id, lot_type) VALUES (?,?,?,?,?,?,?,?)", yield_rows)
    conn.execute("""CREATE TABLE step_history (
        wafer_id TEXT NOT NULL, root_lot_id TEXT NOT NULL, step_seq TEXT NOT NULL,
        area TEXT, eqp_id TEXT NOT NULL, ch_id TEXT, ppid TEXT, timestamp TEXT)""")
    if step_rows:
        conn.executemany(
            "INSERT INTO step_history (wafer_id, root_lot_id, step_seq, area, "
            "eqp_id, ch_id, ppid, timestamp) VALUES (?,?,?,?,?,?,?,?)", step_rows)
    conn.commit()
    conn.close()
    return db


def _y(wid, root, y=90.0, lot_type="PP"):
    return (wid, f"{root}.1", y, None, None, "2026-09-01", root, lot_type)


def _h(wid, root, step, eqp, ch, ppid=None, ts="2026-09-01 10:00:00"):
    return (wid, root, step, None, eqp, ch, ppid, ts)


TARGETS = ["A45Z5_01", "A45Z5_02", "A45Z5_03"]
CONTROLS = ["A45Z5_04", "A45Z5_05", "A45Z5_06"]
STEP = "CC001000"

# ppid_commonality 용 - PPID_X 를 대조군 2/3 도 같이 써서 분리 점수 0.333(<0.5) 인
# **미통과** 후보를 하나 심는다(m1). MIN_SCORE(0.0) 는 넘고 PASS_MIN_SCORE(0.5)
# 는 못 넘어야 "탐색 범위엔 남지만 판별선은 못 넘는" 후보가 된다.
PPID_TARGET = "PPID_X"
PPID_CONTROLS = {CONTROLS[0]: "PPID_X", CONTROLS[1]: "PPID_X", CONTROLS[2]: "PPID_Y"}


def _clean_case_db(tmp_path, name="case.db") -> Path:
    """타깃 전원이 ETCH9/B 를 거치고 대조군은 아무도 안 거친 심어 둔 원인.

    ppid 는 일부러 대조군과 겹치게 심어 eqp_ch 축과 별개로 **판별선을 못 넘는
    후보**(ppid_commonality:ppid:CC001000:PPID_X, score 0.333)를 함께 낸다 -
    ranked_groups() 가 통과 후보만 접는지 확인하는 재료다(m1).
    """
    yield_rows = [_y(w, "A45Z5", y=80.0) for w in TARGETS] + \
                 [_y(w, "A45Z5", y=97.0) for w in CONTROLS]
    step_rows = ([_h(w, "A45Z5", STEP, "ETCH9", "B", ppid=PPID_TARGET) for w in TARGETS] +
                [_h(w, "A45Z5", STEP, "PHOT1", "A", ppid=PPID_CONTROLS[w]) for w in CONTROLS])
    return _make_db(tmp_path, name, yield_rows, step_rows)


def _insufficient_control_db(tmp_path, name="thin.db") -> Path:
    """타깃의 root_lot 에 대조군 후보가 하나도 없다 -> select_control 이 부족을 낸다."""
    yield_rows = [_y("B99K1_01", "B99K1"), _y("B99K1_02", "B99K1")]
    return _make_db(tmp_path, name, yield_rows, [])


# ------------------------------------------------------------------ A1: 없는 DB

def test_missing_db_raises_and_creates_nothing(tmp_path):
    missing = tmp_path / "nope.db"
    assert not missing.exists()
    with pytest.raises(FileNotFoundError):
        run_case.run_case(missing, ["X1"])
    assert not missing.exists()


# ------------------------------------------------------------------ A2: 없는 타깃

def test_unknown_targets_stop_before_any_axis(tmp_path):
    db = _clean_case_db(tmp_path)
    result = run_case.run_case(db, [TARGETS[0], "A45Z5_99"])
    assert result["stopped"] == "unknown_targets"
    assert result["unknown_targets"] == ["A45Z5_99"]
    assert result["axes"] == []
    assert result["groups"] == []


# ------------------------------------------------------------------ A3: 대조군 부족

def test_control_insufficient_stops_before_axes(tmp_path):
    db = _insufficient_control_db(tmp_path)
    result = run_case.run_case(db, ["B99K1_01"])
    assert result["stopped"] == "control_insufficient"
    assert result["control"]["insufficient"] is True
    assert result["control"]["control_group"] == ["B99K1_02"]   # 1장 < CONTROL_MIN_SIZE(3)
    assert result["axes"] == []
    assert result["groups"] == []


def test_cli_control_insufficient_exits_0_and_mentions_shortage(tmp_path, capsys):
    """m3(a) - 대조군 부족은 입력 오류가 아니라 결과다: CLI 종료 0, 화면에 "부족"."""
    db = _insufficient_control_db(tmp_path)
    code = run_case.main(["--db", str(db), "--targets", "B99K1_01"])
    out = capsys.readouterr().out
    assert code == 0
    assert "부족" in out


# ------------------------------------------------------------------ A4: 정상 경로

def test_normal_run_finds_planted_chamber_as_top_group(tmp_path):
    db = _clean_case_db(tmp_path)
    result = run_case.run_case(db, TARGETS)

    assert result["stopped"] is None
    assert result["control"]["insufficient"] is False
    assert sorted(result["control"]["control_group"]) == CONTROLS
    assert result["target_root_lots"] == {"A45Z5": 3}

    by_id = {a["hypothesis_id"]: a for a in result["axes"]}
    assert set(by_id) == {"eqp_ch_commonality", "ppid_commonality",
                          "step_passage_commonality", "metro_commonality"}
    for hid in ("eqp_ch_commonality", "ppid_commonality", "step_passage_commonality"):
        assert by_id[hid]["outcome"] == "ran", hid
        assert by_id[hid]["result"] is not None
    assert by_id["metro_commonality"]["outcome"] == "no_table"
    assert by_id["metro_commonality"]["error"] == "metro"
    assert by_id["metro_commonality"]["result"] is None

    assert result["groups"], "심어 둔 원인이 통과 후보로 나와야 한다"
    top = result["groups"][0]
    assert top["rank"] == 1
    assert top["level"] == "chamber"
    assert top["key"] == "ETCH9_B"
    assert sorted(top["target_wafers"]) == TARGETS
    assert sorted(top["control_wafers"]) == []

    # m1: 미통과 후보(ppid PPID_X, score 0.333 < 0.5)가 실제로 나왔는지 먼저
    # 확인하고 - 안 나오면 아래 부재 단언이 공허해진다 - 그 claim_id 가 순위
    # 묶음 어디에도(대표/교락/포함 어느 자리에도) 없는지 본다. `ranked_groups()`
    # 가 실수로 `self.claims.values()`(미통과 포함 전부)를 접으면 이 단언이
    # 깨진다 - "통과 후보만 접는다" 는 계약을 훼손으로 확인한다.
    ppid_axis = by_id["ppid_commonality"]["result"]
    ppid_cands = {(c["key"], c["passes"]): c for c in ppid_axis["candidates"]}
    assert (PPID_TARGET, False) in ppid_cands, ppid_axis["candidates"]
    assert ppid_cands[(PPID_TARGET, False)]["score"] < 0.5

    failing_claim_id = f"ppid_commonality:ppid:{STEP}:{PPID_TARGET}"
    all_claim_ids = set()
    for g in result["groups"]:
        all_claim_ids.add(g["claim_id"])
        all_claim_ids.update(o["claim_id"] for o in g.get("confounded_with") or [])
        all_claim_ids.update(o["claim_id"] for o in g.get("rolled_up_as") or [])
    assert failing_claim_id not in all_claim_ids

    # 굵은 해상도(설비 ETCH9)는 챔버와 같은 wafer 집합을 가리키므로 한 그룹으로
    # 접혀 "rolled_up_as" 에 실린다 - 접기 자체가 도는지 확인한다.
    equipment_claim_id = f"eqp_ch_commonality:equipment:{STEP}:ETCH9"
    rolled_up_ids = {o["claim_id"] for o in top.get("rolled_up_as") or []}
    assert equipment_claim_id in rolled_up_ids


# ------------------------------------------------------------------ A5: 도구 예외

def test_tool_exception_marks_only_that_axis_failed(tmp_path, monkeypatch):
    db = _clean_case_db(tmp_path)
    original = engine.TOOLS["step_history"]
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("boom")
        return original(*a, **kw)

    monkeypatch.setitem(engine.TOOLS, "step_history", flaky)

    result = run_case.run_case(db, TARGETS)   # 예외가 밖으로 새면 여기서 실패한다

    by_id = {a["hypothesis_id"]: a for a in result["axes"]}
    assert by_id["eqp_ch_commonality"]["outcome"] == "failed"
    assert "KeyError" in by_id["eqp_ch_commonality"]["error"]
    assert by_id["ppid_commonality"]["outcome"] == "ran"
    assert by_id["step_passage_commonality"]["outcome"] == "ran"
    assert by_id["metro_commonality"]["outcome"] == "no_table"
    assert calls["n"] == 3          # step_history 축 3개 전부 호출됐다 (1개만 실패)


# ------------------------------------------------------------------ A6: DB_PATH 복원

def test_db_path_restored_after_normal_run(tmp_path):
    db = _clean_case_db(tmp_path)
    original = ya_config.DB_PATH
    run_case.run_case(db, TARGETS)
    assert ya_config.DB_PATH == original


def test_db_path_restored_after_exception(tmp_path, monkeypatch):
    db = _clean_case_db(tmp_path)
    original = ya_config.DB_PATH

    def boom(*a, **kw):
        raise RuntimeError("가설 로딩 실패")

    monkeypatch.setattr("domain.registry.load_hypotheses", boom)

    with pytest.raises(RuntimeError):
        run_case.run_case(db, TARGETS)
    assert ya_config.DB_PATH == original


# ------------------------------------------------------------------ A7: render()

def test_render_includes_group_line_and_no_table_marker(tmp_path):
    db = _clean_case_db(tmp_path)
    result = run_case.run_case(db, TARGETS)
    text = run_case.render(result)

    expected_line = evidence.format_group_line(result["groups"][0])
    assert expected_line in text
    assert "미적재" in text
    assert "metro" in text


# ------------------------------------------------------------------ A8: CLI

def test_cli_missing_db_exits_2(tmp_path):
    missing = tmp_path / "nope.db"
    code = run_case.main(["--db", str(missing), "--targets", "X1"])
    assert code == 2
    assert not missing.exists()


def test_cli_normal_run_exits_0_and_writes_json(tmp_path, capsys):
    db = _clean_case_db(tmp_path)
    out = tmp_path / "out.json"
    code = run_case.main(["--db", str(db), "--targets", ",".join(TARGETS),
                          "--out", str(out)])
    capsys.readouterr()
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["stopped"] is None
    assert data["target_root_lots"] == {"A45Z5": 3}


def test_cli_unknown_targets_exits_2(tmp_path):
    db = _clean_case_db(tmp_path)
    code = run_case.main(["--db", str(db), "--targets", f"{TARGETS[0]},A45Z5_99"])
    assert code == 2


# ------------------------------------------------------------------ A10: 읽기 전용

def test_run_case_does_not_write_to_case_db(tmp_path):
    db = _clean_case_db(tmp_path)
    before = db.stat()
    run_case.run_case(db, TARGETS)
    after = db.stat()
    assert before.st_mtime == after.st_mtime
    assert before.st_size == after.st_size


# ------------------------------------------------------------------ m3(b): 타깃 1장

def test_single_target_is_insufficient_group_and_render_says_no_passing_groups(tmp_path):
    db = _clean_case_db(tmp_path)
    result = run_case.run_case(db, [TARGETS[0]])

    assert result["stopped"] is None                 # 대조군은 충분하다(D1 - 안 막는다)
    by_id = {a["hypothesis_id"]: a for a in result["axes"]}
    for hid in ("eqp_ch_commonality", "ppid_commonality", "step_passage_commonality"):
        assert by_id[hid]["outcome"] == "ran", hid
        assert by_id[hid]["result"]["status"] == "insufficient_group", hid
    assert result["groups"] == []
    assert "(통과 후보 없음)" in run_case.render(result)


# ------------------------------------------------------------------ m3(c): 중복 타깃

def test_duplicate_targets_deduplicated_preserving_order(tmp_path):
    db = _clean_case_db(tmp_path)
    result = run_case.run_case(db, [TARGETS[1], TARGETS[0], TARGETS[1], TARGETS[0]])
    assert result["targets"] == [TARGETS[1], TARGETS[0]]


# ------------------------------------------------------------------ m4: db_path 검사

def test_directory_as_db_raises_same_as_missing(tmp_path):
    adir = tmp_path / "adir"
    adir.mkdir()
    with pytest.raises(FileNotFoundError):
        run_case.run_case(adir, ["X1"])


def test_cli_directory_as_db_exits_2(tmp_path):
    adir = tmp_path / "adir"
    adir.mkdir()
    code = run_case.main(["--db", str(adir), "--targets", "X1"])
    assert code == 2
    assert list(adir.iterdir()) == []          # 아무 것도 안 만들어졌다


def test_cli_zero_byte_db_exits_2_with_clear_message(tmp_path, capsys):
    db = tmp_path / "zero.db"
    db.write_bytes(b"")
    code = run_case.main(["--db", str(db), "--targets", "X1"])
    out = capsys.readouterr().out
    assert code == 2
    assert "DB" in out and "읽을 수 없다" in out


def test_cli_out_equal_to_db_rejected_before_running(tmp_path):
    db = _clean_case_db(tmp_path)
    before = db.stat()
    code = run_case.main(["--db", str(db), "--targets", ",".join(TARGETS),
                          "--out", str(db)])
    after = db.stat()
    assert code == 2
    assert before.st_mtime == after.st_mtime and before.st_size == after.st_size


def test_cli_out_parent_dir_missing_rejected_before_running(tmp_path):
    db = _clean_case_db(tmp_path)
    out = tmp_path / "no_such_dir" / "out.json"
    code = run_case.main(["--db", str(db), "--targets", ",".join(TARGETS),
                          "--out", str(out)])
    assert code == 2
    assert not out.exists()
    assert not out.parent.exists()


def test_cli_out_hardlink_to_db_rejected_before_running(tmp_path):
    # resolve() 로는 다른 경로로 보이지만 같은 파일이다(r2).
    db = _clean_case_db(tmp_path)
    link = tmp_path / "link.json"
    os.link(db, link)
    before = db.read_bytes()
    code = run_case.main(["--db", str(db), "--targets", ",".join(TARGETS),
                          "--out", str(link)])
    assert code == 2
    assert db.read_bytes() == before


def test_cli_out_is_directory_rejected_before_running(tmp_path):
    db = _clean_case_db(tmp_path)
    out = tmp_path / "outdir"
    out.mkdir()
    code = run_case.main(["--db", str(db), "--targets", ",".join(TARGETS),
                          "--out", str(out)])
    assert code == 2
    assert list(out.iterdir()) == []
