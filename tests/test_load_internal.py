"""사내 적재 왕복 — transform → INSERT 경로가 실제로 도는지.

계약 테스트(test_schema_contract.py)는 **DDL 만** 동결한다. 그래서 DDL 에 컬럼이
있어도 transform_steps 나 INSERT 에서 빠뜨리면 계약은 green 인데 적재된 값은
전부 NULL 이 된다 — hyp_ppid_commonality 가 에러 없이 후보 0 으로 끝나는,
계약 테스트가 막으려던 것과 똑같은 모양의 조용한 실패다. 그 구멍을 메운다.
"""

import csv
import io
import os
import sqlite3
import subprocess
import sys

import pytest

import ya_config
from data import load_internal as li

YIELDS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "lot_id": "A45Z5.1",
           "lot_type": "PP", "yield": 91.2, "date": "2026-07-01"},
          {"root_lot_id": "A45Z5", "wafer_id": "02", "lot_id": "A45Z5.1",
           "lot_type": "PP", "yield": 62.0, "date": "2026-07-01"}]

STEPS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "step_seq": "CC002000",
          "area": "Etch", "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_Y",
          "timestamp": "t"},
         {"root_lot_id": "A45Z5", "wafer_id": "02", "step_seq": "CC002000",
          "area": "Etch", "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_X",
          "timestamp": "t"},
         # area·ch_id·ppid 없는 원천 (공정명 미제공·단일 챔버 설비·PPID 개념 없는 스텝)
         {"root_lot_id": "A45Z5", "wafer_id": "02", "step_seq": "CC004000",
          "eqp_id": "CMP1", "timestamp": "t"}]


def _load(tmp_path):
    db = tmp_path / "t.db"
    report = li.load(YIELDS, STEPS, db, verbose=False)
    return db, report


def test_step_columns_survive_the_write_path(tmp_path):
    """DDL 에만 있고 INSERT 에서 빠지는 일이 없어야 한다."""
    db, _ = _load(tmp_path)
    conn = sqlite3.connect(db)
    rows = conn.execute("""SELECT wafer_id, area, eqp_id, ch_id, ppid FROM step_history
                           ORDER BY wafer_id, step_seq""").fetchall()
    conn.close()
    assert rows == [("A45Z5_01", "Etch", "ETCH9", "A", "PPID_Y"),
                    ("A45Z5_02", "Etch", "ETCH9", "B", "PPID_X"),
                    ("A45Z5_02", None, "CMP1", None, None)]   # 결측은 NULL 로


def test_null_rates_reflect_actual_gaps(tmp_path):
    """결측률이 실제 결측을 반영해야 한다 — 0.0 으로 굳으면 '안 실렸다'를 못 본다."""
    _, report = _load(tmp_path)
    assert report["ch_id_null_rate"] == round(1 / 3, 3)
    assert report["ppid_null_rate"] == round(1 / 3, 3)
    assert report["area_null_rate"] == round(1 / 3, 3)
    assert not report["fatal"]


def test_lot_type_comes_from_the_source_code_not_from_the_lot_id(tmp_path):
    """판정 재료는 원천의 두 자리 코드다 — lot_id 접미는 아무것도 결정하지 않는다.

    한동안 `lot_id` 의 '.1' 접미를 보는 휴리스틱이었다. 되돌아가면 여기서 잡힌다:
    아래 두 행은 접미와 코드가 서로 반대라 옛 규칙이면 값이 뒤집힌다.
    """
    ys = [{"root_lot_id": "Z99Z9", "wafer_id": "01", "lot_id": "Z99Z9.1",
           "lot_type": "ES", "yield": 80.0, "date": "d"},
          {"root_lot_id": "Z99Z9", "wafer_id": "02", "lot_id": "Z99Z9.2",
           "lot_type": "PP", "yield": 80.0, "date": "d"}]
    st = [{"root_lot_id": "Z99Z9", "wafer_id": f"{i:02d}", "step_seq": "CC002000",
           "eqp_id": "E9", "timestamp": "t"} for i in (1, 2)]
    report = li.load(ys, st, tmp_path / "t.db", verbose=False)

    assert report["lot_types"] == {"eval": 1, "prod": 1}


