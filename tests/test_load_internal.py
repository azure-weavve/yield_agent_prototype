"""사내 적재 왕복 — transform → INSERT 경로가 실제로 도는지.

계약 테스트(test_schema_contract.py)는 **DDL 만** 동결한다. 그래서 DDL 에 컬럼이
있어도 transform_steps 나 INSERT 에서 빠뜨리면 계약은 green 인데 적재된 값은
전부 NULL 이 된다 — hyp_ppid_commonality 가 에러 없이 후보 0 으로 끝나는,
계약 테스트가 막으려던 것과 똑같은 모양의 조용한 실패다. 그 구멍을 메운다.
"""

import io
import sqlite3
import sys

from data import load_internal as li

YIELDS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "lot_id": "A45Z5.1",
           "yield": 91.2, "date": "2026-07-01"},
          {"root_lot_id": "A45Z5", "wafer_id": "02", "lot_id": "A45Z5.1",
           "yield": 62.0, "date": "2026-07-01"}]

STEPS = [{"root_lot_id": "A45Z5", "wafer_id": "01", "process_step": "Etch",
          "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_Y", "timestamp": "t"},
         {"root_lot_id": "A45Z5", "wafer_id": "02", "process_step": "Etch",
          "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_X", "timestamp": "t"},
         # ch_id·ppid 없는 원천 (단일 챔버 설비·PPID 개념 없는 스텝)
         {"root_lot_id": "A45Z5", "wafer_id": "02", "process_step": "CMP",
          "eqp_id": "CMP1", "timestamp": "t"}]


def _load(tmp_path):
    db = tmp_path / "t.db"
    report = li.load(YIELDS, STEPS, db, verbose=False)
    return db, report


def test_step_columns_survive_the_write_path(tmp_path):
    """DDL 에만 있고 INSERT 에서 빠지는 일이 없어야 한다."""
    db, _ = _load(tmp_path)
    conn = sqlite3.connect(db)
    rows = conn.execute("""SELECT wafer_id, eqp_id, ch_id, ppid FROM step_history
                           ORDER BY wafer_id, process_step""").fetchall()
    conn.close()
    assert rows == [("A45Z5_01", "ETCH9", "A", "PPID_Y"),
                    ("A45Z5_02", "CMP1", None, None),      # 결측은 NULL 로
                    ("A45Z5_02", "ETCH9", "B", "PPID_X")]


def test_null_rates_reflect_actual_gaps(tmp_path):
    """결측률이 실제 결측을 반영해야 한다 — 0.0 으로 굳으면 '안 실렸다'를 못 본다."""
    _, report = _load(tmp_path)
    assert report["ch_id_null_rate"] == round(1 / 3, 3)
    assert report["ppid_null_rate"] == round(1 / 3, 3)
    assert not report["fatal"]


# --------------------------------------------------------------------------- #
# ppid grain — 결측률이 못 보는 실패
#
# ppid 는 wafer×스텝 단위(그 wafer 가 그 스텝에서 쓴 PPID)다. 원천에서 lot/recipe
# 마스터에 조인해 오면 결측률은 0.0(초록)인데 lot 전원이 같은 ppid 를 갖게 되어
# hyp_ppid_commonality 가 **에러 없이 틀린 집계**를 낸다. 결측률로는 안 보인다.
#
# 판정은 전역 조건으로만 한다 — 한 lot 이 한 PPID 로 도는 건 정상인 스텝도 많아서
# lot 개별 판정은 오경보가 잦다. 반례(한 군에서 ppid 2값) 1건이면 wafer 단위가
# 증명되므로, "전 데이터에 반례 0건" 일 때만 의심한다.
# --------------------------------------------------------------------------- #
LOT_GRAIN_YIELDS = [{"root_lot_id": "B77Q2", "wafer_id": "01", "lot_id": "B77Q2.1",
                     "yield": 88.0, "date": "2026-07-02"},
                    {"root_lot_id": "B77Q2", "wafer_id": "02", "lot_id": "B77Q2.1",
                     "yield": 55.0, "date": "2026-07-02"}]

