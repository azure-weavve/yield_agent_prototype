"""사내 적재 왕복 — transform → INSERT 경로가 실제로 도는지.

계약 테스트(test_schema_contract.py)는 **DDL 만** 동결한다. 그래서 DDL 에 컬럼이
있어도 transform_steps 나 INSERT 에서 빠뜨리면 계약은 green 인데 적재된 값은
전부 NULL 이 된다 — hyp_ppid_commonality 가 에러 없이 후보 0 으로 끝나는,
계약 테스트가 막으려던 것과 똑같은 모양의 조용한 실패다. 그 구멍을 메운다.
"""

import io
import os
import sqlite3
import subprocess
import sys

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