def test_a_malformed_lot_type_code_stops_the_load(tmp_path):
    """코드 형식이 어긋나면 조용히 eval 로 떨어뜨리지 말고 멈춰야 한다.

    eval 로 흘리면 양산랏이 통째로 평가랏이 되어도 리포트의 lot_type 집계가
    그럴듯해 보인다 — 사람이 볼 수 있는 증상이 없다.
    """
    ys = [dict(YIELDS[0], lot_type="PROD")]
    db = tmp_path / "t.db"
    try:
        li.load(ys, [], db, verbose=False)
    except ValueError as e:
        assert "두 자리" in str(e)
    else:
        raise AssertionError("형식 위반 코드가 통과했다")
    # 실패한 적재가 기존 DB 자리에 잔해를 남기면 안 된다
    assert not db.exists() and not db.with_name(db.name + ".tmp").exists()


def test_a_process_name_in_step_seq_is_flagged(tmp_path):
    """step_seq 자리에 공정명이 들어오면 경고해야 한다 — area 와 뒤바뀐 원천의 서명.

    이 사고는 에러를 내지 않는다. 공정명으로 묶인 후보가 그럴듯하게 나오고, 사내에서
    그 스텝 번호를 못 찾아서야 뒤늦게 드러난다. 다만 교체는 막지 않는다 — 자릿수
    관행이 제품군마다 다를 수 있어 오경보가 가능하다.
    """
    st = [dict(s, step_seq="Etch") for s in STEPS]
    report = li.load(YIELDS, st, tmp_path / "t.db", verbose=False)

    assert any("step_seq 형식 위반" in i for i in report["issues"])
    assert not report["fatal"] and report["swapped"]


def test_irregular_step_suffix_is_not_a_format_violation(tmp_path):
    """비정규 스텝 표시 `EC` 접미는 정상 값이다 ("AA110000EC").

    정규식을 `[A-Z]{2}\\d{6}$` 로 좁히면 실데이터의 비정규 스텝 전종이 경고에 실려
    사람이 진짜 위반(area 와 뒤바뀜)을 그 안에서 못 찾는다. 접미를 **떼서** 실어도
    안 된다 — 정규 스텝과 같은 키로 뭉쳐 commonality 분모가 조용히 달라진다.
    """
    st = ([dict(s, step_seq="AA110000EC") for s in STEPS] +
          [dict(s, step_seq="AA110000") for s in STEPS])
    report = li.load(YIELDS, st, tmp_path / "t.db", verbose=False)

    assert not any("step_seq 형식 위반" in i for i in report["issues"])
    assert _step_seqs(tmp_path / "t.db") == ["AA110000", "AA110000EC"]   # 원천 값 그대로


def _step_seqs(db):
    conn = sqlite3.connect(db)
    try:
        return sorted(r[0] for r in conn.execute("SELECT DISTINCT step_seq FROM step_history"))
    finally:
        conn.close()


def test_padded_step_seq_does_not_split_one_step_into_two(tmp_path):
    """고정폭 원천의 앞뒤 공백이 같은 스텝을 두 군으로 쪼개면 안 된다.

    `"CC002000"` 과 `"CC002000 "` 이 섞이면 commonality 가 같은 설비를 두 군으로 나눠
    분리 점수가 반토막 나는데, 에러는 나지 않는다.
    """
    st = [dict(STEPS[0]), dict(STEPS[1])]
    st[1]["step_seq"] = " CC002000 "          # 고정폭 CHAR 원천의 흔한 모양
    db = tmp_path / "t.db"
    li.load(YIELDS, st, db, verbose=False)

    conn = sqlite3.connect(db)
    seqs = [r[0] for r in conn.execute("SELECT DISTINCT step_seq FROM step_history")]
    conn.close()
    assert seqs == ["CC002000"]