# lot 마스터 조인의 서명: 같은 lot×스텝의 두 wafer 가 챔버는 갈리는데 ppid 는 같다
LOT_GRAIN_STEPS = [{"root_lot_id": "B77Q2", "wafer_id": "01", "process_step": "Etch",
                    "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
                   {"root_lot_id": "B77Q2", "wafer_id": "02", "process_step": "Etch",
                    "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_L", "timestamp": "t"}]


def test_ppid_that_never_varies_within_lot_and_step_is_flagged(tmp_path):
    """결측률 0.0 이어도 grain 이 틀렸으면 경고가 떠야 한다."""
    report = li.load(LOT_GRAIN_YIELDS, LOT_GRAIN_STEPS, tmp_path / "t.db",
                     verbose=False)
    assert report["ppid_null_rate"] == 0.0            # 결측률은 못 보는 실패다
    assert report["ppid_grain"] == {"checkable": 1, "varying": 0}
    assert any("마스터 단위 조인 의심" in i for i in report["issues"])
    assert not report["fatal"]                        # 교체는 막지 않는다 (사람이 볼 것)


def test_ppid_grain_is_silent_when_variation_is_structurally_impossible(tmp_path):
    """lot×스텝마다 wafer 가 1장뿐이면 갈릴 수가 없다 — 경고하면 100% 오경보다."""
    yields = [{"root_lot_id": "C31K8", "wafer_id": "01", "lot_id": "C31K8.1",
               "yield": 90.0, "date": "2026-07-03"},
              {"root_lot_id": "C31K8", "wafer_id": "02", "lot_id": "C31K8.2",
               "yield": 70.0, "date": "2026-07-03"}]
    steps = [{"root_lot_id": "C31K8", "wafer_id": "01", "process_step": "Etch",
              "eqp_id": "ETCH9", "ch_id": "A", "ppid": "PPID_L", "timestamp": "t"},
             {"root_lot_id": "C31K8", "wafer_id": "02", "process_step": "Etch",
              "eqp_id": "ETCH9", "ch_id": "B", "ppid": "PPID_L", "timestamp": "t"}]
    report = li.load(yields, steps, tmp_path / "t.db", verbose=False)
    assert report["ppid_grain"] == {"checkable": 0, "varying": 0}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_ppid_grain_accepts_a_single_counterexample_as_proof(tmp_path):
    """한 군에서 ppid 가 갈리면 wafer 단위가 증명된다 — 더미가 이 모양이다.

    이 테스트는 검사에서 DISTINCT 판정이 빠져 무조건 경고하게 되면 실패한다.
    """
    _, report = _load(tmp_path)
    assert report["ppid_grain"] == {"checkable": 1, "varying": 1}
    assert not any("마스터 단위 조인 의심" in i for i in report["issues"])


def test_report_prints_on_a_console_that_cannot_encode_every_character(tmp_path,
                                                                      monkeypatch):
    """cp949 콘솔에서 리포트가 죽으면 안 된다.

    한국어 코드페이지에는 em-dash(U+2014)가 없다. 경고 문구에 그 글자가 하나 있으면
    print 가 UnicodeEncodeError 로 죽는데, `_print` 는 os.replace **뒤에** 불리므로
    DB 는 교체된 채 traceback 만 남고 **사람이 봐야 할 경고 문구가 사라진다** —
    빈 추출·중복 이력처럼 리포트가 가장 필요한 순간이 정확히 이 경로다.
    """
    steps = STEPS + [dict(STEPS[0])]          # wafer×스텝 중복 → em-dash 들어간 경고
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(sys, "stdout", buf)
    li.load(YIELDS, steps, tmp_path / "t.db", verbose=True)
    buf.flush()
    out = buf.buffer.getvalue().decode("cp949")

    assert "재작업" in out                     # 경고 내용이 남아야 한다
    assert "[교체]" in out                     # 경고 뒤 줄까지 끝까지 찍혀야 한다
