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

B_YIELDS = [{"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
             "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}]
B_STEPS = [{"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
            "eqp_id": "ETCH9", "timestamp": "t"}]


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


def test_root_lot_id_survives_the_write_path(tmp_path):
    """lot 단위 삭제의 키다. DDL 에만 있고 INSERT 에서 빠지면 NOT NULL 위반으로
    적재가 죽거나(운이 좋으면), 조용히 틀린 lot 이 실린다."""
    db, _ = _load(tmp_path)
    conn = sqlite3.connect(db)
    rows = conn.execute("""SELECT DISTINCT wafer_id, root_lot_id FROM step_history
                           ORDER BY wafer_id""").fetchall()
    conn.close()
    assert rows == [("A45Z5_01", "A45Z5"), ("A45Z5_02", "A45Z5")]


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


def test_rebuild_takes_batches_so_the_caller_need_not_hold_everything(tmp_path):
    """전체 재적재도 청크로 받는다. 호출부가 2,800만 행을 한 리스트로 들면
    적재 내내 그 리스트가 살아 있어 메모리가 32GB 까지 오른다(사내 실측)."""
    b1 = ([YIELDS[0]], [STEPS[0]])
    b2 = ([YIELDS[1]], [STEPS[1], STEPS[2]])
    report = li.rebuild([b1, b2], tmp_path / "t.db", verbose=False)

    assert report["n_yield"] == 2 and report["n_steps"] == 3
    assert report["swapped"] and not report["fatal"]


def test_chunked_splits_a_lot_list_into_fixed_size_pieces():
    assert [len(c) for c in li._chunked(list(range(45)), 20)] == [20, 20, 5]
    assert list(li._chunked([], 20)) == []


def _counts(db):
    conn = sqlite3.connect(db)
    try:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("yield", "step_history"))
    finally:
        conn.close()


def _seed(tmp_path):
    """A45Z5 lot 이 이미 적재된 DB."""
    db = tmp_path / "t.db"
    li.load(YIELDS, STEPS, db, verbose=False)
    return db


def test_reloading_the_same_lot_does_not_duplicate_rows(tmp_path):
    """멱등성. 그냥 INSERT 하면 이력이 두 벌이 되고 commonality 는 에러 없이
    분모가 두 배가 된 채 계산한다 - 재작업 행과 구분이 안 돼 눈에도 안 띈다."""
    db = _seed(tmp_path)
    before = _counts(db)

    report = li.load_incremental([(["A45Z5"], YIELDS, STEPS)], db, verbose=False)

    assert _counts(db) == before
    assert report["committed"] and not report["fatal"]


def test_rework_history_replaces_the_old_rows(tmp_path):
    """재작업으로 이력이 늘면 새 내용으로 통째로 대체된다."""
    db = _seed(tmp_path)
    reworked = STEPS + [{"root_lot_id": "A45Z5", "wafer_id": "01",
                         "step_seq": "CC002000", "area": "Etch", "eqp_id": "ETCH9",
                         "ch_id": "C", "ppid": "PPID_R", "timestamp": "t2"}]

    li.load_incremental([(["A45Z5"], YIELDS, reworked)], db, verbose=False)

    assert _counts(db) == (2, 4)          # 옛 3행이 남으면 7


def test_a_failure_mid_load_leaves_the_db_untouched(tmp_path):
    """추출이 중간에 죽어도 어제 상태로 돌아가야 한다.

    전체 재적재는 tmp 파일 + os.replace 가 이걸 보장했다. 증분은 살아 있는 DB 를
    고치므로 그 보장을 트랜잭션이 대신한다.

    죽기 전에 처리하는 청크는 seed 에 없는 **새 root_lot**(C88C8)이어야 한다. seed 와
    같은 lot·같은 내용을 다시 넣으면 삭제 후 재삽입 결과가 원본과 바이트 단위로
    같아져서, 커밋되든 롤백되든 행 수가 그대로다 - 이 단언이 둘을 구별하지 못하게 된다.
    """
    db = _seed(tmp_path)
    before = _counts(db)

    new_yield = [{"root_lot_id": "C88C8", "wafer_id": "01", "lot_id": "C88C8.1",
                 "lot_type": "PP", "yield": 70.0, "date": "2026-07-02"}]
    new_steps = [{"root_lot_id": "C88C8", "wafer_id": "01", "step_seq": "CC002000",
                 "eqp_id": "ETCH9", "timestamp": "t"}]

    def dying_chunks():
        yield (["C88C8"], new_yield, new_steps)      # 한 청크는 적용된 뒤
        raise RuntimeError("추출 중단")

    try:
        li.load_incremental(dying_chunks(), db, verbose=False)
    except RuntimeError:
        pass
    else:
        raise AssertionError("예외가 전파되지 않았다")

    assert _counts(db) == before


def test_a_broken_batch_is_blocked_even_though_the_db_is_mostly_clean(tmp_path):
    """이번 배치의 고아를 전역 비율로 재면 기존 데이터가 희석해 못 잡는다.

    아래 배치는 wafer 3장 중 2장이 고아(yield 없음)라 그 자체로는 0.67 이지만,
    DB 전체로 세면 5장 중 2장(0.4)이라 임계 0.5 를 안 넘는다.
    """
    db = _seed(tmp_path)                       # A45Z5 wafer 2장, 고아 없음
    orphans = B_STEPS + [
        {"root_lot_id": "B77B7", "wafer_id": "09", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        {"root_lot_id": "B77B7", "wafer_id": "10", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"}]

    report = li.load_incremental([(["B77B7"], B_YIELDS, orphans)], db, verbose=False)

    assert report["fatal"] and not report["committed"]
    assert any("고아" in f for f in report["fatal"])   # 어느 검사가 잡았는지
    assert _counts(db) == (2, 3)               # 원래 상태 그대로


def test_old_orphans_do_not_block_a_clean_batch(tmp_path):
    """반대 방향. 기존 데이터에 고아가 있어도 이번 배치가 깨끗하면 통과한다."""
    db = tmp_path / "t.db"
    dirty = STEPS + [{"root_lot_id": "A45Z5", "wafer_id": "77",
                      "step_seq": "CC002000", "eqp_id": "ETCH9", "timestamp": "t"}]
    li.load(YIELDS, dirty, db, verbose=False)  # 고아 1장이 이미 들어 있는 DB

    report = li.load_incremental([(["B77B7"], B_YIELDS, B_STEPS)], db, verbose=False)

    assert report["committed"] and not report["fatal"]


def test_incremental_report_correctly_labels_a_committed_load(tmp_path, monkeypatch):
    """증분 커밋 성공을 '교체 안 함'으로 잘못 찍으면 안 된다.

    `_print` 가 `r.get("swapped")` 로만 분기하면, 증분 report 에는 그 키가 없어 매번
    이 분기를 타서 커밋에 성공해도 항상 "[교체 안 함] ... 기존 상태 유지" 를 찍는다.
    성공한 적재를 실패로 읽게 만드는 조용한 거짓말이라 verbose=True 실사용 경로를
    실제로 돌려서 잠근다 (다른 신규 테스트는 전부 verbose=False 라 이 버그를 못 잡는다).
    """
    db = _seed(tmp_path)
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)

    report = li.load_incremental([(["B77B7"], B_YIELDS, B_STEPS)], db, verbose=True)
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert report["committed"] and not report["fatal"]
    assert "[커밋]" in out
    assert "[교체 안 함]" not in out
    assert "[증분]" in out
    assert "[전체]" in out


def test_a_lot_id_typed_differently_in_the_two_sources_is_blocked(tmp_path):
    """원천이 yield 와 step_history 에 lot 을 다른 표기로 실으면 막혀야 한다.

    yield 는 root_lot_id="B77B7" 로, step_history 는 같은 wafer 를 "C88C8" 로
    싣는(오타·다른 표기 체계) 상황을 흉내낸다. transform_steps 는 wafer_id 를
    그 레코드의 root_lot_id 값으로 직접 합성하므로(`build_wafer_id`), 표기가
    갈리면 합성된 wafer_id 자체가 갈려("B77B7_01" vs "C88C8_01") 조인이 깨진다.

    이걸 잡는 것은 **고아/이력없음 검사**다 (root_lot_id 컬럼 자기 정합성 검사가
    아니다 - 그건 같은 소스 값에서 wafer_id 와 root_lot_id 를 둘 다 만들기 때문에
    구조적으로 항상 참이라 이 종류의 사고를 못 잡는다). yield 의 "B77B7_01" 은
    매칭되는 step 이 없어 "이력 없는 wafer" 로 잡혀 증분 적재가 커밋되지 않는다.
    나중에 다른 이유로 우연히 통과하지 않도록 fatal 메시지에 그 검사의 서명이
    있는지까지 확인한다.
    """
    db = _seed(tmp_path)
    mismatched_steps = [{"root_lot_id": "C88C8", "wafer_id": "01",
                         "step_seq": "CC002000", "eqp_id": "ETCH9", "timestamp": "t"}]
    before = _counts(db)

    report = li.load_incremental([(["B77B7"], B_YIELDS, mismatched_steps)], db,
                                 verbose=False)

    assert report["fatal"] and not report["committed"]
    assert any("step_history 없는" in f for f in report["fatal"])
    assert _counts(db) == before


def test_a_lot_typed_differently_from_the_request_is_blocked(tmp_path):
    """요청한 lot 과 실제로 실려 온 lot 의 표기가 다르면 막혀야 한다.

    고정폭 CHAR 원천의 뒤 공백이 이 사고의 가장 흔한 모양이다("CC002000 " 이
    commonality 를 두 군으로 쪼갠 전례가 있다 - `test_padded_step_seq_...` 참조).
    root_lot_id 도 같은 사고에 노출돼 있는데, 이번 배치는 요청("B77B7")과 다른
    표기("B77B7 ", 뒤 공백)로 yield·step 이 **같이** 실려 온다.

    이 행들은 다른 어떤 검사에도 안 걸린다: yield 와 step 이 같은(틀린) 표기로
    함께 오므로 자기들끼리는 완전히 정합적이다 - wafer_id 가 서로 조인되고
    (orphan·no_hist 통과), root_lot_id 컬럼도 자기 wafer_id 접두와 일치한다
    (검사 2 통과). `_scope` 는 요청한 lot("B77B7")으로만 채워지므로, 실려 온
    표기("B77B7 ")는 `_in_scope()` 자체를 통과 못 해 검사 1~6 의 그 어떤 SELECT
    에도 안 잡히고 조용히 스코프 밖으로 빠진다. `DELETE ... WHERE root_lot_id
    IN ("B77B7")` 도 이 표기를 못 지우므로, 걸러내지 않으면 재적재마다 누적된다.
    """
    db = _seed(tmp_path)
    stray_yield = [{"root_lot_id": "B77B7 ", "wafer_id": "01", "lot_id": "B77B7.1",
                    "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}]
    stray_steps = [{"root_lot_id": "B77B7 ", "wafer_id": "01", "step_seq": "CC002000",
                    "eqp_id": "ETCH9", "timestamp": "t"}]
    before = _counts(db)

    report = li.load_incremental([(["B77B7"], stray_yield, stray_steps)], db,
                                 verbose=False)

    assert report["fatal"] and not report["committed"]
    assert any("요청하지 않은 root_lot" in f for f in report["fatal"])
    assert _counts(db) == before


def test_a_stray_lot_seen_only_in_yield_is_still_caught(tmp_path):
    """yield 쪽 `_collect_lots` 가 빠지면 못 잡는 사고를 경로별로 좁혀 확인한다.

    옛 테스트(`..._typed_differently_from_the_request_is_blocked`)는 yield·step
    양쪽에 동시에 어긋난 표기를 보내서, 둘 중 한쪽 감시만 남아도 통과해 버렸다
    (한쪽이 죽어도 다른 쪽이 잡는다). 여기서는 **yield 에만** 표기가 어긋난
    wafer 를 하나 섞는다(부분 불일치 - wafer 1장은 정상, 1장만 "B77B7 ").
    이 "B77B7 " 표기는 `_scope`(요청 lot "B77B7")밖이라 고아/이력없음 검사의
    SELECT 자체에 안 잡힌다 — 잡히는 유일한 경로는 stray 비교(seen_lots)뿐이다.
    """
    db = _seed(tmp_path)
    stray_yield = [
        {"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
         "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"},
        {"root_lot_id": "B77B7 ", "wafer_id": "02", "lot_id": "B77B7.1",
         "lot_type": "PP", "yield": 70.0, "date": "2026-08-01"},
    ]
    normal_steps = [
        {"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        {"root_lot_id": "B77B7", "wafer_id": "02", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
    ]
    before = _counts(db)

    report = li.load_incremental([(["B77B7"], stray_yield, normal_steps)], db,
                                 verbose=False)

    assert report["fatal"] and not report["committed"]
    # G2: 전역 stray 검사는 없어지고 청크 검사만 남았다 - 청크 메시지 전용 문구로 좁힌다.
    assert any("이 청크가 요청하지 않은" in f for f in report["fatal"])
    assert _counts(db) == before


def test_a_stray_lot_seen_only_in_steps_is_still_caught(tmp_path):
    """위 테스트의 반대 경로. step 쪽 `_collect_lots` 만 남아도 잡혀야 한다.

    여기서는 **step 에만** "B77B7 " wafer 를 하나 섞는다(부분 불일치 - wafer 1장은
    정상, 1장만 어긋난 표기). yield 쪽은 전부 정상 표기라 위 테스트와 독립적으로,
    step 쪽 `_collect_lots` 가 빠지면 이 테스트만 죽어야 한다.
    """
    db = _seed(tmp_path)
    normal_yield = [
        {"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
         "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"},
        {"root_lot_id": "B77B7", "wafer_id": "02", "lot_id": "B77B7.1",
         "lot_type": "PP", "yield": 70.0, "date": "2026-08-01"},
    ]
    stray_steps = [
        {"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        {"root_lot_id": "B77B7 ", "wafer_id": "02", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
    ]
    before = _counts(db)

    report = li.load_incremental([(["B77B7"], normal_yield, stray_steps)], db,
                                 verbose=False)

    assert report["fatal"] and not report["committed"]
    # G2: 전역 stray 검사는 없어지고 청크 검사만 남았다 - 청크 메시지 전용 문구로 좁힌다.
    assert any("이 청크가 요청하지 않은" in f for f in report["fatal"])
    assert _counts(db) == before


def test_rollback_report_does_not_print_a_misleading_total_line(tmp_path, monkeypatch):
    """롤백된 배치의 [전체] 줄이 곧 되돌려질 수치를 확정된 것처럼 찍으면 안 된다.

    validate() 는 커밋 전에 돌므로 이 시점의 COUNT(*) 는 아직 커밋 안 된 이번
    배치의 변경을 포함한다. 그대로 찍으면 롤백돼 사라질 수치가 사람 눈에는
    확정된 것처럼 보인다.
    """
    db = _seed(tmp_path)
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)

    orphans = B_STEPS + [
        {"root_lot_id": "B77B7", "wafer_id": "09", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        {"root_lot_id": "B77B7", "wafer_id": "10", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"}]
    report = li.load_incremental([(["B77B7"], B_YIELDS, orphans)], db, verbose=True)
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert report["fatal"] and not report["committed"]
    assert "[되돌림]" in out
    assert "[전체] yield" not in out            # 라벨 없는 [전체] 줄은 찍히면 안 된다
    assert "[전체](롤백 전)" in out


def test_commit_failure_still_closes_the_connection_and_keeps_the_original_error(
        tmp_path, monkeypatch):
    """COMMIT 실패는 락 경합 등으로 라이브 DB 경로에서 현실적으로 일어난다.

    connection 이 안 닫히면 다음 실행이 잠금을 못 얻는다. 그리고 정리 차 다시
    시도하는 ROLLBACK 이 실패해도, 사람이 봐야 할 원래 실패 사유(COMMIT 실패)가
    가려지면 안 된다.
    """
    db = _seed(tmp_path)

    class _FailingCommitConn:
        """COMMIT 만 가로채 실패시키고 나머지는 실제 connection 에 그대로 위임한다."""

        def __init__(self, real):
            object.__setattr__(self, "_real", real)
            object.__setattr__(self, "closed", False)

        def __getattr__(self, name):
            return getattr(self._real, name)

        def __setattr__(self, name, value):
            if name == "closed":
                object.__setattr__(self, name, value)
            else:
                setattr(self._real, name, value)

        def execute(self, sql, *a):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("database is locked")
            return self._real.execute(sql, *a)

        def close(self):
            object.__setattr__(self, "closed", True)
            self._real.close()

    real_connect = sqlite3.connect
    holder = {}

    def fake_connect(path):
        w = _FailingCommitConn(real_connect(path))
        holder["conn"] = w
        return w

    monkeypatch.setattr(li.sqlite3, "connect", fake_connect)

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        li.load_incremental([(["A45Z5"], YIELDS, STEPS)], db, verbose=False)

    assert holder["conn"].closed


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


# --------------------------------------------------------------------------- #
# Task 5 - 실행 모드와 lot 청크 추출 계약 (--rebuild/--since/--lots/--yield-csv)
# --------------------------------------------------------------------------- #
def test_extraction_runs_once_per_chunk(tmp_path, monkeypatch):
    """전량을 한 번에 안 받는다. 이것이 메모리 유계의 실질 보증이다 -
    한 번만 부르면 사내 lib 가 2,800만 행을 통째로 만들어 32GB 를 쓴다."""
    db = _seed(tmp_path)
    seen = []

    def fake_extract(chunk):
        seen.append(list(chunk))
        return [], []

    monkeypatch.setattr(li, "_extract", fake_extract)
    monkeypatch.setattr(ya_config, "LOAD_LOT_CHUNK", 20)

    lots = [f"L{i:03d}" for i in range(45)]
    # force=True: 이 가짜 추출은 yield 0행이라 정상적으로 fatal 이 난다.
    # 여기서 보는 것은 적재 결과가 아니라 호출 분할이다.
    li._run_incremental(lots, db, force=True, verbose=False)

    assert [len(c) for c in seen] == [20, 20, 5]
    assert seen[0] == lots[:20]


def test_an_empty_lot_list_ends_normally_without_touching_the_db(tmp_path, monkeypatch):
    """주말·비가동으로 대상이 0개인 것은 정상이다.

    이 분기가 없으면 검사 0번("yield 0행: 추출 결과가 비었다")이 매번 치명적
    오류로 뜨고, 사람이 그 경보를 무시하기 시작하면 진짜 추출 장애도 같이 묻힌다.
    """
    db = _seed(tmp_path)
    before = _counts(db)
    monkeypatch.setattr(li, "_extract_lot_ids", lambda since: [])
    monkeypatch.setattr(sys, "argv",
                        ["load_internal", "--since", "7", "--db", str(db)])

    try:
        li.main()
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("SystemExit 가 나지 않았다")

    assert _counts(db) == before


def test_a_mode_must_be_given_explicitly():
    """인자 없이 실행하면 전체 재적재가 조용히 도는 것을 막는다."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, "-m", "data.load_internal"],
                          capture_output=True, cwd=root)
    assert proc.returncode != 0
    assert b"--rebuild" in proc.stderr or b"--since" in proc.stderr


def test_cli_csv_and_incremental_modes_together_refuse(tmp_path, monkeypatch):
    """D1: CSV 모드(--yield-csv)는 증분 모드와 같은 상호배타 그룹에 있다 - 함께
    주면(예: --since 와 --yield-csv) 어느 쪽으로도 조용히 정해지지 않고 멈춘다."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    yc, sc = tmp_path / "yield.csv", tmp_path / "steps.csv"
    _write_csv(yc, ["root_lot_id", "wafer_no", "lot_id", "lot_type", "yield", "date"], [])
    _write_csv(sc, ["root_lot_id", "wafer_no", "step_seq", "eqp_id"], [])
    argv = ["load_internal.py", "--since", "7", "--yield-csv", str(yc),
            "--steps-csv", str(sc), "--yield-unit", "percent"]
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2


def test_cli_csv_only_option_with_a_non_csv_mode_refuses(tmp_path, monkeypatch):
    """CSV 전용 옵션(--yield-unit 등)을 --yield-csv 없이 다른 모드와 섞으면 멈춘다 -
    조용히 무시되면 오타를 낸 사용자가 CSV 경로를 탄다고 착각한다."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    monkeypatch.setattr(sys, "argv",
                        ["load_internal.py", "--since", "7", "--yield-unit", "percent"])

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2


def test_a_stray_lot_carried_from_an_earlier_chunk_is_caught_per_chunk(tmp_path):
    """F5: 전체 실행 단위로만 stray 를 비교하면, 청크 2 가 청크 1 의 lot 을 실어
    오는 사고를 못 잡는다 - 그 lot 은 청크 1 에서 이미 requested_lots 에 들어가
    있어 "요청 안 한 lot" 이 아니게 된다. 청크 단위 비교라야 잡힌다.
    """
    db = _seed(tmp_path)
    chunk1_yield = [{"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
                     "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}]
    chunk1_steps = [{"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
                     "eqp_id": "ETCH9", "timestamp": "t"}]
    chunk2_yield = [{"root_lot_id": "C88C8", "wafer_id": "01", "lot_id": "C88C8.1",
                     "lot_type": "PP", "yield": 70.0, "date": "2026-08-02"}]
    # 청크 2 는 C88C8 만 요청했는데, step 이력에 청크 1 의 B77B7 행이 다시 섞여 온다
    chunk2_steps = [{"root_lot_id": "C88C8", "wafer_id": "01", "step_seq": "CC002000",
                     "eqp_id": "ETCH9", "timestamp": "t"},
                    {"root_lot_id": "B77B7", "wafer_id": "02", "step_seq": "CC004000",
                     "eqp_id": "CMP1", "timestamp": "t2"}]

    report = li.load_incremental(
        [(["B77B7"], chunk1_yield, chunk1_steps),
         (["C88C8"], chunk2_yield, chunk2_steps)], db, verbose=False)

    assert report["fatal"] and not report["committed"]
    assert any("청크가 요청하지 않은 root_lot" in f for f in report["fatal"])


def test_incremental_report_counts_requested_lots_that_delivered_zero_rows(tmp_path):
    """F6: 요청했으나 0행으로 돌아온 lot 은 fatal 이 아니라 보고용 카운트로만
    남는다 - 원천에서 사라진 lot(예: 취소·보류)은 그 자체로 비정상이 아니다."""
    db = _seed(tmp_path)

    report = li.load_incremental(
        [(["B77B7", "Z00Z0"], B_YIELDS, B_STEPS)], db, verbose=False)

    assert report["committed"] and not report["fatal"]
    assert report["n_zero_row_lots"] == 1
    assert report["zero_row_lots"] == ["Z00Z0"]


# --------------------------------------------------------------------------- #
# Task 5 Opus 재리뷰 - 닫힌 목록 G1~G9 (plan.md "Task 5 리뷰 결과와 결정")
# --------------------------------------------------------------------------- #
class _CloseTrackingConn:
    """실제 connection 을 감싸 close() 호출 여부만 관측한다. execute 는 서브클래스가
    필요한 SQL 만 가로채고 나머지는 실제 connection 에 위임한다."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "closed", False)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name == "closed":
            object.__setattr__(self, name, value)
        else:
            setattr(self._real, name, value)

    def close(self):
        object.__setattr__(self, "closed", True)
        self._real.close()


def test_g1_outer_rollback_failure_does_not_mask_the_original_error(tmp_path, monkeypatch):
    """G1: validate() 이전 실패에서도 COMMIT 실패 경로와 같은 모양을 쓴다.

    SQLite 가 SQLITE_FULL/IOERR 류로 트랜잭션을 스스로 이미 되돌려 놓은 상황을
    흉내낸다(validate 를 가짜로 바꿔 그 안에서 직접 ROLLBACK 한 뒤 예외를 던짐).
    바깥 except 가 정리 차 다시 시도하는 ROLLBACK 은 "트랜잭션 없음" 으로 실패하는데,
    이 새 예외가 원래 실패 사유(ORIGINAL)를 가리면 안 되고 connection 은 닫혀야 한다.
    """
    db = _seed(tmp_path)

    def bad_validate(conn, *a, **k):
        conn.execute("ROLLBACK")          # SQLite 가 스스로 되돌린 상황을 흉내
        raise ValueError("ORIGINAL")

    monkeypatch.setattr(li, "validate", bad_validate)

    real_connect = sqlite3.connect
    holder = {}

    def fake_connect(path):
        w = _CloseTrackingConn(real_connect(path))
        holder["conn"] = w
        return w

    monkeypatch.setattr(li.sqlite3, "connect", fake_connect)

    with pytest.raises(ValueError, match="ORIGINAL"):
        li.load_incremental([(["B77B7"], B_YIELDS, B_STEPS)], db, verbose=False)

    assert holder["conn"].closed


def test_g2_a_yield_lot_leaked_from_an_earlier_chunk_is_caught_per_chunk(tmp_path):
    """G2: step 쪽 누수(F5)의 대칭 - yield 쪽도 앞 청크의 lot 이 새 나오면 잡혀야
    한다. 청크 2 는 C88C8 만 요청했는데 yield 스트림에 청크 1 의 B77B7 행이
    다시 섞여 온다."""
    db = _seed(tmp_path)
    chunk1_yield = [{"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
                     "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}]
    chunk1_steps = [{"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
                     "eqp_id": "ETCH9", "timestamp": "t"}]
    chunk2_yield = [
        {"root_lot_id": "C88C8", "wafer_id": "01", "lot_id": "C88C8.1",
         "lot_type": "PP", "yield": 70.0, "date": "2026-08-02"},
        {"root_lot_id": "B77B7", "wafer_id": "02", "lot_id": "B77B7.1",
         "lot_type": "PP", "yield": 60.0, "date": "2026-08-02"},
    ]
    chunk2_steps = [{"root_lot_id": "C88C8", "wafer_id": "01", "step_seq": "CC002000",
                     "eqp_id": "ETCH9", "timestamp": "t"}]

    report = li.load_incremental(
        [(["B77B7"], chunk1_yield, chunk1_steps),
         (["C88C8"], chunk2_yield, chunk2_steps)], db, verbose=False)

    assert report["fatal"] and not report["committed"]
    assert any("이 청크가 요청하지 않은" in f for f in report["fatal"])


def test_g3_rebuild_extraction_runs_once_per_chunk(tmp_path, monkeypatch):
    """G3: --rebuild 경로도 lot 을 청크로 나눠 _extract 를 부른다
    (test_extraction_runs_once_per_chunk 의 rebuild 판)."""
    db = tmp_path / "t.db"
    seen = []

    def fake_extract(chunk):
        seen.append(list(chunk))
        return [], []

    lots = [f"L{i:03d}" for i in range(45)]
    monkeypatch.setattr(li, "_extract_lot_ids", lambda since: lots)
    monkeypatch.setattr(li, "_extract", fake_extract)
    monkeypatch.setattr(ya_config, "LOAD_LOT_CHUNK", 20)
    monkeypatch.setattr(sys, "argv",
                        ["load_internal.py", "--rebuild", "--db", str(db), "--force"])

    try:
        li.main()
    except SystemExit:
        pass

    assert [len(c) for c in seen] == [20, 20, 5]
    assert seen[0] == lots[:20]


def test_g4_rollback_report_does_not_print_misleading_deleted_counts(tmp_path, monkeypatch):
    """G4: 롤백된 배치의 [증분] 삭제 행수도 [전체] 줄(F2)과 같은 문제다 - 곧
    되돌려질 DELETE 결과를 확정된 것처럼 찍으면 안 된다."""
    db = _seed(tmp_path)
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)

    orphans = B_STEPS + [
        {"root_lot_id": "B77B7", "wafer_id": "09", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        {"root_lot_id": "B77B7", "wafer_id": "10", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"}]
    report = li.load_incremental([(["B77B7"], B_YIELDS, orphans)], db, verbose=True)
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert report["fatal"] and not report["committed"]
    assert "[증분] 대상 lot" not in out            # 라벨 없는 [증분] 줄은 찍히면 안 된다
    assert "[증분](롤백 전) 대상 lot" in out


def test_g5_negative_since_refuses(tmp_path, monkeypatch):
    """G5: 음수 N 은 "오늘 - (-N)일" 로 미래 날짜가 된다 - 거의 항상 부호 실수다."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    monkeypatch.setattr(sys, "argv", ["load_internal.py", "--since", "-3"])

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2


def test_g6_lots_with_only_whitespace_and_commas_refuses(tmp_path, monkeypatch):
    """G6: --lots 는 사람이 직접 타이핑한 값이다 - 공백·쉼표만 있어 결과가
    비면 --since 가 0개를 찾는 것과 달리 거의 항상 입력 실수다."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    monkeypatch.setattr(sys, "argv", ["load_internal.py", "--lots", " , ,"])

    with pytest.raises(SystemExit) as exc:
        li.main()
    assert exc.value.code == 2


def test_g7_incremental_dummy_warning_says_lot_scoped_not_replaced(tmp_path, monkeypatch):
    """G7: 증분 모드(--since/--lots)의 더미 경고는 "대체" 가 아니라 lot 단위
    갱신임을 말해야 한다. --rebuild 는 "대체" 문구 그대로 유지."""
    monkeypatch.setattr(ya_config, "DB_PATH", tmp_path / "dummy.db")
    monkeypatch.setattr(li, "_extract_lot_ids", lambda since: [])
    monkeypatch.setattr(sys, "argv", ["load_internal.py", "--since", "7"])
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)

    with pytest.raises(SystemExit):
        li.main()
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert "대체됩니다" not in out
    assert "대상 lot 만 갱신됩니다" in out


def test_g8_cleanup_rollback_failure_does_not_mask_the_commit_error(tmp_path, monkeypatch):
    """G8: COMMIT 도 실패하고, 정리 차 재시도하는 ROLLBACK 도 실패하는 분기.
    F4 의 내부 try/except(정리용 ROLLBACK 보호)가 없으면 두 번째 실패가 첫 번째
    실패(COMMIT, 사람이 봐야 할 진짜 사유)를 가린다."""
    db = _seed(tmp_path)

    class _FailingCommitAndRollbackConn(_CloseTrackingConn):
        def execute(self, sql, *a):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("database is locked")
            if sql == "ROLLBACK":
                raise sqlite3.OperationalError("cannot rollback - no transaction is active")
            return self._real.execute(sql, *a)

    real_connect = sqlite3.connect
    holder = {}

    def fake_connect(path):
        w = _FailingCommitAndRollbackConn(real_connect(path))
        holder["conn"] = w
        return w

    monkeypatch.setattr(li.sqlite3, "connect", fake_connect)

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        li.load_incremental([(["A45Z5"], YIELDS, STEPS)], db, verbose=False)

    assert holder["conn"].closed


def test_g9_committed_zero_row_line_says_it_was_deleted(tmp_path, monkeypatch):
    """G9: 커밋된 경우 0행 lot 줄은 추측("사라진 lot 일 수 있다")에 그치지 않고
    이번 커밋으로 실제 지워졌다는 사실을 덧붙인다."""
    db = _seed(tmp_path)
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)

    report = li.load_incremental(
        [(["B77B7", "Z00Z0"], B_YIELDS, B_STEPS)], db, verbose=True)
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert report["committed"] and not report["fatal"]
    assert "이번 커밋으로 DB 에서 지워졌다" in out


# --------------------------------------------------------------------------- #
# 최종 리뷰 - 닫힌 목록 H1~H7 (plan.md "최종 리뷰 결과와 결정") - H2
# --------------------------------------------------------------------------- #
def test_h2_rebuild_chunk_stray_blocks_the_swap(tmp_path):
    """H2: --rebuild 도 load_incremental 과 같은 청크 단위 요청 대 납품 검사를
    한다. 청크 2 는 B77B7 만 요청했는데 청크 1(A45Z5)의 step 행이 다시 섞여
    오면(추출 파이프라인이 청크 경계를 못 지킨 버그) swap 하면 안 된다.
    """
    chunk1_yield = [{"root_lot_id": "A45Z5", "wafer_id": "01", "lot_id": "A45Z5.1",
                     "lot_type": "PP", "yield": 91.2, "date": "2026-07-01"}]
    chunk1_steps = [{"root_lot_id": "A45Z5", "wafer_id": "01", "step_seq": "CC002000",
                     "eqp_id": "ETCH9", "timestamp": "t"}]
    chunk2_yield = [{"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
                     "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}]
    chunk2_steps = [
        {"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
        # 청크 1(A45Z5)의 step 행이 청크 2 에 다시 실려 온다 - 청크 2 는 B77B7 만 요청했다
        {"root_lot_id": "A45Z5", "wafer_id": "01", "step_seq": "CC002000",
         "eqp_id": "ETCH9", "timestamp": "t"},
    ]
    batches = [
        (["A45Z5"], chunk1_yield, chunk1_steps),
        (["B77B7"], chunk2_yield, chunk2_steps),
    ]

    report = li.rebuild(batches, tmp_path / "t.db", verbose=False)

    assert not report["swapped"]
    assert any("이 청크가 요청하지 않은" in f for f in report["fatal"])


def test_h2_rebuild_cli_passes_chunk_lots_so_a_leak_blocks_the_swap(tmp_path, monkeypatch):
    """H2 배선: `--rebuild` CLI 가 청크 lot 목록을 rebuild() 에 넘겨야 위 검사가
    실제로 돈다. 옛 2-튜플로 되돌리면 rebuild 는 요청 lot 을 몰라 누수를 그대로
    교체하는데, 호출 횟수만 보는 G3 테스트로는 이것이 안 잠긴다."""
    db = tmp_path / "t.db"
    rows = {
        "A45Z5": ([{"root_lot_id": "A45Z5", "wafer_id": "01", "lot_id": "A45Z5.1",
                    "lot_type": "PP", "yield": 91.2, "date": "2026-07-01"}],
                  [{"root_lot_id": "A45Z5", "wafer_id": "01", "step_seq": "CC002000",
                    "eqp_id": "ETCH9", "timestamp": "t"}]),
        "B77B7": ([{"root_lot_id": "B77B7", "wafer_id": "01", "lot_id": "B77B7.1",
                    "lot_type": "PP", "yield": 88.0, "date": "2026-08-01"}],
                  [{"root_lot_id": "B77B7", "wafer_id": "01", "step_seq": "CC002000",
                    "eqp_id": "ETCH9", "timestamp": "t"},
                   # 청크 2 가 청크 1(A45Z5)의 step 행을 다시 실어 온다
                   {"root_lot_id": "A45Z5", "wafer_id": "01", "step_seq": "CC002000",
                    "eqp_id": "ETCH9", "timestamp": "t"}]),
    }
    monkeypatch.setattr(li, "_extract_lot_ids", lambda since: ["A45Z5", "B77B7"])
    monkeypatch.setattr(li, "_extract", lambda chunk: rows[chunk[0]])
    monkeypatch.setattr(ya_config, "LOAD_LOT_CHUNK", 1)
    monkeypatch.setattr(sys, "argv", ["load_internal.py", "--rebuild", "--db", str(db)])

    with pytest.raises(SystemExit) as exc:
        li.main()

    assert exc.value.code == 1
    assert not db.exists()


def test_h2_rebuild_without_lot_lists_is_unaffected(tmp_path):
    """H2 대칭: load()/CSV 경로가 쓰는 기존 2-튜플 계약은 청크 검사 없이 그대로
    동작해야 한다(요청 lot 개념이 없다)."""
    report = li.load(YIELDS, STEPS, tmp_path / "t.db", verbose=False)

    assert report["swapped"] and not report["fatal"]