def test_report_prints_on_a_console_that_cannot_encode_every_character(tmp_path,
                                                                      monkeypatch):
    """cp949 콘솔에서 리포트가 죽으면 안 된다.

    `_print` 는 os.replace **뒤에** 불린다. 한 줄이 UnicodeEncodeError 로 죽으면 DB 는
    교체된 채 traceback 만 남고 **사람이 봐야 할 경고 문구가 사라진다** — 리포트가
    가장 필요한 순간이 정확히 이 경로다.

    이 저장소가 직접 쓰는 문구는 전부 cp949 안으로 맞췄으므로(그래야 '?' 로도 안 깨진다),
    남은 위험은 **데이터에서 오는 문자열**이다. 리포트는 DB 경로·wafer_id 예시 같은
    외부 값을 그대로 싣는데 그 안에 무엇이 들어올지는 이 저장소가 통제하지 못한다.
    여기서는 경로에 em-dash(U+2014, 한국어 코드페이지에 없다)를 넣어 그 경우를 만든다.
    """
    steps = STEPS + [dict(STEPS[0])]          # wafer×스텝 중복 → 경고 1건 발생
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)
    li.load(YIELDS, steps, tmp_path / "t—.db", verbose=True)   # 경로에 cp949 밖 글자
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert "재작업" in out                     # 경고 내용이 남아야 한다
    assert "[교체]" in out                     # 경고 뒤 줄까지 끝까지 찍혀야 한다
    assert "[라벨]" in out                     # 경고 앞 진단 줄도 사라지면 안 된다


def test_help_text_survives_a_cp949_console():
    """`--help` 는 argparse 가 직접 찍으므로 `_say` 가 못 덮는다.

    help·description 문구에 cp949 밖 글자(em-dash·⚠️)를 하나 넣으면 `--help` 자체가
    UnicodeEncodeError 로 죽는다. 코드에는 그러지 말라는 주석이 있지만 주석은 강제력이
    없어서, 이 저장소에서 `_say` 가 구조적으로 보호할 수 없는 유일한 경로를 여기서 고정한다.
    """
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    proc = subprocess.run([sys.executable, "-m", "data.load_internal", "--help"],
                          capture_output=True, env=env,
                          cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")


def test_script_path_execution_finds_the_repo_root():
    """`python data/load_internal.py` (스크립트 경로) 로도 돌아야 한다.

    스크립트 경로로 실행하면 `sys.path[0]` 은 **`data/`** 이고 CWD 는 들어가지 않는다.
    그래서 모듈 상단의 `sys.path.insert` 가 없으면 `import ya_config` 가 죽는다.
    사내에서 실제로 이 형태로 실행해 `ModuleNotFoundError` 를 봤고(2026-08-03),
    방어를 넣었지만 그 세 줄을 지워도 나머지 테스트는 전부 통과한다 — 여기서 잠근다.

    `PYTHONPATH` 를 지우고 돌린다. 안 그러면 상위 프로세스가 저장소 루트를 넘겨줘
    방어가 없어도 통과하는 공허한 테스트가 된다.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run([sys.executable, os.path.join("data", "load_internal.py"), "--help"],
                          capture_output=True, env=env, cwd=root)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# CSV 입력 (P1-3 사례 자료) — read_csv_records() + CLI 분기
# --------------------------------------------------------------------------- #
def _write_csv(path, fieldnames, rows, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_source_column_names_with_colmap_round_trip_through_load(tmp_path):
    """T1: 원천 컬럼명 + 대응표로 된 CSV 두 개가 load() 까지 왕복해야 한다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["ROOT", "WF", "LOT", "LTYPE", "YLD", "DT"],
               [{"ROOT": "A1", "WF": "1", "LOT": "A1.1", "LTYPE": "PP",
                 "YLD": "91.2", "DT": "2026-01-01"},
                {"ROOT": "A1", "WF": "2", "LOT": "A1.1", "LTYPE": "PP",
                 "YLD": "62.0", "DT": "2026-01-01"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["ROOT", "WF", "STEP", "EQP"],
               [{"ROOT": "A1", "WF": "1", "STEP": "CC002000", "EQP": "E1"},
                {"ROOT": "A1", "WF": "2", "STEP": "CC002000", "EQP": "E1"}])
    colmap = tmp_path / "map.yaml"
    colmap.write_text(
        "yield:\n"
        "  ROOT: root_lot_id\n  WF: wafer_no\n  LOT: lot_id\n"
        "  LTYPE: lot_type\n  YLD: yield\n  DT: date\n"
        "steps:\n"
        "  ROOT: root_lot_id\n  WF: wafer_no\n  STEP: step_seq\n  EQP: eqp_id\n",
        encoding="utf-8")

    yrs, srs = li.read_csv_records(yc, sc, "percent", colmap=colmap)
    db = tmp_path / "t.db"
    report = li.load(yrs, srs, db, verbose=False)

    assert report["n_yield"] == 2 and report["n_steps"] == 2
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT wafer_id, yield FROM yield ORDER BY wafer_id").fetchall()
    conn.close()
    assert rows == [("A1_01", 91.2), ("A1_02", 62.0)]


def test_contract_key_headers_load_without_a_colmap(tmp_path):
    """T2: 원천 컬럼명이 이미 계약 키면 대응표 없이도 적재된다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "B2", "wafer_no": "1", "lot_id": "B2.1", "lot_type": "PP",
                 "yield": "80.0", "date": "d"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "B2", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E9"}])

    yrs, srs = li.read_csv_records(yc, sc, "percent")
    db = tmp_path / "t.db"
    report = li.load(yrs, srs, db, verbose=False)
    assert report["n_yield"] == 1 and not report["fatal"]


def test_bom_prefixed_utf8_header_is_recognized(tmp_path):
    """T3: 엑셀이 저장한 UTF-8 BOM 이 첫 컬럼명에 붙어도 필수 컬럼 검사가 깨지면 안 된다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "C3", "wafer_no": "1", "lot_id": "C3.1", "lot_type": "PP",
                 "yield": "70.0", "date": "d"}], encoding="utf-8-sig")
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "C3", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}],
               encoding="utf-8-sig")

    yrs, srs = li.read_csv_records(yc, sc, "percent")
    db = tmp_path / "t.db"
    report = li.load(yrs, srs, db, verbose=False)
    assert report["n_yield"] == 1 and not report["fatal"]


def test_ratio_yield_unit_is_converted_to_percent_before_load(tmp_path):
    """T4a: ratio 입력이면 저장값이 x100 이어야 한다 — validate() 의 범위검사(0~100)가
    비율(0~1)을 못 잡아 전부 저수율로 통과하는 함정(요청서 5-2)을 막는 지점이다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1", "lot_type": "PP",
                 "yield": "0.912", "date": "2026-01-01"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}])

    yrs, srs = li.read_csv_records(yc, sc, "ratio")
    db = tmp_path / "t.db"
    report = li.load(yrs, srs, db, verbose=False)

    conn = sqlite3.connect(db)
    y = conn.execute("SELECT yield FROM yield").fetchone()[0]
    conn.close()
    assert y == pytest.approx(91.2)
    assert not report["fatal"]


def test_percent_yield_unit_is_stored_unchanged(tmp_path):
    """T4b: percent 입력이면 변환 없이 그대로 저장돼야 한다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1", "lot_type": "PP",
                 "yield": "91.2", "date": "2026-01-01"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}])

    yrs, srs = li.read_csv_records(yc, sc, "percent")
    db = tmp_path / "t.db"
    li.load(yrs, srs, db, verbose=False)

    conn = sqlite3.connect(db)
    y = conn.execute("SELECT yield FROM yield").fetchone()[0]
    conn.close()
    assert y == pytest.approx(91.2)


def test_missing_required_column_stops_before_reading_rows(tmp_path):
    """T5: 대응 후에도 필수 키가 없으면 행을 읽기 전에 멈추고, 메시지에 빠진 키를 담는다."""
    yc = tmp_path / "yield.csv"
    # lot_type 컬럼이 통째로 빠짐
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1",
                 "yield": "91.2", "date": "2026-01-01"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])

    with pytest.raises(ValueError, match="lot_type"):
        li.read_csv_records(yc, sc, "percent")


def test_colmap_typo_not_in_header_stops(tmp_path):
    """T6a: 대응표의 원천 컬럼명이 CSV 헤더에 없으면(오타) 멈춘다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("yield:\n  WRONG_COL: root_lot_id\n", encoding="utf-8")

    with pytest.raises(ValueError, match="WRONG_COL"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_colmap_duplicate_mapping_to_same_key_stops(tmp_path):
    """T6b: 두 원천 컬럼이 같은 계약 키로 대응되면 조용한 덮어쓰기 대신 멈춘다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["WF1", "WF2", "root_lot_id", "lot_id", "lot_type", "yield", "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("yield:\n  WF1: wafer_no\n  WF2: wafer_no\n", encoding="utf-8")

    with pytest.raises(ValueError, match="wafer_no"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_optional_columns_blank_in_csv_become_null(tmp_path):
    """T7: 선택 컬럼(ppid, ch_id, defect_type)이 빈칸이면 DB 에 NULL 로 들어가야 한다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date",
                    "defect_type"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1", "lot_type": "PP",
                 "yield": "91.2", "date": "d", "defect_type": ""}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id", "ch_id", "ppid"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000",
                 "eqp_id": "E1", "ch_id": "", "ppid": ""}])

    yrs, srs = li.read_csv_records(yc, sc, "percent")
    db = tmp_path / "t.db"
    li.load(yrs, srs, db, verbose=False)

    conn = sqlite3.connect(db)
    defect = conn.execute("SELECT defect_type FROM yield").fetchone()[0]
    ch_id, ppid = conn.execute("SELECT ch_id, ppid FROM step_history").fetchone()
    conn.close()
    assert defect is None and ch_id is None and ppid is None


def _csv_args(yc, sc, db=None):
    argv = ["load_internal.py", "--yield-csv", str(yc), "--steps-csv", str(sc),
            "--yield-unit", "percent"]
    if db is not None:
        argv += ["--db", str(db)]
    return argv


def test_cli_csv_input_without_db_refuses_and_leaves_dummy_untouched(tmp_path, monkeypatch):
    """T8a: CSV 인자 + --db 미지정 → 기본값(더미 경로)로 떨어지면 안 되고 거부돼야 한다.

    행이 비어 있으면 거부와 무관하게(빈 추출은 fatal 이라) 교체가 안 되므로, 그것만으론
    이 가드를 검증하지 못한다(가드를 지워도 통과하는 공허한 테스트가 된다). 그래서 가드가
    없으면 실제로 적재·교체까지 성공할 유효한 행을 하나 넣는다.
    """
    fake_dummy = tmp_path / "dummy.db"
    monkeypatch.setattr(ya_config, "DB_PATH", fake_dummy)
    yc, sc = tmp_path / "yield.csv", tmp_path / "steps.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1", "lot_type": "PP",
                 "yield": "91.2", "date": "2026-01-01"}])
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}])
    monkeypatch.setattr(sys, "argv", _csv_args(yc, sc))

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2               # ap.error() 의 종료 코드
    assert not fake_dummy.exists()


def test_cli_csv_input_with_dummy_db_path_refuses(tmp_path, monkeypatch):
    """T8b: --db 를 더미 경로와 같은 값으로 명시해도 거부돼야 한다(--force 로도 못 넘김)."""
    fake_dummy = tmp_path / "dummy.db"
    monkeypatch.setattr(ya_config, "DB_PATH", fake_dummy)
    yc, sc = tmp_path / "yield.csv", tmp_path / "steps.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"], [])
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    argv = _csv_args(yc, sc, db=fake_dummy) + ["--force"]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code != 0
    assert not fake_dummy.exists()


def test_cli_csv_input_creates_tmp_db_via_subprocess(tmp_path):
    """T9: 정상 경로 — tmp CSV 두 개 → tmp DB 생성, 종료코드 0."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1", "lot_type": "PP",
                 "yield": "91.2", "date": "2026-01-01"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}])
    db = tmp_path / "case.db"

    proc = subprocess.run([sys.executable, "-m", "data.load_internal",
                           "--yield-csv", str(yc), "--steps-csv", str(sc),
                           "--yield-unit", "percent", "--db", str(db)],
                          capture_output=True, cwd=root)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert db.exists()


# --------------------------------------------------------------------------- #
# Opus 리뷰 지적 반영
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel_db", ["data/yield.db", "./data/yield.db"])
def test_dummy_db_guard_catches_relative_paths_too(tmp_path, monkeypatch, rel_db):
    """더미 DB 가드는 절대경로인 ya_config.DB_PATH 와 미해석 Path 로 비교하면
    "data/yield.db" 나 "./data/yield.db" 같은 상대경로를 못 잡는다 — repo 루트에서
    실행하면 조용히 뚫린다. resolve() 로 비교해야 한다.
    """
    fake_dummy = (tmp_path / "data" / "yield.db").resolve()
    fake_dummy.parent.mkdir()
    monkeypatch.setattr(ya_config, "DB_PATH", fake_dummy)
    monkeypatch.chdir(tmp_path)
    yc, sc = tmp_path / "yield.csv", tmp_path / "steps.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1", "lot_type": "PP",
                 "yield": "91.2", "date": "2026-01-01"}])
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}])
    monkeypatch.setattr(sys, "argv", _csv_args(yc, sc, db=rel_db))

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2
    assert not fake_dummy.exists()


def test_colmap_target_collides_with_passthrough_column_stops(tmp_path):
    """대응표가 만든 계약 키가 매핑 안 된 통과 컬럼과 같은 이름이면 컬럼 순서에 따라
    조용히 덮어써진다(마지막 값이 이긴다) — 멈춰야 한다.
    """
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["yield", "YLD_RATIO", "root_lot_id", "wafer_no", "lot_id",
                    "lot_type", "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("yield:\n  YLD_RATIO: yield\n", encoding="utf-8")

    with pytest.raises(ValueError, match="yield"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_colmap_creating_both_wafer_id_and_wafer_no_stops(tmp_path):
    """wafer_id 와 wafer_no 가 동시에 존재하면 _wafer_no() 가 wafer_no 를 조용히
    우선한다 — 대응표가 만들어낸 모호함이면 멈춰야 한다.
    """
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["wafer_id", "WF_NO", "root_lot_id", "lot_id", "lot_type", "yield",
                    "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("yield:\n  WF_NO: wafer_no\n", encoding="utf-8")

    with pytest.raises(ValueError, match="wafer_no"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_colmap_top_level_section_typo_stops(tmp_path):
    """대응표 최상위 섹션 이름 오타("step:" — 맞는 이름은 "steps:")를 조용히
    무시하면 그 대응은 통째로 안 먹히고 원천 컬럼명이 그대로 통과해 버린다.
    """
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("step:\n  EQP: eqp_id\n", encoding="utf-8")

    with pytest.raises(ValueError, match="step"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_colmap_list_form_yaml_stops(tmp_path):
    """대응표가 dict 가 아니라 list 로 파싱되면(형식 오류) 멈춘다."""
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("- yield\n- steps\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dict"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_colmap_mapping_target_not_a_contract_key_stops(tmp_path):
    """대응 대상 오타("CHAMBER: chid" — 맞는 계약 키는 "ch_id")를 조용히
    통과시키면 그 값은 아무도 안 읽는 자리에 실린다.
    """
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"], [])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id", "CHAMBER"], [])
    colmap = tmp_path / "map.yaml"
    colmap.write_text("steps:\n  CHAMBER: chid\n", encoding="utf-8")

    with pytest.raises(ValueError, match="chid"):
        li.read_csv_records(yc, sc, "percent", colmap=colmap)


def test_unstarted_steps_generator_does_not_lock_the_file(tmp_path):
    """yield 단계가 먼저 실패하면(예: lot_type 형식 위반) load() 는 step_history
    삽입까지 못 가므로 steps 제너레이터가 한 번도 안 돈다. 헤더 검증 때 열어 둔 핸들을
    끝까지 들고 있으면, Windows 에서 곧바로 그 파일을 지우거나 다시 쓰려 할 때
    WinError 32(사용 중)로 터진다 — 열기 자체를 제너레이터 소비 시점으로 미뤄야 한다.
    """
    yc = tmp_path / "yield.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"],
               [{"root_lot_id": "A1", "wafer_no": "1", "lot_id": "A1.1",
                 "lot_type": "PROD",  # 두 자리가 아님 -> transform_yield 단계에서 실패
                 "yield": "91.2", "date": "d"}])
    sc = tmp_path / "steps.csv"
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"],
               [{"root_lot_id": "A1", "wafer_no": "1", "step_seq": "CC002000", "eqp_id": "E1"}])

    yrs, srs = li.read_csv_records(yc, sc, "percent")
    with pytest.raises(ValueError):
        li.load(yrs, srs, tmp_path / "t.db", verbose=False)

    sc.unlink()   # 핸들이 남아 있으면 여기서 PermissionError(WinError 32)


def test_cli_yield_unit_without_csv_args_refuses(tmp_path, monkeypatch):
    """T7: --yield-unit 만 주고 --yield-csv/--steps-csv 를 안 주면 거부해야 한다
    (조용히 무시되고 _extract() 경로로 떨어지면 사용자가 오타를 못 알아챈다)."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    monkeypatch.setattr(sys, "argv", ["load_internal.py", "--yield-unit", "percent"])

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2


def test_cli_colmap_without_csv_args_refuses(tmp_path, monkeypatch):
    """T7: --colmap 만 주고 CSV 인자가 없으면 거부해야 한다."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    colmap = tmp_path / "map.yaml"
    colmap.write_text("yield: {}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["load_internal.py", "--colmap", str(colmap)])

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2
